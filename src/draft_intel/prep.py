"""DI-039 — ``make prep``. The Sprint 2 gate.

Charter §4.9 makes this core scope, and says why:

    a valuation model you first see three minutes before the auction is one you cannot
    sanity-check. A model you see four days early is one you can argue with, correct, and trust.

    **Timing requirement:** ``make prep`` must produce usable output by the end of Sprint 2,
    even if the cockpit is unfinished. The user should be reading their priced board and arguing
    with it **at least three days before the draft.**

Seven sections, per §4.9. Six are here in full. The one deviation is stated rather than papered
over, because the whole point of this document is that the user can argue with it:

**§4.9 item 1 asks for live auction value at p25/p50/p75. Those labels are not used.** A
percentile implies a sampling distribution, and the 500-run Monte Carlo that would produce one is
Sprint 3 (§8). What is printed instead is a *sourced* band: the low and high come from the two
keeper-price scenarios DI-031 already computes -- prices as loaded against prices under the
league's 75% rule -- which differ by real money and move every price on the board. That is a
range with a stated cause. Labelling it p25/p75 would dress a two-point sensitivity as a
distribution, and the user would reasonably read it as one.

Section 6, the budget scenario planner, is *interactive* in §4.9. A printed report cannot be
interactive, so it renders a fixed set of allocations through the same optimizer. The wiring is
the same either way, which is what §4.9 predicted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from draft_intel.config import LeagueConfig, assert_startable, load_league_config, validate
from draft_intel.domain.identity import build_identity
from draft_intel.domain.keepers import load_manifest, resolve_manifest
from draft_intel.quant.affordability import affordability
from draft_intel.quant.keeper_board import KeeperBoard, keeper_board
from draft_intel.quant.market import (
    AdpMarketValues,
    CsvMarketValues,
    InternalMarketValues,
    ManualMarketValues,
    resolve_market_values,
)
from draft_intel.quant.optimizer import Candidate, best_roster
from draft_intel.quant.overrides import PlayerOverride
from draft_intel.quant.replacement import compute_baselines
from draft_intel.quant.scoring import PlayerProjection, build_projections
from draft_intel.quant.slots import allocate_flex, seat_keepers
from draft_intel.quant.tiers import tier_sheet
from draft_intel.quant.valuation import ValueBoard, value_board
from draft_intel.quant.walkaway import walkaway_board
from draft_intel.store.overrides import OverrideStore

RULE = "=" * 78


def _line(label: str, value: object) -> str:
    return f"  {label:<26} {value}"


class Pipeline(NamedTuple):
    """Everything the priced board is built from, produced once and shared.

    ``build_report`` and the price table both need the whole chain -- config, projections,
    resolved keepers, baselines, the value board, market values, retention prices. Building it
    twice is how two surfaces start quoting different numbers for the same player, which is the
    defect this project has already had once, in the two value bases section 3 was mixing.
    """

    config: LeagueConfig
    board: ValueBoard
    keepers: KeeperBoard
    market: Any
    warnings: list[Any]
    price_source: str
    resolved: Mapping[tuple[str, str], Any]
    identity: Any
    manifest: Any
    demand: Any
    roster_live: int
    keeper_spend: int
    unreliable: Mapping[str, float]
    prices: Mapping[str, int]

    model_market: Any
    """The resolved market with the user's typed values taken back out. Equal to ``market``
    when nothing was typed."""

    model_board: ValueBoard
    """The board as the model computed it, before any override. Never dropped.

    §4.8 requires the model's figure to stay displayable beside the user's, permanently. Keeping
    a whole second board rather than a per-player original is what makes that true for the
    *derived* numbers too: a points override moves replacement level, so it changes VORP and
    dollars for players the user never touched, and only a second full run can say by how much.
    """

    overrides: Mapping[str, PlayerOverride]
    """What the user changed, keyed on ``player_id``. Empty when nothing is overridden."""

    orphan_overrides: tuple[str, ...]
    """Stored overrides matching nobody on the board -- reported, never raised.

    ``apply_overrides`` raises on these, and is right to: an override naming nobody is a typo,
    and dropping it silently leaves the user believing a correction was applied. But the same
    file is read by ``make prep`` at 8am on draft day, and a player who fell out of the
    projection feed overnight must not take the report down. So the pipeline carries them out to
    be displayed, and the API refuses to create one in the first place.
    """


def build_pipeline(root: Path, *, overrides: OverrideStore | None = None) -> Pipeline:
    """Run everything up to the priced board. No rendering, no optimizer.

    Args:
        root: Repository root, holding ``config/`` and ``fixtures/``.
        overrides: Where the user's manual values live. Defaults to
            ``<root>/config/value_overrides.yaml``, which is what makes ``make prep`` and
            ``/prices`` quote the same numbers *by default rather than by discipline*. Pass a
            store on a scratch path to run the model untouched.

    **Overrides enter at two different depths, and the difference is not cosmetic** (DI-062):

    * a **points** override is applied to the projection, *before* :func:`compute_baselines`. It
      is a claim about the player, so everything derived from points has to be rebuilt on top of
      it -- VORP, the replacement baseline, and therefore every other player's dollars by a
      little. Applying it downstream would leave a board whose points and VORP disagree.
    * a **market value** override enters as the highest-priority market provider, so it reaches
      ``floor(0.75 * auction_value)`` and moves the keeper's rule price and surplus. This is the
      only path to a real keeper rule price short of assembling the whole CSV.
    * a **live value** override and the **blacklist** replace the model's derived dollars
      outright, after everything above. They are the last word by construction, per §4.8's
      ``manual > API-derived > model``.

    Values are never renormalised to absorb an edit. ``sum_baseline_value`` on the returned board
    will stop matching ``total_live_money`` once anything is overridden; that gap is a fact to
    display, not an error to correct.
    """

    config_dir, fixtures = root / "config", root / "fixtures"
    config = load_league_config(config_dir / "league.yaml")
    league = json.loads((fixtures / "league.json").read_text())
    real_draft = json.loads((fixtures / "real_draft.json").read_text())
    players_map = json.loads((fixtures / "players_slim.json").read_text())
    projections_raw = json.loads((fixtures / "projections_slim.json").read_text())
    mock_draft = json.loads((fixtures / "draft.json").read_text())
    picks = json.loads((fixtures / "picks.json").read_text())

    warnings = assert_startable(validate(config, league, real_draft))

    store = overrides or OverrideStore(config_dir / "value_overrides.yaml")
    manual = store.as_player_overrides()

    model_projections, unreliable = build_projections(projections_raw, league["scoring_settings"])
    # Points first, upstream of everything. See the docstring: a points override is a claim about
    # the player, and replacement level is computed *from* points, so a board built before the
    # override and patched after it would carry a VORP that no longer follows from its own points.
    projections = _override_points(model_projections, manual)
    manifest = load_manifest(config_dir / "keepers.yaml")
    resolved = resolve_manifest(manifest, players_map)
    keeper_ids = frozenset(pid for _owner, pid in resolved)
    # owners.yaml, not a literal. `cli.py` already reads it through `_aliases("mock_aliases")`;
    # duplicating the mapping here meant editing the config had no effect on this report.
    aliases = yaml.safe_load((config_dir / "owners.yaml").read_text()) or {}
    identity = build_identity(
        mock_draft,
        aliases={**(aliases.get("aliases") or {}), **(aliases.get("mock_aliases") or {})},
    )

    positions_by_slot: dict[int, list[str]] = {}
    for (owner, _pid), entry in resolved.items():
        slot = identity.slot_for(owner)
        if slot is not None:
            positions_by_slot.setdefault(slot, []).append(entry.pos)
    demand = seat_keepers(positions_by_slot, starters=config.starters, teams=config.teams)

    roster_full = config.auction_pool
    roster_live = roster_full - len(keeper_ids)
    keeper_spend = sum(int(p["metadata"]["amount"]) for p in picks if p["player_id"] in keeper_ids)

    def price(source: Sequence[Any]) -> ValueBoard:
        return value_board(
            source,
            baselines=compute_baselines(
                source,
                keeper_ids=keeper_ids,
                demand=demand,
                roster_spots_full=roster_full,
                roster_spots_live=roster_live,
                kicker_slots=config.starters.get("K", 0) * config.teams,
            ),
            keeper_ids=keeper_ids,
            keeper_spend=keeper_spend,
            total_budget=config.teams * config.budget,
            roster_spots_full=roster_full,
            roster_spots_live=roster_live,
        )

    # Two runs when points were overridden, one when they were not. The second is not a
    # convenience: a points override moves the replacement baseline, so it moves dollars for
    # players the user never touched, and "what would the model have said" is unrecoverable from
    # the overridden board alone.
    board = price(projections)
    model_board = board if projections is model_projections else price(model_projections)
    # Dollars last, and they replace rather than adjust: §4.8's `manual > API-derived > model`
    # means a number the user typed is not scaled, renormalised or reconciled afterwards.
    board = _override_money(board, manual)

    typed_market = {pid: o.market_value for pid, o in manual.items() if o.market_value is not None}

    def resolve(providers: Sequence[Any]) -> Any:
        return resolve_market_values(
            [
                *providers,
                CsvMarketValues(config_dir / "auction_values.csv", players_map),
                AdpMarketValues(
                    projections_raw, [p.market_value for p in board.players if p.in_pool_full]
                ),
                InternalMarketValues(
                    {p.player_id: p.market_value for p in board.players if p.in_pool_full}
                ),
            ],
            projections,
            required=roster_full,
        )

    market = resolve([ManualMarketValues(typed_market)] if typed_market else [])
    # The same layer with the user's numbers taken back out, so the page can show what the
    # market said before they touched it. §4.8 again: a figure without the one it replaced is a
    # figure with no provenance. Built only when there is something to compare against.
    model_market = resolve([]) if typed_market else market
    prices, price_source = _retention_prices(resolved, picks, keeper_ids)
    keepers = keeper_board(
        board,
        keeper_owners={pid: owner for owner, pid in resolved},
        slots={
            pid: slot for owner, pid in resolved if (slot := identity.slot_for(owner)) is not None
        },
        prices=prices,
        market=market,
        minimum_retention_price=manifest.league.minimum_retention_price,
    )

    return Pipeline(
        config=config,
        board=board,
        keepers=keepers,
        market=market,
        warnings=warnings,
        price_source=price_source,
        resolved=resolved,
        identity=identity,
        manifest=manifest,
        demand=demand,
        roster_live=roster_live,
        keeper_spend=keeper_spend,
        unreliable=unreliable,
        prices=prices,
        model_market=model_market,
        model_board=model_board,
        overrides=manual,
        orphan_overrides=tuple(sorted(set(manual) - {p.player_id for p in board.players})),
    )


def build_report(root: Path, *, targets: int = 12) -> str:
    """Run the whole pipeline and render the printable report.

    Args:
        root: Repository root, holding ``config/`` and ``fixtures/``.
        targets: How many players get a walk-away price on the target list. Each costs two
            optimizer solves per price point, so this is the knob that decides how long
            ``make prep`` takes; it is not a claim about how many players matter.
    """
    built = build_pipeline(root)
    config, board, keepers = built.config, built.board, built.keepers
    resolved, identity, manifest = built.resolved, built.identity, built.manifest
    demand, roster_live, price_source = built.demand, built.roster_live, built.price_source
    unreliable, prices = built.unreliable, built.prices

    out: list[str] = []
    out += _header(config, built.warnings)
    out += _price_provenance(
        price_source,
        resolved_count=sum(1 for _o, pid in resolved if identity.slot_for(_o) is not None),
        expected_count=config.teams * config.keepers_per_team,
    )
    out += _override_section(built)
    out += _inflation_section(keepers, unreliable)
    out += _keeper_section(keepers, config.teams)
    out += _positional_map(board, demand, roster_live)
    out += _priced_board(board, keepers)
    out += _tier_sheet(board)
    # Derived, never hardcoded. `user_team` is in the manifest and the slot follows from
    # identity; an earlier version hardcoded slot 3 and a $55 keeper spend, and $55 was another
    # manager's figure entirely -- the report contradicted its own section 3 by $7.
    my_slot = identity.slot_for(manifest.user_team)
    my_keeper_spend = sum(
        price
        for (owner, pid), _entry in resolved.items()
        if owner == manifest.user_team and (price := prices.get(pid)) is not None
    )
    out += _scenarios(board, config, my_keeper_spend)
    out += _targets(board, config, limit=targets, keeper_spend=my_keeper_spend)
    out += _affordability_preview(config, my_slot, manifest.user_team)
    return "\n".join(out) + "\n"


def _override_points(
    projections: Sequence[PlayerProjection], manual: Mapping[str, PlayerOverride]
) -> Sequence[PlayerProjection]:
    """Substitute the user's projected points, upstream of replacement level.

    Returns the input object unchanged when nothing is overridden, so ``build_pipeline`` can tell
    by identity whether a second model run is needed at all.
    """
    changed = {pid: o.points for pid, o in manual.items() if o.points is not None}
    if not changed:
        return projections
    return [
        p.model_copy(update={"points": changed[p.player_id]}) if p.player_id in changed else p
        for p in projections
    ]


def _override_money(board: ValueBoard, manual: Mapping[str, PlayerOverride]) -> ValueBoard:
    """Replace the model's live auction value with the user's, and re-add up the board.

    **A market-value override deliberately does not land here.** ``PlayerValue.market_value`` is
    the *model's* book value -- what our own valuation says a player is worth in a keeper-free
    auction -- and ``keeper_board`` reads it as exactly that, alongside the separate provider
    figure from :mod:`draft_intel.quant.market`. Mixing the two value bases is the defect E8
    found in the report's section 3, and writing a number the user typed into the model's own
    book value would reintroduce it one layer down. So a typed market value enters as
    :class:`~draft_intel.quant.market.ManualMarketValues`, where market opinions belong, and the
    model's book value stays the model's.

    For the same reason the blacklist zeroes the live value only. "Never bid" is a statement
    about this auction, not a claim that the player is worthless; zeroing book value there would
    silently move keeper surplus and the inflation figure.

    ``sum_baseline_value`` is recomputed because it is a statement about the players in *this*
    board. ``total_live_money`` is not: it is a property of the room, and an opinion about a
    player's worth does not change how many dollars are in it. That is precisely why the board
    stops reconciling after an edit -- §4.8 says to show that gap rather than close it.
    """
    if not manual:
        return board

    players = []
    for player in board.players:
        override = manual.get(player.player_id)
        if override is None:
            players.append(player)
            continue
        update: dict[str, float] = {}
        if override.baseline_value is not None:
            update["baseline_value"] = round(override.baseline_value, 2)
        if override.blacklisted:
            # "Never bid" is not "bid this much", so the blacklist wins over a typed price too.
            update["baseline_value"] = 0.0
        players.append(player.model_copy(update=update) if update else player)

    return board.model_copy(
        update={
            "players": tuple(players),
            "sum_baseline_value": round(
                sum(p.baseline_value for p in players if p.in_pool_live), 2
            ),
        }
    )


def _retention_prices(
    resolved: Mapping[tuple[str, str], Any],
    picks: Sequence[Mapping[str, Any]],
    keeper_ids: frozenset[str],
) -> tuple[dict[str, int], str]:
    """Retention prices, from the manifest first and the mock's picks feed only as a fallback.

    **The manifest is the authoritative source and was previously not consulted at all.** Every
    price came from ``fixtures/picks.json`` -- a *mock draft* -- and was rendered as "prices as
    loaded" with per-team paid columns and named per-keeper alerts, as though it described this
    league. Setting a manifest price to ``commissioner`` authority changed nothing in the report.

    ``config/keepers.yaml`` states the resolution order: ``sleeper_draft_room`` and
    ``commissioner`` are authoritative, ``estimated`` is not, and *"every number downstream of an
    estimated price is badged as estimated in the UI and in `make prep` output"*. Mock-draft
    money is not even an estimate of this league's prices -- it is a different draft's results --
    so the fallback is labelled explicitly rather than badged.

    Returns ``(prices, provenance label)``.
    """
    from_manifest = {
        pid: entry.price for (_owner, pid), entry in resolved.items() if entry.price is not None
    }
    if len(from_manifest) == len(keeper_ids):
        return from_manifest, "config/keepers.yaml (authoritative)"

    from_mock = {
        p["player_id"]: int(p["metadata"]["amount"])
        for p in picks
        if p["player_id"] in keeper_ids and (p.get("metadata") or {}).get("amount")
    }
    merged = {**from_mock, **from_manifest}
    if from_manifest:
        return merged, (
            f"MIXED: {len(from_manifest)} from config/keepers.yaml, the rest from the MOCK draft"
        )
    return merged, "the MOCK draft's picks feed -- NOT this league"


def _price_provenance(source: str, *, resolved_count: int, expected_count: int) -> list[str]:
    out = [RULE, "KEEPER PRICE PROVENANCE — read this before section 2 or 3", RULE]
    out.append(_line("retention prices from", source))
    # ADR-0006 clause 1: the gate says "priced against the real keeper manifest", and this line
    # is what stops that quietly becoming "priced against as much of it as happened to resolve".
    # The board is built from the manifest either way; what changes with an unresolved keeper is
    # that the tool cannot tell which team holds them, which silently moves both the demand and
    # the surplus for that seat.
    out.append(
        _line(
            "keepers resolved",
            f"{resolved_count} of {expected_count}"
            + ("" if resolved_count == expected_count else "  <-- INCOMPLETE, see DI-043"),
        )
    )
    if "MOCK" in source:
        out.append(
            "\n  !! These are a DIFFERENT DRAFT'S RESULTS, not this league's retention prices.\n"
            "     Every keeper price, surplus, alert and inflation figure below inherits that.\n"
            "     They are not estimates of your prices -- they are somebody else's numbers,\n"
            "     standing in until yours exist.\n"
            "\n     Fix: fill in `price` and `price_source` in config/keepers.yaml. The manifest\n"
            "     is consulted first and wins wherever it has a value."
        )
    return [*out, ""]


def _override_section(built: Pipeline) -> list[str]:
    """What the user changed, printed before any figure that depends on it.

    §4.8: *never let the user forget they are looking at a number they typed rather than a number
    that was measured.* A report that silently prints overridden dollars is exactly that
    forgetting, four days early and in a form they will bring to the draft. So the section sits
    directly under the provenance block and is skipped entirely when nothing is overridden --
    a heading reading "0 overrides" is noise every other week of the year.
    """
    if not built.overrides and not built.orphan_overrides:
        return []

    model = {p.player_id: p for p in built.model_board.players}
    now = {p.player_id: p for p in built.board.players}
    out = [RULE, "YOUR OVERRIDES — these numbers are yours, not the model's", RULE]

    for player_id, override in sorted(
        built.overrides.items(), key=lambda kv: -(now[kv[0]].baseline_value if kv[0] in now else 0)
    ):
        if player_id not in now:
            continue
        was, is_now = model[player_id], now[player_id]
        parts = []
        if override.points is not None:
            parts.append(f"pts {was.points:.1f} -> {is_now.points:.1f}")
        if override.baseline_value is not None:
            parts.append(f"live ${was.baseline_value:.2f} -> ${is_now.baseline_value:.2f}")
        if override.market_value is not None:
            model_market = built.model_market.get(player_id) or was.market_value
            parts.append(f"market ${model_market:.2f} -> ${override.market_value:.2f}")
        if override.blacklisted:
            parts.append("BLACKLISTED, never bid")
        out.append(
            _line(is_now.name, "; ".join(parts) + (f"  [{override.note}]" if override.note else ""))
        )

    if built.orphan_overrides:
        out.append("")
        out.append(
            f"  !! {len(built.orphan_overrides)} override(s) name nobody on the board and are\n"
            f"     being ignored: {', '.join(built.orphan_overrides)}.\n"
            "     A player who left the projection feed, or a hand-edit with a bad player_id."
        )

    # §4.8's visible number. Nothing is renormalised after an edit, so the board stops summing to
    # the money in the room; that gap is stated rather than closed.
    deviation = round(built.board.sum_baseline_value - built.board.total_live_money, 2)
    if abs(deviation) >= 0.01:
        out.append("")
        out.append(_line("board now sums to", f"${built.board.sum_baseline_value:,.0f}"))
        out.append(_line("against live money of", f"${built.board.total_live_money:,}"))
        out.append(_line("deviation", f"${deviation:+,.0f}  <-- NOT renormalised, deliberately"))
    return [*out, ""]


# --------------------------------------------------------------------------- sections


def _header(config: LeagueConfig, warnings: Sequence[Any]) -> list[str]:
    out = [
        RULE,
        "DRAFT INTELLIGENCE — PRE-DRAFT REPORT",
        RULE,
        _line("draft starts", config.draft_start),
        _line(
            "auction pool",
            f"{config.teams} teams x {config.draft_rounds} rounds = {config.auction_pool} bought",
        ),
        _line("money in the room", f"${config.teams * config.budget}"),
        _line("roster capacity", f"{config.roster_size} per team"),
    ]
    for warning in warnings:
        out.append(f"  WARN {warning}")
    if not warnings:
        out.append("  config: clean")
    return [*out, ""]


def _inflation_section(keepers: KeeperBoard, unreliable: Mapping[str, float]) -> list[str]:
    """§4.9 item 2: the structural figure, one number, stated plainly."""
    out = [
        RULE,
        "2. STRUCTURAL KEEPER INFLATION — the single most actionable pre-draft number",
        RULE,
    ]
    for scenario in (keepers.under_rule, keepers.as_loaded):
        if not scenario.complete:
            out.append(
                _line(
                    scenario.label,
                    f"not computable: {scenario.missing} keeper(s) have no price",
                )
            )
            continue
        over = (scenario.keeper_inflation - 1) * 100
        direction = "OVER" if over >= 0 else "UNDER"
        out.append(
            _line(
                scenario.label,
                f"{scenario.keeper_inflation:.4f}x  -> expect the field to clear about "
                f"{abs(over):.0f}% {direction} book value",
            )
        )
        out.append(
            _line(
                "",
                f"SK ${scenario.keeper_spend}, live money ${scenario.total_live_money}, "
                f"keeper surplus ${scenario.keeper_surplus:+.0f}",
            )
        )
    out.append("")
    out.append(
        "  Why: each keeper retained below open-market value leaves the room holding more money\n"
        "  than the board still on it is worth. That surplus has nowhere to go but into prices."
    )
    if keepers.market_is_estimate:
        out.append(
            f"\n  !! Auction values came from {keepers.market_source!r}, not real market prices.\n"
            "     Every rule-implied figure above is an ESTIMATE. Drop real values into\n"
            "     config/auction_values.csv to replace them."
        )
    for position, median in sorted(unreliable.items()):
        out.append(
            f"  !! {position} scored from Sleeper's pts_ppr, not raw stats: the league's own\n"
            f"     scoring diverges by a median {median:.1f}% because the projections do not\n"
            f"     carry every stat this league scores."
        )
    return [*out, ""]


def _keeper_section(keepers: KeeperBoard, teams: int) -> list[str]:
    """§4.9 item 3: per team, with effective buying power."""
    out = [RULE, "3. KEEPER SURPLUS BOARD — effective buying power per team", RULE]
    # Two different value bases meet in this section and used to be printed side by side with
    # nothing saying so. `book` is OUR model's full-market valuation, which is what §4.3 defines
    # surplus against. `rule $` below is `floor(0.75 x consensus)`, and the consensus is the
    # market PROVIDER's number, because the league rule is written against Sleeper's auction
    # value rather than against anything we compute. A reader could not reconcile a book of $50
    # with a rule of $27 from anything on the page, and would reasonably assume one was wrong.
    # Both columns are shown, so the arithmetic closes in both directions.
    out.append(
        "  `book` is this model's full-market value (what §4.3 measures surplus against);\n"
        "  `mkt` is the market provider's consensus, which is what the 75% rule is applied to.\n"
        "  They are different numbers on purpose; the alerts below use `mkt`, the surplus"
        " column uses `book`.\n"
    )
    out.append(
        f"  {'owner':8} {'keepers':34} {'book':>6} {'mkt':>6} {'paid':>6} {'surplus':>8} "
        f"{'eff. power':>11}"
    )
    rows: list[tuple[float, str]] = []
    for owner, lines in sorted(keepers.by_team().items()):
        book = sum(line.book_value for line in lines)
        consensus = sum(line.market_value or 0 for line in lines)
        paid = sum(line.price_paid or 0 for line in lines)
        surplus = book - paid
        # Charter §4.6: two teams both showing $150 remaining are not equal if one captured $40
        # of keeper surplus and the other captured $6.
        #
        # Divided by the league's team count, never by the number of teams that happen to hold
        # keepers. Those differ the moment one team keeps nobody -- which the API's own
        # `max_keepers: 1` makes entirely possible -- and dividing by the smaller number
        # inflated every other team's buying power by $22.
        power = (keepers.as_loaded.total_budget // teams) - paid + surplus
        names = ", ".join(line.name.split()[-1] for line in lines)
        rows.append(
            (
                surplus,
                f"  {owner:8} {names[:34]:34} {book:>6.0f} {consensus:>6.0f} {paid:>6} "
                f"{surplus:>+8.0f} {power:>11.0f}",
            )
        )
    for _surplus, row in sorted(rows, reverse=True):
        out.append(row)

    by_position: dict[str, float] = {}
    for line in keepers.lines:
        by_position[line.position] = by_position.get(line.position, 0.0) + (line.surplus or 0.0)
    out.append("\n  surplus by position (§4.6: concentration at QB confirms the scarcity thesis)")
    for position, surplus in sorted(by_position.items(), key=lambda kv: -kv[1]):
        out.append(_line(position, f"${surplus:+.0f}"))
    for alert in keepers.alerts()[:6]:
        out.append(f"  ALERT {alert}")
    return [*out, ""]


def _positional_map(board: ValueBoard, demand: Any, roster_live: int) -> list[str]:
    """§4.9 item 4: remaining supply vs remaining demand, QB first."""
    out = [RULE, "4. POSITIONAL MARKET MAP — supply against demand after keepers", RULE]
    out.append(f"  {'pos':5} {'startable':>10} {'need':>6} {'ratio':>7} {'top $':>7} {'cliff':>7}")
    order = ["QB", "RB", "WR", "TE", "K"]
    remaining_base = demand.remaining_base
    # §4.5: FLEX is allocated "proportionally to remaining positional demand", not split evenly.
    # An even three-way split with a floor discarded 2 of the 20 remaining FLEX slots, so the
    # need column summed to 78 while the line two rows below printed 80 -- the same page stating
    # both numbers. Largest-remainder keeps the total exact.
    flex_share = allocate_flex(demand.remaining_flex, remaining_base)
    for position in order:
        available = sorted(
            (p for p in board.available() if p.position == position and p.in_pool_live),
            key=lambda p: -p.baseline_value,
        )
        need = remaining_base.get(position, 0) + flex_share.get(position, 0)
        ratio = len(available) / need if need else float("inf")
        cliff = _cliff(available)
        top = available[0].baseline_value if available else 0.0
        out.append(
            f"  {position:5} {len(available):>10} {need:>6} {ratio:>7.2f} {top:>7.2f} {cliff:>7}"
        )
    out.append(
        f"\n  {demand.remaining_starting} starting slots and {roster_live} roster spots remain."
        "\n  They are different numbers and are easy to transpose; both are asserted."
    )
    return [*out, ""]


def _cliff(available: Sequence[Any]) -> str:
    """The biggest single price drop inside the top of a position, and where it falls."""
    top = available[:14]
    if len(top) < 2:
        return "--"
    gaps = [(top[i].baseline_value - top[i + 1].baseline_value, i + 1) for i in range(len(top) - 1)]
    gap, index = max(gaps)
    return f"${gap:.0f}@{index}"


def _priced_board(board: ValueBoard, keepers: KeeperBoard) -> list[str]:
    """§4.9 item 1: the priced board, with a sourced range rather than invented percentiles."""
    out = [RULE, "1. THE PRICED BOARD — top 30 available, by live auction value", RULE]
    # `base` below is priced under the AS-LOADED scenario, so the alternate price is
    # `base x (under_rule / as_loaded)` -- a SIGNED ratio. An earlier version sorted the two
    # inflations into low/high and then always rendered the band upward from `base`, which is
    # correct only while the keepers happen to be loaded above the 75% rule. Flip that -- the
    # charter's own keeper thesis, keepers retained BELOW market -- and the true alternate price
    # fell outside the printed band, on the opposite side, under a byte-identical label.
    priced_infl = keepers.as_loaded.keeper_inflation if keepers.as_loaded.complete else None
    other_infl = keepers.under_rule.keeper_inflation if keepers.under_rule.complete else None
    if priced_infl and other_infl:
        scale = other_infl / priced_infl
        direction = "above" if scale > 1 else "below"
        out.append(
            f"  Two points, not a distribution. `LIVE $` prices the AS-LOADED scenario\n"
            f"  ({priced_infl:.3f}x); `rule $` prices the same player under the 75% rule\n"
            f"  ({other_infl:.3f}x), which on this slate lands {direction} it by "
            f"{abs(scale - 1) * 100:.0f}%.\n"
            "  NOT p25/p50/p75: a percentile implies a sampling distribution, and the 500-run\n"
            "  Monte Carlo that would produce one is Sprint 3. Labelling a two-point\n"
            "  sensitivity as percentiles would be read as something it is not.\n"
        )
    else:
        scale = 1.0
        out.append(
            "  Only one keeper-price scenario is complete, so no alternate price is shown.\n"
        )
    # The board's money identity, printed so it can be checked by eye. Every price on this page
    # scales with `total_live_money`, and deleting the keeper-spend sum outright moved the top
    # asset from $26.60 to $37.32 with the whole test suite green -- 97% line coverage measures
    # which statements ran, not which numbers were checked.
    priced_total = sum(p.baseline_value for p in board.players if p.in_pool_live)
    out.append(
        f"  Reconciles: ${priced_total:,.0f} of talent priced against ${board.total_live_money:,}"
        f" of live money (${board.total_budget:,} pot less ${board.keeper_spend:,} on keepers).\n"
    )
    out.append(
        f"  {'#':>3} {'player':24} {'pos':4} {'pts':>7} {'VORP':>7} "
        f"{'LIVE $':>7} {'rule $':>7} {'book $':>7}"
    )
    for index, player in enumerate(board.available()[:30], 1):
        base = player.baseline_value
        out.append(
            f"  {index:>3} {player.name[:24]:24} {player.position:4} {player.points:>7.1f} "
            f"{player.vorp_live:>7.1f} {base:>7.2f} {base * scale:>7.2f} "
            f"{player.market_value:>7.2f}"
        )
    return [*out, ""]


def _tier_sheet(board: ValueBoard) -> list[str]:
    """§4.9 item 5: the thing to print and put on the desk."""
    out = [RULE, "5. TIER SHEET — breaks found in the board, never declared", RULE]
    sheet = tier_sheet(
        [
            (p.player_id, p.name, p.position, p.baseline_value)
            for p in board.available()
            if p.in_pool_live
        ]
    )
    for position in ["QB", "RB", "WR", "TE", "K"]:
        tiers = sheet.get(position, [])
        out.append(f"\n  {position}")
        for tier in tiers[:4]:
            names = ", ".join(name.split()[-1] for _pid, name, _v in tier.players[:6])
            more = f" +{tier.size - 6}" if tier.size > 6 else ""
            out.append(
                f"    T{tier.number} ${tier.top_value:.0f}-${tier.bottom_value:.0f}  {names}{more}"
            )
            if tier.gap_below:
                out.append(f"        -- ${tier.gap_below:.0f} cliff below this tier --")
    return [*out, ""]


def _candidates(board: ValueBoard) -> list[Candidate]:
    return [
        Candidate(
            player_id=p.player_id,
            name=p.name,
            position=p.position,
            points=p.points,
            vorp=p.vorp_live,
            price=max(1, round(p.baseline_value)),
        )
        for p in board.available()
        if p.in_pool_live
    ]


def _scenarios(board: ValueBoard, config: LeagueConfig, my_keeper_spend: int) -> list[str]:
    """§4.9 item 6, rendered as fixed allocations because a printed page cannot be interactive.

    **What varies is the allocation across positions, not a single budget scalar.** An earlier
    version varied only the keeper cost and printed three rows with the identical roster shape,
    which is a budget-*level* sensitivity. §4.9's stated question is *"if I spend $75 on two QBs,
    what does the rest of my roster look like?"* -- an allocation question. Pre-committing spend
    at a position is what the optimizer's ``forced`` argument already does, so this is the wiring
    §4.9 predicted rather than a new engine.
    """
    out = [
        RULE,
        "6. BUDGET SCENARIOS — pre-commit at a position, see what the rest of the roster becomes",
        RULE,
    ]
    candidates = _candidates(board)
    slots = config.draft_rounds - config.keepers_per_team
    budget = config.budget - my_keeper_spend
    out.append(
        f"  From ${budget} across {slots} slots, after your ${my_keeper_spend} of keepers.\n"
    )
    out.append(f"  {'scenario':34} {'spend':>7} {'starting pts':>13} {'starting shape':>28}")

    baseline = best_roster(candidates, budget=budget, slots=slots, starters=dict(config.starters))
    rows: list[tuple[str, Any]] = [("no pre-commitment", baseline)]
    for label, position, count in (
        ("two QBs at the top", "QB", 2),
        ("two RBs at the top", "RB", 2),
        ("an elite TE", "TE", 1),
    ):
        top = sorted((c for c in candidates if c.position == position), key=lambda c: -c.points)[
            :count
        ]
        if len(top) < count:
            continue
        rows.append(
            (
                f"{label} (${sum(c.price for c in top)})",
                best_roster(
                    candidates,
                    budget=budget,
                    slots=slots,
                    starters=dict(config.starters),
                    forced=top,
                ),
            )
        )

    for label, roster in rows:
        if roster.objective == float("-inf"):
            # Carry the optimizer's own caveats to the page. Branching on the objective alone
            # printed a bare "infeasible" and dropped every note behind it, so a board the
            # optimizer had only *capped* read as one it had actually exhausted.
            out.append(f"  {label:34} {'--':>7} {'infeasible':>13}")
            out.extend(f"      {note}" for note in roster.notes)
            continue
        shape: dict[str, int] = {}
        for player in roster.starters:
            shape[player.position] = shape.get(player.position, 0) + 1
        delta = roster.starting_points - baseline.starting_points
        out.append(
            f"  {label:34} {roster.spent:>7} {roster.starting_points:>13.0f} "
            f"{' '.join(f'{k}{v}' for k, v in sorted(shape.items())):>28}"
            + (f"  ({delta:+.0f})" if roster is not baseline else "")
        )
    out.append(
        "\n  Same optimizer as the walk-away curve, so these are the numbers the live tool will\n"
        "  produce. The bracketed figure is the cost in projected starting points of committing\n"
        "  to that shape rather than letting the optimizer choose."
    )
    return [*out, ""]


def _targets(
    board: ValueBoard, config: LeagueConfig, *, limit: int, keeper_spend: int
) -> list[str]:
    """§4.9 item 7: the target list, with walk-away prices."""
    out = [RULE, "7. TARGET LIST — walk-away price per player", RULE]
    candidates = _candidates(board)
    slots = config.draft_rounds - config.keepers_per_team
    budget = config.budget - keeper_spend
    curves = walkaway_board(
        candidates,
        budget=budget,
        slots=slots,
        starters=dict(config.starters),
        top=limit,
        prices=list(range(1, min(budget - slots + 1, 61), 3)),
    )
    out.append(
        f"  From ${budget} across {slots} slots. The walk-away price is the MOST you should pay,\n"
        "  not a recommendation to pay it. Moving the bench weight moves every number here.\n"
    )
    out.append(f"  {'player':24} {'pos':4} {'live $':>7} {'walk away':>10} {'monotone':>9}")
    for curve in curves.curves:
        price = "never" if curve.walk_away_price is None else f"${curve.walk_away_price}"
        board_price = next((c.price for c in candidates if c.player_id == curve.player_id), 0)
        out.append(
            f"  {curve.name[:24]:24} {curve.position:4} {board_price:>7} {price:>10} "
            f"{'ok' if curve.monotone else 'BROKEN':>9}"
        )
    if any(not curve.monotone for curve in curves.curves):
        out.append(
            "\n  !! A non-monotone curve means the optimizer is not returning optima and the\n"
            "     walk-away numbers above cannot be trusted. This is a bug, not a market signal."
        )
    return [*out, ""]


def _affordability_preview(config: LeagueConfig, my_slot: int | None, owner: str) -> list[str]:
    """A pre-draft look at §4.7c, before anybody has bid anything.

    ``my_slot`` is derived from the manifest's ``user_team`` through identity resolution, never
    hardcoded. The literal it replaced happened to be correct today and was wrong by
    construction -- and there is a real state, six managers still unjoined, where no slot
    resolves at all. That is reported rather than guessed.
    """
    from draft_intel.domain.ledger import fold

    if my_slot is None:
        return [
            RULE,
            "OPPONENT AFFORDABILITY — unavailable",
            RULE,
            _line("blocked", f"{owner!r} has no resolved draft slot; see DI-043"),
            "",
        ]
    state = fold(
        [], slots=range(1, config.teams + 1), budget=config.budget, total_slots=config.draft_rounds
    )
    result = affordability(
        state, position="QB", my_slot=my_slot, starters=config.starters, positions={}
    )
    return [
        RULE,
        "OPPONENT AFFORDABILITY — the shape before a dollar is spent",
        RULE,
        _line("my max bid", f"${result.my_max_bid} across {result.my_open_slots} open slots"),
        _line("clears the field", f"${result.price_that_clears_the_field()}"),
        "",
        "  Every team starts identical here. Keeper prices break the symmetry immediately, and\n"
        "  §1.1 is explicit that every consumer must read the per-team figure rather than\n"
        "  assuming a shared one. That divergence is what the surplus board above measures.",
        "",
    ]


def main(root: Path | None = None, out_path: Path | None = None, *, targets: int = 12) -> int:
    """Render the report to stdout and to ``reports/prep.txt``."""
    root = root or Path(__file__).resolve().parents[2]
    report = build_report(root, targets=targets)
    print(report)
    destination = out_path or (root / "reports" / "prep.txt")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report)
    print(f"written to {destination}")
    return 0
