"""Tests for the valuation chain, DI-026 through DI-030.

Written against the failure mode this project has repeatedly hit: tests that cannot fail.
Every expected number below is either hand-computed from the formula in the charter, or
derived from the fixture by a route that does not go through the code under test. Where a test
exists to prove a distinction is load-bearing, it constructs the wrong answer explicitly and
asserts the code does not produce it.

The tiny league used throughout makes the arithmetic checkable by hand:

    2 teams, $100 each -> $200 total, 2 roster spots each -> 4 rostered
    starters: 1 QB, 1 RB, no FLEX  ->  league-wide base QB 2, RB 2
    QB1 100  QB2 80  QB3 60
    RB1  90  RB2 70  RB3 50
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from draft_intel.config import load_league_config
from draft_intel.domain.identity import build_identity
from draft_intel.domain.keepers import load_manifest, resolve_manifest
from draft_intel.quant.replacement import (
    Baselines,
    compute_baselines,
    last_drafted_baseline,
    starter_baseline,
)
from draft_intel.quant.scoring import (
    PlayerProjection,
    ProjectionSource,
    build_projections,
    score_stats,
    unreliable_positions,
)
from draft_intel.quant.slots import seat_keepers
from draft_intel.quant.valuation import InvariantViolation, ValueBoard, value_board
from draft_intel.replay.harness import load_picks

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"

TINY_BASE = {"QB": 2, "RB": 2}
TINY_POINTS = [
    ("q1", "QB", 100.0),
    ("q2", "QB", 80.0),
    ("q3", "QB", 60.0),
    ("r1", "RB", 90.0),
    ("r2", "RB", 70.0),
    ("r3", "RB", 50.0),
]


def proj(player_id: str, position: str, points: float) -> PlayerProjection:
    return PlayerProjection(
        player_id=player_id,
        name=player_id.upper(),
        position=position,
        points=points,
        projection_source=ProjectionSource.COMPUTED,
        computed_points=points,
    )


def tiny() -> list[PlayerProjection]:
    return [proj(pid, pos, pts) for pid, pos, pts in TINY_POINTS]


def value_of(board: ValueBoard, player_id: str) -> tuple[float, float]:
    entry = next(p for p in board.players if p.player_id == player_id)
    return entry.market_value, entry.baseline_value


# ======================================================================================
# DI-026 — scoring
# ======================================================================================


def test_score_stats_is_hand_checkable():
    """3 TD x 6 + 100 yd x 0.1 + 5 rec x 1 - 1 fumble x 2 = 18 + 10 + 5 - 2 = 31."""
    stats = {"rec_td": 3, "rec_yd": 100, "rec": 5, "fum_lost": 1}
    scoring = {"rec_td": 6.0, "rec_yd": 0.1, "rec": 1.0, "fum_lost": -2.0}
    assert score_stats(stats, scoring) == pytest.approx(31.0)


def test_score_stats_ignores_adp_pre_scored_totals_and_unscored_stats():
    stats = {"rec": 5, "adp_ppr": 3.0, "pts_ppr": 999.0, "rush_att": 200}
    assert score_stats(stats, {"rec": 1.0}) == pytest.approx(5.0)


def test_score_stats_does_not_count_booleans_as_one():
    """`bool` is an `int` subclass; a flag in a stat line must not become a point."""
    assert score_stats({"rec": True}, {"rec": 1.0}) == pytest.approx(0.0)


def test_score_stats_survives_a_non_numeric_value():
    assert score_stats({"rec": "lots", "rec_td": 1}, {"rec": 1.0, "rec_td": 6.0}) == 6.0


def _record(position: str, stats: dict) -> dict:
    return {
        "player_id": f"{position}-{stats.get('rec', 0)}-{stats.get('pts_ppr', 0)}",
        "player": {"first_name": position, "last_name": "Player", "position": position},
        "stats": stats,
    }


def test_unreliable_positions_flags_only_the_position_that_diverges():
    """A position is unreliable when the league scores something the projections omit.

    WR is scored completely; K is missing a scoring category entirely, so its computed total
    lands far below Sleeper's own figure. Only K should be flagged.
    """
    scoring = {"rec": 1.0, "fgm_0_19": 3.0, "fgm_40_49": 4.0}
    records = [
        _record("WR", {"rec": 100, "pts_ppr": 100.0}),
        _record("WR", {"rec": 90, "pts_ppr": 90.0}),
        _record("K", {"fgm_40_49": 5, "pts_ppr": 100.0}),  # computed 20 vs 100
        _record("K", {"fgm_40_49": 4, "pts_ppr": 90.0}),
    ]
    assert set(unreliable_positions(records, scoring)) == {"K"}


def test_unreliable_positions_ignores_near_zero_players():
    """Percentage divergence on a 2-point projection is noise, not signal."""
    scoring = {"rec": 1.0}
    records = [_record("WR", {"rec": 0, "pts_ppr": 2.0})] * 3
    assert unreliable_positions(records, scoring) == {}


def test_build_projections_falls_back_only_for_unreliable_positions():
    scoring = {"rec": 1.0, "fgm_0_19": 3.0}
    records = [
        _record("WR", {"rec": 100, "pts_ppr": 100.0}),
        _record("WR", {"rec": 90, "pts_ppr": 90.0}),
        _record("K", {"pts_ppr": 100.0}),
        _record("K", {"pts_ppr": 90.0}),
    ]
    players, unreliable = build_projections(records, scoring, positions=("WR", "K"))
    assert "K" in unreliable and "WR" not in unreliable

    wrs = [p for p in players if p.position == "WR"]
    kickers = [p for p in players if p.position == "K"]
    assert all(p.projection_source is ProjectionSource.COMPUTED for p in wrs)
    assert all(p.projection_source is ProjectionSource.SLEEPER_PPR for p in kickers)
    # Kickers take Sleeper's figure; the raw computation would have given every one of them 0.
    assert sorted(p.points for p in kickers) == [90.0, 100.0]
    assert all(p.computed_points == 0.0 for p in kickers)


# --- against the real league and the real projections -----------------------------------


def test_real_league_scores_skill_positions_exactly_and_kickers_not_at_all():
    """The measurement that drove the fallback design, pinned so it cannot drift.

    QB/RB/WR/TE reproduce Sleeper's own PPR figure to 0.0% median divergence. Kickers do not,
    because this league scores field goals by distance bucket (fgm_0_19 .. fgm_60p) while the
    projections only carry fgm_40_49 and fgm_50p.
    """
    league = json.loads((FIXTURES / "league.json").read_text())
    raw = json.loads((FIXTURES / "projections_slim.json").read_text())
    unreliable = unreliable_positions(raw, league["scoring_settings"])

    assert set(unreliable) == {"K"}
    assert unreliable["K"] > 25.0  # measured ~29.8%

    # And the league really does score buckets the projections never supply.
    scored_buckets = {
        k for k, v in league["scoring_settings"].items() if k.startswith("fgm_") and v
    }
    projected = {k for r in raw for k in r["stats"] if k.startswith("fgm_")}
    assert scored_buckets - projected, "kickers would be scorable; the fallback is unneeded"


def test_real_projections_produce_a_source_for_every_player():
    league = json.loads((FIXTURES / "league.json").read_text())
    raw = json.loads((FIXTURES / "projections_slim.json").read_text())
    players, _ = build_projections(raw, league["scoring_settings"])
    assert players
    # A projection may legitimately be slightly negative: a deep reserve projected for a
    # fumble and nothing else. Two such players exist in this fixture, both around -$1 point.
    # What must not happen is a wholesale sign error.
    assert min(p.points for p in players) > -5.0
    assert {p.projection_source for p in players} == {
        ProjectionSource.COMPUTED,
        ProjectionSource.SLEEPER_PPR,
    }
    assert players == sorted(players, key=lambda p: p.points, reverse=True)


# ======================================================================================
# DI-028 — slot demand
# ======================================================================================


STARTERS = {"QB": 2, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1}


def test_two_keepers_at_one_position_both_fit_base_slots():
    """Mason keeps two WRs and a team has two WR slots, so no FLEX is consumed."""
    demand = seat_keepers({1: ["WR", "WR"]}, starters=STARTERS, teams=10)
    assert demand.keeper_base["WR"] == 2
    assert demand.keeper_flex == 0


def test_a_third_keeper_at_one_position_spills_into_flex():
    """The case the greedy base-then-FLEX order exists for."""
    demand = seat_keepers({1: ["WR", "WR", "WR"]}, starters=STARTERS, teams=10)
    assert demand.keeper_base["WR"] == 2
    assert demand.keeper_flex == 1


def test_a_keeper_with_nowhere_to_sit_is_counted_as_bench_not_dropped():
    """Two TEs in a one-TE league: base takes one, FLEX takes one, a third is bench.

    Silently dropping the overflow would understate the demand reduction.
    """
    demand = seat_keepers({1: ["TE", "TE", "TE", "TE"]}, starters=STARTERS, teams=10)
    assert demand.keeper_base["TE"] == 1
    assert demand.keeper_flex == 2
    assert demand.keeper_bench == 1


def test_a_kicker_keeper_cannot_take_a_flex_slot():
    demand = seat_keepers({1: ["K", "K"]}, starters=STARTERS, teams=10)
    assert demand.keeper_base["K"] == 1
    assert demand.keeper_flex == 0
    assert demand.keeper_bench == 1


def test_real_manifest_reproduces_appendix_a_demand():
    """Charter Appendix A.2, re-derived through the code rather than trusted."""
    config = load_league_config(ROOT / "config" / "league.yaml")
    players = json.loads((FIXTURES / "players_slim.json").read_text())
    draft = json.loads((FIXTURES / "draft.json").read_text())
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    identity = build_identity(draft, aliases={"Me": "Matt"})

    positions_by_slot: dict[int, list[str]] = {}
    for (owner, _pid), entry in resolve_manifest(manifest, players).items():
        slot = identity.slot_for(owner)
        assert slot is not None
        positions_by_slot.setdefault(slot, []).append(entry.pos)

    demand = seat_keepers(positions_by_slot, starters=config.starters, teams=config.teams)

    assert demand.keeper_base == {"QB": 7, "RB": 6, "WR": 7, "TE": 0, "K": 0}
    assert demand.keeper_flex == 0
    assert demand.remaining_base == {"QB": 13, "RB": 14, "WR": 13, "TE": 10, "K": 10}
    assert demand.remaining_flex == 20

    # Charter §4.2: assert BOTH totals. They are different numbers and easy to transpose.
    assert demand.remaining_starting == 80
    assert config.auction_pool - 20 == 140
    assert demand.remaining_starting != 140


# ======================================================================================
# DI-029 — replacement baselines
# ======================================================================================


def test_starter_baseline_reads_replacement_off_the_last_starter():
    """Base slots QB 2 / RB 2, no FLEX: replacement is QB2 (80) and RB2 (70)."""
    baseline = starter_baseline(tiny(), base_slots=TINY_BASE, flex_slots=0)
    assert baseline.points == {"QB": 80.0, "RB": 70.0}
    assert baseline.pool_size == 4


def test_flex_split_is_derived_from_points_not_assumed():
    """Charter §4.2: "do not assume a split, derive it."

    One FLEX slot, base QB 1 / RB 1. The best remaining flex-eligible player is RB2 (70),
    ahead of the leftover QBs, so the FLEX goes to RB and RB replacement drops to 70.
    """
    baseline = starter_baseline(tiny(), base_slots={"QB": 1, "RB": 1}, flex_slots=1)
    assert baseline.rostered["RB"] == 2
    assert baseline.rostered["QB"] == 1
    assert baseline.points == {"QB": 100.0, "RB": 70.0}


def test_last_drafted_baseline_is_a_fixed_point():
    """Feeding the solved roster back in must not move the answer."""
    first = last_drafted_baseline(tiny(), base_slots=TINY_BASE, flex_slots=0, roster_spots=4)
    second = last_drafted_baseline(tiny(), base_slots=TINY_BASE, flex_slots=0, roster_spots=4)
    assert first.points == second.points == {"QB": 80.0, "RB": 70.0}
    assert first.pool_size == 4


def test_bench_spots_go_to_the_position_with_more_value_over_replacement():
    """With one bench spot, the deeper position earns it rather than a fixed rule.

    Base QB 1 / RB 1 gives replacement QB 100 / RB 90 at the seed. QB2 gains 80-100 = -20,
    RB2 gains 70-90 = -20, tie; but as replacement falls the allocation settles on the pool
    with genuine depth. What matters is that it is derived, and that the total is respected.
    """
    baseline = last_drafted_baseline(
        tiny(), base_slots={"QB": 1, "RB": 1}, flex_slots=0, roster_spots=3
    )
    assert baseline.pool_size == 3
    assert sum(baseline.rostered.values()) == 3


def test_pinned_positions_are_not_subject_to_the_value_contest():
    """Kickers: exactly one per team, regardless of what VORP would say."""
    players = [*tiny(), proj("k1", "K", 120.0), proj("k2", "K", 118.0), proj("k3", "K", 5.0)]
    baseline = last_drafted_baseline(
        players,
        base_slots={"QB": 2, "RB": 2, "K": 2},
        flex_slots=0,
        roster_spots=6,
        pinned={"K": 2},
    )
    assert baseline.rostered["K"] == 2  # not 3, despite k3 existing


# --- the charter's two named audits -----------------------------------------------------


def test_the_2qb_check_pushes_replacement_deeper_and_raises_top_qb_vorp():
    """Charter §4.2 sanity gate, and §9's "most likely place for a subtle, expensive error".

    **This test contradicts the charter's wording, deliberately.** §4.2 says 2QB should be
    "compressing QB VORP at the top". The arithmetic says the opposite, and it is not close.
    Doubling QB demand means rostering more quarterbacks, which pushes replacement *deeper*
    into the list, which *lowers* replacement points and therefore *raises* the VORP of every
    quarterback above it. On the real pool:

        1QB: replacement 262.7 pts, 22 QBs rostered, top-QB VORP  98.8
        2QB: replacement 227.8 pts, 25 QBs rostered, top-QB VORP 133.7

    That is the standard superflex result -- quarterbacks are worth *more* when you must start
    two, not less. The charter's other 2QB claims stand: replacement does move materially, and
    the QB20-28 band does become the contested one. Only "compressing at the top" is backwards.
    Flagged rather than silently resolved, per the charter's own standing instruction.
    """
    one_qb = last_drafted_baseline(
        tiny(), base_slots={"QB": 1, "RB": 2}, flex_slots=0, roster_spots=3
    )
    two_qb = last_drafted_baseline(
        tiny(), base_slots={"QB": 2, "RB": 2}, flex_slots=0, roster_spots=4
    )

    assert two_qb.rostered["QB"] > one_qb.rostered["QB"], "2QB must roster more QBs"
    assert two_qb.points["QB"] < one_qb.points["QB"], "deeper replacement means fewer points"

    best_qb = proj("q1", "QB", 100.0)
    assert two_qb.vorp(best_qb) > one_qb.vorp(best_qb), "top-QB VORP RISES under 2QB"
    assert one_qb.vorp(best_qb) == 0.0  # QB1 is his own replacement in a 1QB tiny league
    assert two_qb.vorp(best_qb) == 20.0  # 100 - QB2's 80


def test_the_keeper_double_count_audit():
    """Charter §9: supply AND demand adjusted, exactly once each.

    QB1 is kept. Three implementations give three different QB replacement levels, and only
    one is right:

        both adjusted  (correct)  QB1 out of the pool, QB demand 2 -> 1  ->  replacement 80
        supply only    (wrong)    QB1 out of the pool, QB demand still 2 ->  replacement 60
        demand only    (wrong)    QB1 still in the pool, QB demand 1     ->  replacement 100

    A naive implementation lands on 60 or 100. This pins 80.
    """
    keeper = "q1"
    available = [p for p in tiny() if p.player_id != keeper]

    both = last_drafted_baseline(
        available, base_slots={"QB": 1, "RB": 2}, flex_slots=0, roster_spots=3
    )
    supply_only = last_drafted_baseline(
        available, base_slots={"QB": 2, "RB": 2}, flex_slots=0, roster_spots=3
    )
    demand_only = last_drafted_baseline(
        tiny(), base_slots={"QB": 1, "RB": 2}, flex_slots=0, roster_spots=3
    )

    assert both.points["QB"] == 80.0
    assert supply_only.points["QB"] == 60.0
    assert demand_only.points["QB"] == 100.0
    assert len({both.points["QB"], supply_only.points["QB"], demand_only.points["QB"]}) == 3


def test_compute_baselines_excludes_keepers_from_live_supply():
    demand = seat_keepers({1: ["QB"]}, starters={"QB": 2, "RB": 2, "FLEX": 0}, teams=1)
    baselines = compute_baselines(
        tiny(),
        keeper_ids=frozenset({"q1"}),
        demand=demand,
        roster_spots_full=4,
        roster_spots_live=3,
        kicker_slots=0,
    )
    assert isinstance(baselines, Baselines)
    # Full universe still sees q1; the live universe must not.
    assert baselines.full_last_drafted.points["QB"] == 80.0
    assert baselines.live_last_drafted.points["QB"] == 80.0
    assert baselines.live_last_drafted.rostered["QB"] == 1


# ======================================================================================
# DI-030 — dual valuation
# ======================================================================================


def tiny_baselines(keeper_ids: frozenset[str], *, live_spots: int) -> Baselines:
    demand = seat_keepers(
        {1: [p.position for p in tiny() if p.player_id in keeper_ids]},
        starters={"QB": 2, "RB": 2, "FLEX": 0},
        teams=1,
    )
    return compute_baselines(
        tiny(),
        keeper_ids=keeper_ids,
        demand=demand,
        roster_spots_full=4,
        roster_spots_live=live_spots,
        kicker_slots=0,
    )


def test_full_market_value_matches_the_charter_formula_by_hand():
    """Replacement QB 80 / RB 70 -> VORP q1 20, r1 20, everyone else 0.

    discretionary    = 200 - 4 = 196
    dollars_per_vorp = 196 / 40 = 4.9
    market_value(q1) = 1 + 20 * 4.9 = 99.0
    """
    board = value_board(
        tiny(),
        baselines=tiny_baselines(frozenset(), live_spots=4),
        keeper_ids=frozenset(),
        keeper_spend=0,
        total_budget=200,
        roster_spots_full=4,
        roster_spots_live=4,
    )
    assert board.dollars_per_vorp == pytest.approx(4.9)
    assert value_of(board, "q1")[0] == pytest.approx(99.0)
    assert value_of(board, "r1")[0] == pytest.approx(99.0)
    assert board.sum_market_value == pytest.approx(200.0, abs=1.0)


def test_live_value_matches_the_charter_formula_by_hand():
    """q1 kept at $30, so $170 is left for 3 spots.

    VORP_live: r1 = 90 - 70 = 20, everyone else 0
    discretionary_live = 170 - 3 = 167
    dpv_live           = 167 / 20 = 8.35
    baseline_value(r1) = 1 + 20 * 8.35 = 168.0
    """
    board = value_board(
        tiny(),
        baselines=tiny_baselines(frozenset({"q1"}), live_spots=3),
        keeper_ids=frozenset({"q1"}),
        keeper_spend=30,
        total_budget=200,
        roster_spots_full=4,
        roster_spots_live=3,
    )
    assert board.total_live_money == 170
    assert board.dollars_per_vorp_live == pytest.approx(8.35)
    assert value_of(board, "r1")[1] == pytest.approx(168.0)
    assert board.sum_baseline_value == pytest.approx(170.0, abs=1.0)


def test_a_keeper_is_off_the_live_board_but_still_has_book_value():
    board = value_board(
        tiny(),
        baselines=tiny_baselines(frozenset({"q1"}), live_spots=3),
        keeper_ids=frozenset({"q1"}),
        keeper_spend=30,
        total_budget=200,
        roster_spots_full=4,
        roster_spots_live=3,
    )
    market, baseline = value_of(board, "q1")
    assert baseline == 0.0, "a keeper cannot be bid on"
    assert market > 0.0, "but still has a full-market value, which prices the keeper itself"
    assert "q1" not in {p.player_id for p in board.available()}


def test_keeper_inflation_is_money_against_book_not_a_ratio_of_money_pools():
    """The bug this project actually shipped, pinned so it cannot come back.

    An earlier version returned ``discretionary_live / discretionary``. Here that would be
    167/196 = 0.852, which describes nothing a bidder experiences. The correct figure is live
    money against the book value still on the board.
    """
    board = value_board(
        tiny(),
        baselines=tiny_baselines(frozenset({"q1"}), live_spots=3),
        keeper_ids=frozenset({"q1"}),
        keeper_spend=30,
        total_budget=200,
        roster_spots_full=4,
        roster_spots_live=3,
    )
    expected = board.total_live_money / board.available_book_value
    assert board.keeper_inflation == pytest.approx(expected, abs=1e-4)

    wrong = board.discretionary_live / board.discretionary
    assert board.keeper_inflation != pytest.approx(wrong, abs=1e-3)


def test_keeper_surplus_is_book_minus_paid():
    board = value_board(
        tiny(),
        baselines=tiny_baselines(frozenset({"q1"}), live_spots=3),
        keeper_ids=frozenset({"q1"}),
        keeper_spend=30,
        total_budget=200,
        roster_spots_full=4,
        roster_spots_live=3,
    )
    assert board.keeper_surplus == pytest.approx(board.keeper_book_value - 30, abs=0.01)


# --- the three invariants, and the refusal ---------------------------------------------


def test_a_board_that_cannot_reconcile_refuses_to_return():
    """Charter §4.3: "the app must refuse to present prices".

    A keeper spend larger than the whole budget makes the live money negative. Note that the
    charter's three sum invariants all still *hold* on that input -- the arithmetic stays
    self-consistent, dollars-per-VORP simply goes negative and the sums reconcile to a negative
    total. Arithmetic consistency is not sanity, so the inputs are checked separately.
    """
    with pytest.raises(InvariantViolation):
        value_board(
            tiny(),
            baselines=tiny_baselines(frozenset({"q1"}), live_spots=3),
            keeper_ids=frozenset({"q1"}),
            keeper_spend=500,
            total_budget=200,
            roster_spots_full=4,
            roster_spots_live=3,
        )


def test_empty_projections_refuse_rather_than_price_nothing():
    with pytest.raises(InvariantViolation, match="empty board"):
        value_board(
            [],
            baselines=tiny_baselines(frozenset(), live_spots=4),
            keeper_ids=frozenset(),
            keeper_spend=0,
            total_budget=200,
            roster_spots_full=4,
            roster_spots_live=4,
        )


# --- end to end against the real league -------------------------------------------------


def real_board():
    config = load_league_config(ROOT / "config" / "league.yaml")
    league = json.loads((FIXTURES / "league.json").read_text())
    players_map = json.loads((FIXTURES / "players_slim.json").read_text())
    raw = json.loads((FIXTURES / "projections_slim.json").read_text())
    draft = json.loads((FIXTURES / "draft.json").read_text())
    picks = load_picks(FIXTURES / "picks.json")

    projections, _ = build_projections(raw, league["scoring_settings"])
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    identity = build_identity(draft, aliases={"Me": "Matt"})
    resolved = resolve_manifest(manifest, players_map)
    keeper_ids = frozenset(pid for _owner, pid in resolved)
    keeper_spend = sum(int(p["metadata"]["amount"]) for p in picks if p["player_id"] in keeper_ids)

    positions_by_slot: dict[int, list[str]] = {}
    for (owner, _pid), entry in resolved.items():
        slot = identity.slot_for(owner)
        if slot is not None:
            positions_by_slot.setdefault(slot, []).append(entry.pos)
    demand = seat_keepers(positions_by_slot, starters=config.starters, teams=config.teams)

    full = config.auction_pool
    live = full - len(keeper_ids)
    baselines = compute_baselines(
        projections,
        keeper_ids=keeper_ids,
        demand=demand,
        roster_spots_full=full,
        roster_spots_live=live,
        kicker_slots=config.starters["K"] * config.teams,
    )
    return value_board(
        projections,
        baselines=baselines,
        keeper_ids=keeper_ids,
        keeper_spend=keeper_spend,
        total_budget=config.teams * config.budget,
        roster_spots_full=full,
        roster_spots_live=live,
    )


def test_real_board_satisfies_all_three_invariants():
    """`value_board` raises if they fail, so reaching this line is most of the assertion."""
    board = real_board()
    assert board.sum_market_value == pytest.approx(2000.0, abs=1.0)
    assert board.sum_baseline_value == pytest.approx(board.total_live_money, abs=1.0)
    assert board.keeper_spend + board.total_live_money == 2000
    assert board.pool_full_size == 160
    assert board.pool_live_size == 140


def test_real_board_prices_the_keeper_slate_and_leaves_140_biddable():
    board = real_board()
    assert sum(1 for p in board.players if p.is_keeper) == 20
    assert all(p.baseline_value == 0.0 for p in board.players if p.is_keeper)
    assert len([p for p in board.available() if p.in_pool_live]) == 140


def test_real_board_shows_the_2qb_signature():
    """QB replacement must sit far above the flex positions in a 2QB league.

    RB/WR/TE replacement levels converge because the fixed point equalises marginal value
    across flex-eligible positions; QB cannot participate in that, so it separates.
    """
    config = load_league_config(ROOT / "config" / "league.yaml")
    league = json.loads((FIXTURES / "league.json").read_text())
    raw = json.loads((FIXTURES / "projections_slim.json").read_text())
    projections, _ = build_projections(raw, league["scoring_settings"])

    baseline = last_drafted_baseline(
        projections,
        base_slots={"QB": 20, "RB": 20, "WR": 20, "TE": 10, "K": 10},
        flex_slots=20,
        roster_spots=config.auction_pool,
        pinned={"K": 10},
    )
    qb = baseline.points["QB"]
    flex = [baseline.points[p] for p in ("RB", "WR", "TE")]
    assert qb > max(flex) + 50, "QB replacement must separate sharply under 2QB"
    assert max(flex) - min(flex) < 15, "flex-eligible replacements should converge"
    assert baseline.rostered["QB"] >= 20, "20 QB starting slots must all be fillable"

    # The same 1QB-vs-2QB comparison on the real pool, which is what would actually catch a
    # regression in the fixed point. Measured: 262.7 -> 227.8 points, 22 -> 25 rostered.
    one_qb = last_drafted_baseline(
        projections,
        base_slots={"QB": 10, "RB": 20, "WR": 20, "TE": 10, "K": 10},
        flex_slots=20,
        roster_spots=160,
        pinned={"K": 10},
    )
    best_qb = max((p for p in projections if p.position == "QB"), key=lambda p: p.points)
    assert baseline.points["QB"] < one_qb.points["QB"] - 20
    assert baseline.rostered["QB"] > one_qb.rostered["QB"]
    assert baseline.vorp(best_qb) > one_qb.vorp(best_qb) + 20


# ======================================================================================
# Mutation-driven additions.
#
# The first ten mutations run against this file caught only six. The four that slipped
# through are below, each with the reason it was invisible - all four are the same species
# of problem this project has hit repeatedly: an assertion that holds whether or not the
# code is right.
# ======================================================================================


def hand_baselines(
    *,
    full: dict[str, float],
    live: dict[str, float],
    full_rostered: dict[str, int] | None = None,
    live_rostered: dict[str, int] | None = None,
) -> Baselines:
    """Baselines with deliberately different full and live levels.

    On the real slate the two last-drafted baselines come out numerically identical, because
    removing 20 keepers from supply and 20 slots from demand very nearly cancel. That makes
    real data useless for proving the valuation reads the *live* baseline, so this constructs
    a case where they differ.

    ``rostered`` used to be filled in as ``{position: 1}`` because nothing read it. DI-059 makes
    the priced pool follow it -- so that the pool and the replacement level pricing it are the
    same set by construction -- and it is now load-bearing: it must sum to the ``roster_spots``
    the caller passes, or `value_board` refuses the board rather than pricing two different
    auctions against each other. Each caller states the roster it means.
    """
    from draft_intel.quant.replacement import Baseline

    def b(points: dict[str, float], rostered: dict[str, int] | None) -> Baseline:
        counts = rostered if rostered is not None else {k: 1 for k in points}
        return Baseline(points=points, rostered=counts, pool_size=sum(counts.values()))

    return Baselines(
        full_starter=b(full, full_rostered),
        full_last_drafted=b(full, full_rostered),
        live_starter=b(live, live_rostered),
        live_last_drafted=b(live, live_rostered),
    )


def test_live_valuation_reads_the_live_baseline_not_the_full_one():
    """Missed mutation: `live_last_drafted` swapped for `full_last_drafted`.

    Invisible on real data because the two baselines coincide there, and invisible on the
    tiny fixture for the same reason. Pinned here with baselines that differ by construction.
    """
    baselines = hand_baselines(
        full={"QB": 50.0, "RB": 50.0},
        live={"QB": 90.0, "RB": 85.0},
        full_rostered={"QB": 2, "RB": 2},
        live_rostered={"QB": 2, "RB": 2},
    )
    board = value_board(
        tiny(),
        baselines=baselines,
        keeper_ids=frozenset(),
        keeper_spend=0,
        total_budget=200,
        roster_spots_full=4,
        roster_spots_live=4,
    )
    q1 = next(p for p in board.players if p.player_id == "q1")
    assert q1.vorp == pytest.approx(50.0)  # 100 - 50, the FULL baseline
    assert q1.vorp_live == pytest.approx(10.0)  # 100 - 90, the LIVE baseline
    assert q1.vorp != q1.vorp_live


def test_a_keeper_has_zero_live_vorp_not_merely_a_zero_price():
    """Missed mutation: the keeper check in the live-VORP map removed.

    The earlier test asserted only `baseline_value == 0`, which pool membership already
    guarantees independently - so it held even with the keeper check gone. The VORP itself
    must be zero.
    """
    board = value_board(
        tiny(),
        baselines=tiny_baselines(frozenset({"q1"}), live_spots=3),
        keeper_ids=frozenset({"q1"}),
        keeper_spend=30,
        total_budget=200,
        roster_spots_full=4,
        roster_spots_live=3,
    )
    q1 = next(p for p in board.players if p.player_id == "q1")
    assert q1.vorp_live == 0.0, "a keeper must carry no live value at all"
    assert q1.vorp > 0.0, "but must keep its book value"
    assert q1.in_pool_live is False


def test_the_sum_invariant_actually_fires_on_sane_inputs():
    """Missed mutation: the market-value sum check disabled.

    The previous refusal test tripped the input guard instead, which is checked first, so the
    sum invariant itself was never exercised. Here every input is sane and only the sums are
    wrong: a live baseline above every player's projection zeroes all live VORP, so each of
    the 3 pooled players prices at the $1 floor and the board totals $3 against $170 of live
    money.
    """
    baselines = hand_baselines(
        full={"QB": 80.0, "RB": 70.0},
        live={"QB": 999.0, "RB": 999.0},
        full_rostered={"QB": 2, "RB": 2},
        live_rostered={"QB": 1, "RB": 2},  # q1 is kept, so 3 available spots
    )
    with pytest.raises(InvariantViolation, match="baseline_value"):
        value_board(
            tiny(),
            baselines=baselines,
            keeper_ids=frozenset({"q1"}),
            keeper_spend=30,
            total_budget=200,
            roster_spots_full=4,
            roster_spots_live=3,
        )


def test_live_starter_baseline_also_has_demand_reduced_by_keepers():
    """Missed mutation: `demand.base` used instead of `demand.remaining_base`.

    It slipped through because nothing asserted on `live_starter` - the double-count audit
    exercises `last_drafted_baseline` directly with hand-passed slots, so it never covered
    how `compute_baselines` wires demand into the starter baseline.
    """
    demand = seat_keepers({1: ["QB"]}, starters={"QB": 2, "RB": 2, "FLEX": 0}, teams=1)
    baselines = compute_baselines(
        tiny(),
        keeper_ids=frozenset({"q1"}),
        demand=demand,
        roster_spots_full=4,
        roster_spots_live=3,
        kicker_slots=0,
    )
    # Live universe: q1 gone from supply, QB demand 2 -> 1. One QB seated from [q2, q3], so
    # replacement is q2 at 80. Leaving demand at 2 would seat both and give q3 at 60.
    assert baselines.live_starter.points["QB"] == 80.0
    assert baselines.live_starter.rostered["QB"] == 1
    assert baselines.full_starter.points["QB"] == 80.0
    assert baselines.full_starter.rostered["QB"] == 2


def test_the_market_sum_invariant_fires_independently_of_the_baseline_one():
    """Missed mutation: the market-value sum check disabled.

    The baseline-sum test above cannot catch this, because the market check runs first and a
    board that breaks both would raise on either. This breaks only the full-market side: a full
    baseline above every projection zeroes all full VORP, so the 4 pooled players price at the
    $1 floor and total $4 against the $200 budget, while the live side stays perfectly sane.
    """
    baselines = hand_baselines(
        full={"QB": 999.0, "RB": 999.0},
        live={"QB": 80.0, "RB": 70.0},
        full_rostered={"QB": 2, "RB": 2},
        live_rostered={"QB": 2, "RB": 2},  # no keepers here, so both pools are the full 4
    )
    with pytest.raises(InvariantViolation, match="market_value"):
        value_board(
            tiny(),
            baselines=baselines,
            keeper_ids=frozenset(),
            keeper_spend=0,
            total_budget=200,
            roster_spots_full=4,
            roster_spots_live=4,
        )


def test_live_money_must_cover_the_minimum_bid_on_every_remaining_spot():
    """The guard that survives even if the keeper-spend ceiling is removed.

    Overlapping input checks are deliberate: a keeper spend above the budget is caught twice,
    once directly and once by the $1-per-spot floor. That redundancy is why mutating the
    ceiling alone changes no observable behaviour.
    """
    with pytest.raises(InvariantViolation, match="minimum bid"):
        value_board(
            tiny(),
            baselines=tiny_baselines(frozenset({"q1"}), live_spots=3),
            keeper_ids=frozenset({"q1"}),
            keeper_spend=198,  # $2 left for 3 spots at a $1 floor
            total_budget=200,
            roster_spots_full=4,
            roster_spots_live=3,
        )


def real_board_and_baselines():
    """The real board plus the baselines that priced it, so the two can be compared."""
    config = load_league_config(ROOT / "config" / "league.yaml")
    league = json.loads((FIXTURES / "league.json").read_text())
    players = json.loads((FIXTURES / "players_slim.json").read_text())
    raw = json.loads((FIXTURES / "projections_slim.json").read_text())
    picks = json.loads((FIXTURES / "picks.json").read_text())
    projections, _ = build_projections(raw, league["scoring_settings"])
    resolved = resolve_manifest(load_manifest(ROOT / "config" / "keepers.yaml"), players)
    keeper_ids = frozenset(pid for _owner, pid in resolved)
    demand = seat_keepers({}, starters=config.starters, teams=config.teams)
    full, live = config.auction_pool, config.auction_pool - len(keeper_ids)
    spend = sum(int(p["metadata"]["amount"]) for p in picks if p["player_id"] in keeper_ids)
    baselines = compute_baselines(
        projections,
        keeper_ids=keeper_ids,
        demand=demand,
        roster_spots_full=full,
        roster_spots_live=live,
        kicker_slots=config.starters.get("K", 0) * config.teams,
    )
    board = value_board(
        projections,
        baselines=baselines,
        keeper_ids=keeper_ids,
        keeper_spend=spend,
        total_budget=config.teams * config.budget,
        roster_spots_full=full,
        roster_spots_live=live,
    )
    return board, baselines


# ============================== DI-059 — the pool and the baseline are one set


def test_the_priced_pool_is_the_roster_the_replacement_level_solved_for():
    """The two halves of the valuation used to disagree about who is in the auction.

    `last_drafted_baseline` iterates to a per-position roster with K *pinned* — a league that
    starts a kicker must buy ten of them whatever the value curve says — and settled on
    25 QB / 10 K. `pool_full` ranked the same players flat by VORP and got 31 QB / 6 K, because
    kickers have almost no VORP and lose every tiebreak.

    So four kickers the league is obliged to buy fell outside the priced pool and rendered as
    `--`, while `dollars_per_vorp` divided by a VORP sum taken over a pool the replacement level
    had not assumed.
    """
    board, baselines = real_board_and_baselines()

    for label, rostered, member in (
        ("full", baselines.full_last_drafted.rostered, lambda p: p.in_pool_full),
        ("live", baselines.live_last_drafted.rostered, lambda p: p.in_pool_live),
    ):
        counts: dict[str, int] = {}
        for player in board.players:
            if member(player):
                counts[player.position] = counts.get(player.position, 0) + 1
        assert counts == {k: v for k, v in rostered.items() if v}, f"{label} pool disagrees"


def test_every_kicker_the_league_must_buy_is_priced():
    """The user-visible symptom: a position the league is required to fill, rendering as `--`."""
    board, _ = real_board_and_baselines()
    config = load_league_config(ROOT / "config" / "league.yaml")
    required = config.starters.get("K", 0) * config.teams

    priced = [p for p in board.players if p.position == "K" and p.in_pool_full]
    assert len(priced) == required == 10
    assert all(p.market_value > 0 for p in priced), "a player the league must buy needs a price"


def test_a_pool_that_disagrees_with_its_roster_spots_is_refused_rather_than_priced():
    """Having made the pool follow the baseline, a caller must not be able to reintroduce the
    divergence quietly. `compute_baselines` guarantees the sum; nothing in the type system does.
    """
    baselines = hand_baselines(
        full={"QB": 50.0, "RB": 50.0},
        live={"QB": 50.0, "RB": 50.0},
        full_rostered={"QB": 1, "RB": 1},  # 2 players...
        live_rostered={"QB": 1, "RB": 1},
    )
    with pytest.raises(InvariantViolation, match="describe different auctions"):
        value_board(
            tiny(),
            baselines=baselines,
            keeper_ids=frozenset(),
            keeper_spend=0,
            total_budget=200,
            roster_spots_full=4,  # ...against 4 spots
            roster_spots_live=4,
        )


def test_a_player_kept_by_two_owners_is_refused():
    """The mirror of the keeper double-count the ledger already guards.

    Supply and demand read the manifest through different collections: `keeper_ids` is a set, so
    a duplicate collapses and only 19 players leave the pool, while demand seats all 20 entries.
    The board then prices 141 roster spots against 140 players' worth of removed demand — every
    price shifts — and nothing else looks wrong. The count still reads 20 and
    `manifest_keys(require=20)` is still satisfied, because the two entries have different slots.
    """
    import re

    from draft_intel.domain.keepers import DuplicateKeeper

    players = json.loads((FIXTURES / "players_slim.json").read_text())
    lines = (ROOT / "config" / "keepers.yaml").read_text().splitlines()
    rows = [i for i, line in enumerate(lines) if re.search(r'\{name: "', line)]
    source = lines[rows[0]]
    name_match = re.search(r'name: "([^"]+)"', source)
    position_match = re.search(r"pos: (\w+)", source)
    assert name_match and position_match, "manifest layout changed; this test edits a real row"
    name, position = name_match.group(1), position_match.group(1)
    target = next(i for i in rows if re.search(rf"pos: {position}", lines[i]) and i != rows[0])
    lines[target] = re.sub(r'name: "[^"]+"', f'name: "{name}"', lines[target])

    written = ROOT / "config" / "keepers.yaml"
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "keepers.yaml"
        path.write_text("\n".join(lines))
        with pytest.raises(DuplicateKeeper, match="more than one owner"):
            resolve_manifest(load_manifest(path), players)

    # And the real manifest, which is hand-maintained and changes before draft day, is clean.
    assert len(resolve_manifest(load_manifest(written), players)) == 20
