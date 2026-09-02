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
from typing import Any

from draft_intel.config import LeagueConfig, assert_startable, load_league_config, validate
from draft_intel.domain.identity import build_identity
from draft_intel.domain.keepers import load_manifest, resolve_manifest
from draft_intel.quant.affordability import affordability
from draft_intel.quant.keeper_board import KeeperBoard, keeper_board
from draft_intel.quant.market import (
    AdpMarketValues,
    CsvMarketValues,
    InternalMarketValues,
    resolve_market_values,
)
from draft_intel.quant.optimizer import Candidate, best_roster
from draft_intel.quant.replacement import compute_baselines
from draft_intel.quant.scoring import build_projections
from draft_intel.quant.slots import FLEX_ELIGIBLE, seat_keepers
from draft_intel.quant.tiers import tier_sheet
from draft_intel.quant.valuation import ValueBoard, value_board
from draft_intel.quant.walkaway import walkaway_board

RULE = "=" * 78


def _line(label: str, value: object) -> str:
    return f"  {label:<26} {value}"


def build_report(root: Path, *, targets: int = 12) -> str:
    """Run the whole pipeline and render the printable report.

    Args:
        root: Repository root, holding ``config/`` and ``fixtures/``.
        targets: How many players get a walk-away price on the target list. Each costs two
            optimizer solves per price point, so this is the knob that decides how long
            ``make prep`` takes; it is not a claim about how many players matter.
    """
    config_dir, fixtures = root / "config", root / "fixtures"
    config = load_league_config(config_dir / "league.yaml")
    league = json.loads((fixtures / "league.json").read_text())
    real_draft = json.loads((fixtures / "real_draft.json").read_text())
    players_map = json.loads((fixtures / "players_slim.json").read_text())
    projections_raw = json.loads((fixtures / "projections_slim.json").read_text())
    mock_draft = json.loads((fixtures / "draft.json").read_text())
    picks = json.loads((fixtures / "picks.json").read_text())

    out: list[str] = []
    warnings = assert_startable(validate(config, league, real_draft))
    out += _header(config, warnings)

    projections, unreliable = build_projections(projections_raw, league["scoring_settings"])
    manifest = load_manifest(config_dir / "keepers.yaml")
    resolved = resolve_manifest(manifest, players_map)
    keeper_ids = frozenset(pid for _owner, pid in resolved)
    identity = build_identity(mock_draft, aliases={"Me": "Matt"})

    positions_by_slot: dict[int, list[str]] = {}
    for (owner, _pid), entry in resolved.items():
        slot = identity.slot_for(owner)
        if slot is not None:
            positions_by_slot.setdefault(slot, []).append(entry.pos)
    demand = seat_keepers(positions_by_slot, starters=config.starters, teams=config.teams)

    roster_full = config.auction_pool
    roster_live = roster_full - len(keeper_ids)
    keeper_spend = sum(int(p["metadata"]["amount"]) for p in picks if p["player_id"] in keeper_ids)
    baselines = compute_baselines(
        projections,
        keeper_ids=keeper_ids,
        demand=demand,
        roster_spots_full=roster_full,
        roster_spots_live=roster_live,
        kicker_slots=config.starters.get("K", 0) * config.teams,
    )
    board = value_board(
        projections,
        baselines=baselines,
        keeper_ids=keeper_ids,
        keeper_spend=keeper_spend,
        total_budget=config.teams * config.budget,
        roster_spots_full=roster_full,
        roster_spots_live=roster_live,
    )

    market = resolve_market_values(
        [
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
    keepers = keeper_board(
        board,
        keeper_owners={pid: owner for owner, pid in resolved},
        slots={
            pid: slot for owner, pid in resolved if (slot := identity.slot_for(owner)) is not None
        },
        prices={
            p["player_id"]: int(p["metadata"]["amount"])
            for p in picks
            if p["player_id"] in keeper_ids and (p.get("metadata") or {}).get("amount")
        },
        market=market,
        minimum_retention_price=manifest.league.minimum_retention_price,
    )

    out += _inflation_section(keepers, unreliable)
    out += _keeper_section(keepers)
    out += _positional_map(board, demand, roster_live)
    out += _priced_board(board, keepers)
    out += _tier_sheet(board)
    out += _scenarios(board, config)
    out += _targets(board, config, limit=targets)
    out += _affordability_preview(config)
    return "\n".join(out) + "\n"


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


def _keeper_section(keepers: KeeperBoard) -> list[str]:
    """§4.9 item 3: per team, with effective buying power."""
    out = [RULE, "3. KEEPER SURPLUS BOARD — effective buying power per team", RULE]
    out.append(
        f"  {'owner':8} {'keepers':34} {'book':>6} {'paid':>6} {'surplus':>8} {'eff. power':>11}"
    )
    rows: list[tuple[float, str]] = []
    for owner, lines in sorted(keepers.by_team().items()):
        book = sum(line.book_value for line in lines)
        paid = sum(line.price_paid or 0 for line in lines)
        surplus = book - paid
        # Charter §4.6: two teams both showing $150 remaining are not equal if one captured $40
        # of keeper surplus and the other captured $6.
        power = (keepers.as_loaded.total_budget // len(keepers.by_team())) - paid + surplus
        names = ", ".join(line.name.split()[-1] for line in lines)
        rows.append(
            (
                surplus,
                f"  {owner:8} {names[:34]:34} {book:>6.0f} {paid:>6} {surplus:>+8.0f} "
                f"{power:>11.0f}",
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
    for position in order:
        available = sorted(
            (p for p in board.available() if p.position == position and p.in_pool_live),
            key=lambda p: -p.baseline_value,
        )
        need = remaining_base.get(position, 0)
        if position in FLEX_ELIGIBLE:
            need += demand.remaining_flex // len(FLEX_ELIGIBLE)
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
    low_ratio = (
        keepers.as_loaded.keeper_inflation
        if keepers.as_loaded.complete
        else keepers.under_rule.keeper_inflation
        if keepers.under_rule.complete
        else 1.0
    )
    high_ratio = keepers.under_rule.keeper_inflation if keepers.under_rule.complete else low_ratio
    low_ratio, high_ratio = min(low_ratio, high_ratio), max(low_ratio, high_ratio)
    out.append(
        f"  Range = the two keeper-price scenarios, {low_ratio:.3f}x to {high_ratio:.3f}x.\n"
        "  NOT p25/p50/p75: a percentile implies a sampling distribution, and the 500-run\n"
        "  Monte Carlo that would produce one is Sprint 3. This is a two-point sensitivity\n"
        "  with a stated cause, which is a different and more honest thing.\n"
    )
    out.append(
        f"  {'#':>3} {'player':24} {'pos':4} {'pts':>7} {'VORP':>7} "
        f"{'low':>6} {'LIVE $':>7} {'high':>6} {'book $':>7}"
    )
    # The live board is priced under the as-loaded scenario, so the band scales it by the ratio
    # between the two scenarios rather than by either one alone.
    scale = high_ratio / low_ratio if low_ratio else 1.0
    for index, player in enumerate(board.available()[:30], 1):
        base = player.baseline_value
        low, high = min(base, base * scale), max(base, base * scale)
        out.append(
            f"  {index:>3} {player.name[:24]:24} {player.position:4} {player.points:>7.1f} "
            f"{player.vorp_live:>7.1f} {low:>6.0f} {base:>7.2f} {high:>6.0f} "
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


def _scenarios(board: ValueBoard, config: LeagueConfig) -> list[str]:
    """§4.9 item 6, rendered as fixed allocations because a printed page cannot be interactive."""
    out = [
        RULE,
        "6. BUDGET SCENARIOS — the best roster reachable from each starting position",
        RULE,
    ]
    candidates = _candidates(board)
    slots = config.draft_rounds - config.keepers_per_team
    budget = config.budget
    out.append(f"  {'scenario':34} {'spend':>7} {'starting pts':>13} {'shape':>28}")
    for label, spent_on_keepers in (
        ("keepers cost $30 (cheap studs)", 30),
        ("keepers cost $55 (the mock)", 55),
        ("keepers cost $80 (paid up)", 80),
    ):
        left = budget - spent_on_keepers
        roster = best_roster(candidates, budget=left, slots=slots, starters=dict(config.starters))
        if roster.objective == float("-inf"):
            out.append(f"  {label:34} {'--':>7} {'infeasible':>13}")
            continue
        shape: dict[str, int] = {}
        for player in roster.starters:
            shape[player.position] = shape.get(player.position, 0) + 1
        out.append(
            f"  {label:34} {roster.spent:>7} {roster.starting_points:>13.0f} "
            f"{' '.join(f'{k}{v}' for k, v in sorted(shape.items())):>28}"
        )
    out.append(
        "\n  Same optimizer as the walk-away curve, so these are the same numbers the live tool\n"
        "  will produce. Keeper cost is the only thing varied; everything else follows."
    )
    return [*out, ""]


def _targets(board: ValueBoard, config: LeagueConfig, *, limit: int) -> list[str]:
    """§4.9 item 7: the target list, with walk-away prices."""
    out = [RULE, "7. TARGET LIST — walk-away price per player", RULE]
    candidates = _candidates(board)
    slots = config.draft_rounds - config.keepers_per_team
    budget = config.budget - 55  # the mock's keeper spend for this seat
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
    for curve in curves:
        price = "never" if curve.walk_away_price is None else f"${curve.walk_away_price}"
        board_price = next((c.price for c in candidates if c.player_id == curve.player_id), 0)
        out.append(
            f"  {curve.name[:24]:24} {curve.position:4} {board_price:>7} {price:>10} "
            f"{'ok' if curve.monotone else 'BROKEN':>9}"
        )
    if any(not curve.monotone for curve in curves):
        out.append(
            "\n  !! A non-monotone curve means the optimizer is not returning optima and the\n"
            "     walk-away numbers above cannot be trusted. This is a bug, not a market signal."
        )
    return [*out, ""]


def _affordability_preview(config: LeagueConfig) -> list[str]:
    """A pre-draft look at §4.7c, before anybody has bid anything."""
    from draft_intel.domain.ledger import fold

    state = fold(
        [], slots=range(1, config.teams + 1), budget=config.budget, total_slots=config.draft_rounds
    )
    result = affordability(state, position="QB", my_slot=3, starters=config.starters, positions={})
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
