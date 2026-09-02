"""Sprint 1 command line: replay a completed draft, or smoke-test the live API.

There is no cockpit yet. These two commands are how the data spine is exercised by hand.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from draft_intel.config import Severity, assert_startable, load_league_config, validate
from draft_intel.domain.classify import KeeperClassifier, keepers_seen, reconcile
from draft_intel.domain.identity import (
    Identity,
    UnresolvedManifest,
    build_identity,
    manifest_keys,
)
from draft_intel.domain.keepers import load_manifest, resolve_manifest
from draft_intel.domain.ledger import fold
from draft_intel.models import PickClass
from draft_intel.quant.keeper_board import keeper_board
from draft_intel.quant.market import (
    AdpMarketValues,
    CsvMarketValues,
    InternalMarketValues,
    resolve_market_values,
)
from draft_intel.quant.replacement import compute_baselines
from draft_intel.quant.scoring import build_projections
from draft_intel.quant.slots import seat_keepers
from draft_intel.quant.valuation import value_board
from draft_intel.replay.harness import load_picks, replay_all, replay_rejects
from draft_intel.sleeper.client import SleeperClient

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
CONFIG = ROOT / "config"

USERNAME = "mattchupiccu"
LEAGUE_ID = "1391959336820953088"
REAL_DRAFT_ID = "1391959337445920768"


def _aliases(key: str = "aliases") -> dict[str, str]:
    data = yaml.safe_load((CONFIG / "owners.yaml").read_text()) or {}
    merged = dict(data.get("aliases") or {})
    merged.update(data.get(key) or {} if key != "aliases" else {})
    return merged


def _or_dash(figure: float | int | None) -> str:
    """Render an unknown as a dash. A missing price is not a zero, and must never read as one.

    ``-0`` is normalised to ``0``: it is what a small negative rounds to at zero decimals, and a
    minus sign in a money column reads as a real deficit rather than as rounding.
    """
    if figure is None:
        return "--"
    rendered = f"{figure:.0f}"
    return "0" if rendered == "-0" else rendered


def _classifier(
    draft: dict[str, Any],
    players: dict[str, Any],
    identity: Identity,
    *,
    require: int | None,
    armed: bool = True,
) -> KeeperClassifier:
    """Build the pick classifier from the resolved manifest.

    **Armed by default, which it had not been from any product path.** ``KeeperClassifier.armed``
    is the charter's classification mechanism #4 -- an unmatched pick inside the ceremonial
    window is FLAGGED for confirmation rather than silently treated as a competitive bid -- and
    it was set ``True`` by nothing outside `tests/`. The backstop existed and never ran.

    What it backstops is not hypothetical here. The manifest is a file typed in August; the
    ceremonial keeper picks land in the first twenty picks on the night. A keeper swapped after
    the manifest was written matches nothing, and unarmed it becomes a COMPETITIVE pick worth
    real money against a player we still show as available. Armed, it is FLAGGED and the operator
    is asked.

    The window is ``arming_window`` picks, not the whole draft, so a genuine competitive bid in
    round three is never flagged, and on a manifest that resolves fully it changes nothing at
    all -- the mock replays to the same 20 KEEPER / 140 COMPETITIVE ledger either way. Drop one
    manifest key and the difference is the whole point:

    ===========  ===========================================
    unarmed      19 KEEPER, **141 COMPETITIVE**
    armed        19 KEEPER, 140 COMPETITIVE, **1 FLAGGED**
    ===========  ===========================================

    ``armed=False`` remains available for callers that genuinely want the raw classification,
    but no product path uses it.
    """
    manifest = load_manifest(CONFIG / "keepers.yaml")
    resolved = resolve_manifest(manifest, players)
    return KeeperClassifier(
        manifest_keys=manifest_keys(resolved, identity, require=require), armed=armed
    )


def replay() -> int:
    """Replay the completed mock draft and print the final ledger."""
    payload = load_picks(FIXTURES / "picks.json")
    draft = json.loads((FIXTURES / "draft.json").read_text())
    players = json.loads((FIXTURES / "players_slim.json").read_text())
    identity = build_identity(draft, aliases=_aliases("mock_aliases"))
    config = load_league_config(CONFIG / "league.yaml")
    manifest = load_manifest(CONFIG / "keepers.yaml")
    state = fold(
        replay_all(payload),
        slots=range(1, config.teams + 1),
        budget=config.budget,
        total_slots=config.draft_rounds,
        max_keepers=config.keepers_per_team,
        classifier=_classifier(
            draft, players, identity, require=config.teams * config.keepers_per_team
        ),
        expect_keepers=True,
        rejects=replay_rejects(payload),
    )

    print(
        f"{'slot':>4}  {'owner':<8} {'picks':>5} {'keep':>4} {'spent':>6} {'left':>5} {'maxbid':>7}"
    )
    for slot, team in sorted(state.teams.items()):
        print(
            f"{slot:>4}  {identity.owner_for(slot):<8} {team.filled_slots:>5} "
            f"{len(team.keepers):>4} {team.spent:>6} {team.remaining:>5} {team.max_bid:>7}"
        )
    recorded = {s: [(r.player_id, r.amount) for r in t.keepers] for s, t in state.teams.items()}
    seen, complete = keepers_seen(recorded)

    # Reconciliation against the manifest. This is the readout that catches a wrong price, a
    # keeper that quietly changed, or a team entering only one - the errors most likely to
    # actually occur on draft night, each of which silently corrupts a budget for the evening.
    # The function existed from Sprint 1 and was called by nothing outside tests.
    expected: dict[int, list[tuple[str, int | None]]] = {}
    for (owner, player_id), entry in resolve_manifest(manifest, players).items():
        # Deliberately not named `slot`: that name is already bound as an `int` by the
        # ledger loop above, and reusing it here for an `int | None` is the kind of shadowing
        # that reads as correct right up until someone moves one of the two loops.
        owner_slot = identity.slot_for(owner)
        if owner_slot is not None:
            expected.setdefault(owner_slot, []).append((player_id, entry.price))

    total_keepers = config.teams * config.keepers_per_team
    print(
        f"\ntotal spent ${state.total_spent}  remaining ${state.total_remaining}  "
        f"keeper spend ${state.keeper_spend()}"
    )
    print(f"keepers seen: {seen}/{total_keepers}   teams complete: {complete}/{config.teams}")
    print(f"competitive picks: {len(state.competitive_seq)}")
    for line in reconcile(recorded, expected, keepers_per_team=config.keepers_per_team):
        print(f"  RECONCILE {line}")
    # A FLAGGED pick is the armed classifier saying "this looks like a keeper the manifest does
    # not know about". Printing it is what makes the backstop a backstop: the classification
    # already keeps the pick out of the competitive series, but the thing that needs to happen
    # is a human confirming or denying it, and they cannot do that from a count.
    # `flagged_slot`/`roster_entry`, not `slot`/`entry`: both of those names are already bound
    # in this function -- `entry` to a `KeeperEntry` from the manifest loop just above -- and
    # reusing them is the shadowing the comment there warns about. mypy caught it.
    flagged = [
        (flagged_slot, roster_entry)
        for flagged_slot, flagged_team in sorted(state.teams.items())
        for roster_entry in flagged_team.roster
        if roster_entry.pick_class is PickClass.FLAGGED
    ]
    for flagged_slot, roster_entry in flagged:
        print(
            f"  FLAGGED slot {flagged_slot} pick {roster_entry.pick_no} "
            f"player {roster_entry.player_id} ${roster_entry.amount} — inside the keeper "
            "window and not in the manifest; confirm whether this is a late keeper swap"
        )
    for reject in state.rejects:
        print(f"  REJECT {reject}")
    for orphan in state.orphans:
        print(f"  ORPHAN {orphan}")
    for alert in state.alerts:
        print(f"  ALERT {alert}")
    return 0


async def _smoke() -> int:
    async with httpx.AsyncClient() as http:
        client = SleeperClient(client=http)
        league = await client.league(LEAGUE_ID)
        draft = await client.draft(REAL_DRAFT_ID)
        picks = await client.picks(REAL_DRAFT_ID) or []
        rosters = await client.rosters(LEAGUE_ID) or []
        users = await client.users(LEAGUE_ID) or []

    config = load_league_config(CONFIG / "league.yaml")
    warnings = assert_startable(validate(config, league, draft))
    print(f"league    : {league['name']} ({league['status']})")
    print(f"draft     : {draft['status']}, {len(picks)} picks")
    print("config    : startable")
    for warning in warnings:
        assert warning.severity == Severity.WARNING
        print(f"  WARN {warning}")

    # The real draft object carries no slot_name_* keys at all, so this join is the ONLY path
    # that resolves owners in production. It was implemented, tested, and called by nothing.
    identity = build_identity(draft, rosters=rosters, users=users, aliases=_aliases())
    print(
        f"identity  : {len(identity.slot_to_owner)}/{config.teams} slots resolved"
        f" {sorted(identity.slot_to_owner.items())}"
    )
    if not identity.is_complete(config.teams):
        print(f"  BLOCKER unmapped draft slots: {identity.unmapped_slots(config.teams)}")

    players = json.loads((FIXTURES / "players_slim.json").read_text())
    manifest = load_manifest(CONFIG / "keepers.yaml")
    try:
        keys = manifest_keys(
            resolve_manifest(manifest, players),
            identity,
            require=config.teams * config.keepers_per_team,
            teams=config.teams,
        )
        print(f"manifest  : {len(keys)} keeper keys resolved")
    except UnresolvedManifest as exc:
        print(f"  BLOCKER {exc}")
    return 0


def value() -> int:
    """DI-030: price the board both ways and print it. No report layer yet, by design."""
    config = load_league_config(CONFIG / "league.yaml")
    league = json.loads((FIXTURES / "league.json").read_text())
    players_map = json.loads((FIXTURES / "players_slim.json").read_text())
    projections_raw = json.loads((FIXTURES / "projections_slim.json").read_text())
    draft = json.loads((FIXTURES / "draft.json").read_text())
    picks = load_picks(FIXTURES / "picks.json")

    # The tripwire runs on the pricing path, not only on `smoke`. It previously fired nowhere a
    # person reading a priced board would see it, which made a blocking check that nothing
    # blocked on: every figure below is scaled by draft_rounds, the budget and the starting
    # slots, and a board printed against a league that has drifted is wrong in silence.
    # Validated against the REAL draft object, since that is the one the tool will meet on the
    # night; the mock below only supplies identity and picks.
    print("=" * 78)
    print("CONFIG TRIPWIRE  (ADR-0002 / ADR-0005)")
    print("=" * 78)
    warnings = assert_startable(
        validate(config, league, json.loads((FIXTURES / "real_draft.json").read_text()))
    )
    print(
        f"  auction pool  {config.teams} teams x {config.draft_rounds} draft rounds = "
        f"{config.auction_pool} players bought   (roster capacity {config.roster_size})"
    )
    print(f"  budget        ${config.budget}/team, ${config.teams * config.budget} in the room")
    print(f"  draft starts  {config.draft_start}")
    for warning in warnings:
        print(f"  WARN {warning}")

    print()
    projections, unreliable = build_projections(projections_raw, league["scoring_settings"])

    manifest = load_manifest(CONFIG / "keepers.yaml")
    identity = build_identity(draft, aliases=_aliases("mock_aliases"))
    resolved = resolve_manifest(manifest, players_map)
    keeper_ids = frozenset(pid for _owner, pid in resolved)

    # Keeper prices come from the picks feed. Sleeper publishes no auction-value field, so
    # these are the user's estimates until read off the draft room on the morning.
    keeper_spend = sum(int(p["metadata"]["amount"]) for p in picks if p["player_id"] in keeper_ids)
    positions_by_slot: dict[int, list[str]] = {}
    for (owner, _pid), entry in resolved.items():
        slot = identity.slot_for(owner)
        if slot is not None:
            positions_by_slot.setdefault(slot, []).append(entry.pos)

    demand = seat_keepers(positions_by_slot, starters=config.starters, teams=config.teams)
    roster_full = config.auction_pool
    roster_live = roster_full - len(keeper_ids)

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

    print("=" * 78)
    print("DI-026  PROJECTIONS")
    print("=" * 78)
    print(f"  scored {len(projections)} players under this league's scoring_settings")
    for position, median in sorted(unreliable.items()):
        print(
            f"  !! {position}: raw-stat scoring diverges from Sleeper's pts_ppr by a median "
            f"{median:.1f}% -> fell back to pts_ppr for this position"
        )
    diverged = [p for p in projections if p.diverged and p.position not in unreliable]
    print(f"  individual >5% divergences outside those positions: {len(diverged)}")

    print()
    print("=" * 78)
    print("DI-028  SLOT DEMAND  (supply AND demand adjusted - charter 4.2)")
    print("=" * 78)
    print(f"  {'pos':6} {'base':>6} {'kept':>6} {'remain':>7}")
    for position in sorted(demand.base):
        print(
            f"  {position:6} {demand.base[position]:>6} {demand.keeper_base.get(position, 0):>6} "
            f"{demand.remaining_base[position]:>7}"
        )
    print(f"  {'FLEX':6} {demand.flex:>6} {demand.keeper_flex:>6} {demand.remaining_flex:>7}")
    print(
        f"\n  remaining STARTING slots {demand.remaining_starting}   "
        f"remaining ROSTER spots {roster_live}   (different numbers; both asserted)"
    )

    print()
    print("=" * 78)
    print("DI-029  REPLACEMENT BASELINES  (points of the last player rostered)")
    print("=" * 78)
    print(
        f"  {'pos':6} {'fullStrt':>9} {'fullLast':>9} {'liveStrt':>9} {'liveLast':>9} {'rost':>6}"
    )
    for position in ["QB", "RB", "WR", "TE", "K"]:
        b = baselines
        print(
            f"  {position:6} {b.full_starter.points.get(position, 0):>9.1f} "
            f"{b.full_last_drafted.points.get(position, 0):>9.1f} "
            f"{b.live_starter.points.get(position, 0):>9.1f} "
            f"{b.live_last_drafted.points.get(position, 0):>9.1f} "
            f"{b.live_last_drafted.rostered.get(position, 0):>6}"
        )

    print()
    print("=" * 78)
    print("DI-030  VALUATION")
    print("=" * 78)
    print(f"  total budget          ${board.total_budget}")
    print(f"  keeper spend          ${board.keeper_spend}   (20 keepers, estimated prices)")
    print(f"  total live money      ${board.total_live_money}")
    print(f"  discretionary (full)  ${board.discretionary}      $/VORP {board.dollars_per_vorp}")
    print(
        f"  discretionary (live)  ${board.discretionary_live}"
        f"      $/VORP {board.dollars_per_vorp_live}"
    )
    print(
        f"  keeper book value     ${board.keeper_book_value:.0f}"
        f"   (what the 20 would cost at open auction)"
    )
    print(f"  KEEPER SURPLUS        ${board.keeper_surplus:+.0f}")
    print(
        f"  KEEPER INFLATION      {board.keeper_inflation}x"
        f"   (live money / book still on the board)"
    )
    print()
    print("  INVARIANTS (charter 4.3 - the app refuses to price if any fails)")
    print(
        f"    sum market_value  over {board.pool_full_size} = ${board.sum_market_value}"
        f"  (want ${board.total_budget})"
    )
    print(
        f"    sum baseline_value over {board.pool_live_size} = ${board.sum_baseline_value}"
        f"  (want ${board.total_live_money})"
    )
    print(
        f"    keeper + live == total: ${board.keeper_spend} + ${board.total_live_money}"
        f" == ${board.total_budget}"
    )

    # DI-027. The ladder handed to the ADP provider is our own board's price curve, sorted; the
    # provider supplies only the ordering. See quant/market.py for why that is honest and what
    # it does not claim.
    ladder = [p.market_value for p in board.players if p.in_pool_full]
    market = resolve_market_values(
        [
            CsvMarketValues(CONFIG / "auction_values.csv", players_map),
            AdpMarketValues(projections_raw, ladder),
            # Pool members only. A player outside pool_full carries market_value 0.0, which is
            # the absence of a valuation rather than an opinion that they are worthless, and
            # feeding those in reports coverage of 596 against a 160-spot pool.
            InternalMarketValues(
                {p.player_id: p.market_value for p in board.players if p.in_pool_full}
            ),
        ],
        projections,
        required=roster_full,
    )

    print()
    print("=" * 78)
    print("DI-027  MARKET VALUES  (what the ROOM pays, not what our model says)")
    print("=" * 78)
    print(f"  source     {market.source}" + ("   [ESTIMATE]" if market.is_estimate else ""))
    print(
        f"  coverage   {market.coverage} players carry a market value "
        f"(priced pool is {roster_full})   total ${market.total:.0f}"
    )
    for note in market.notes:
        print(f"  note       {note}")
    for row in market.unmatched[:10]:
        print(f"  UNMATCHED  {row}")
    if len(market.unmatched) > 10:
        print(f"  UNMATCHED  ... and {len(market.unmatched) - 10} more")
    if market.is_estimate:
        print(
            "  !! Sleeper publishes no auction value (Finding 3), so the league's own keeper\n"
            "     rule -- floor(0.75 * auction_value) -- is NOT computable from the API.\n"
            f"     Drop real values in {CONFIG / 'auction_values.csv'} to fix this;\n"
            f"     see {CONFIG / 'auction_values.csv.example'} for the format."
        )

    # DI-031. Retention prices come from the picks feed here, which is what the mock actually
    # loaded. On draft day they are read off the draft room and entered through the override
    # layer; the manifest's `price` field is the third path. All three are observed fact, which
    # is what makes them the `as_loaded` scenario rather than the rule-implied one.
    loaded_prices = {
        p["player_id"]: int(p["metadata"]["amount"])
        for p in picks
        if p["player_id"] in keeper_ids and (p.get("metadata") or {}).get("amount")
    }
    keepers = keeper_board(
        board,
        keeper_owners={pid: owner for owner, pid in resolved},
        slots={
            pid: slot for owner, pid in resolved if (slot := identity.slot_for(owner)) is not None
        },
        prices=loaded_prices,
        market=market,
        minimum_retention_price=manifest.league.minimum_retention_price,
    )

    print()
    print("=" * 78)
    print("DI-031  KEEPER SURPLUS BOARD")
    print("=" * 78)
    print(
        f"  {'owner':8} {'player':22} {'pos':4} {'book':>6} {'mkt':>6} "
        f"{'rule':>6} {'loaded':>7} {'surplus':>8}"
    )
    for line in keepers.lines:
        print(
            f"  {line.owner:8} {line.name[:22]:22} {line.position:4} "
            f"{line.book_value:>6.0f} {_or_dash(line.market_value):>6} "
            f"{_or_dash(line.rule_price):>6} {_or_dash(line.price_paid):>7} "
            f"{_or_dash(line.surplus):>8}"
        )

    print()
    print(f"  {'scenario':26} {'ΣK':>6} {'live $':>8} {'surplus':>9} {'inflation':>10}")
    for scenario in (keepers.as_loaded, keepers.under_rule):
        if scenario.complete:
            print(
                f"  {scenario.label:26} {scenario.keeper_spend:>6} "
                f"{scenario.total_live_money:>8} {scenario.keeper_surplus:>+9.0f} "
                f"{scenario.keeper_inflation:>9.4f}x"
            )
        else:
            print(
                f"  {scenario.label:26} {scenario.keeper_spend:>6} "
                f"{'--':>8} {'--':>9} {'--':>10}   "
                f"({scenario.missing} keeper(s) unpriced; derived figures refuse)"
            )
    print(
        "\n  Inflation above 1.00x means the remaining board should clear OVER book, which is\n"
        "  what the 25% retention discount is meant to produce. Below 1.00x means the keepers\n"
        "  were retained at or above their open-market worth and the board clears at a discount."
    )
    for alert in keepers.alerts():
        print(f"  ALERT {alert}")

    print()
    print("  TOP 25 AVAILABLE  (baseline_value is the number to bid against)")
    print(
        f"  {'#':>3} {'player':22} {'pos':4} {'pts':>7} {'VORPlv':>7}"
        f" {'LIVE $':>7} {'book $':>7} {'delta':>7}"
    )
    for i, p in enumerate(board.available()[:25], 1):
        print(
            f"  {i:>3} {p.name[:24]:24} {p.position:4} {p.points:>7.1f} {p.vorp_live:>7.1f} "
            f"{p.baseline_value:>7.2f} {p.market_value:>7.2f} {p.keeper_premium:>+7.2f}"
        )

    print()
    print("  QB MARKET  (charter A.4: the most distorted market in this draft)")
    qbs = [p for p in board.by_position("QB") if not p.is_keeper][:12]
    print(f"  {'#':>3} {'player':24} {'pts':>7} {'VORPlv':>7} {'LIVE $':>7} {'book $':>7}")
    for i, p in enumerate(qbs, 1):
        print(
            f"  {i:>3} {p.name[:24]:24} {p.points:>7.1f} {p.vorp_live:>7.1f} "
            f"{p.baseline_value:>7.2f} {p.market_value:>7.2f}"
        )
    return 0


def smoke() -> int:
    """Hit the live API, validate the real league, and poll the real draft once."""
    return asyncio.run(_smoke())


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    command = args[0] if args else "replay"
    if command == "replay":
        return replay()
    if command == "smoke":
        return smoke()
    if command == "value":
        return value()
    if command == "prep":
        from draft_intel.prep import main as prep_main

        return prep_main()
    print(
        f"unknown command {command!r}; expected 'replay', 'smoke', 'value' or 'prep'",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
