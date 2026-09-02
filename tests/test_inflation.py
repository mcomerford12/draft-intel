"""DI-032 — live market inflation, overall and per position.

Two kinds of test here. The unit tests use a board small enough to check by hand. The identity
test at the bottom uses the real fixtures, because *exactly 1.0000 at pick 0* is a property of
how ``baseline_value`` is constructed and is only worth asserting against a real board.

No player name is hardcoded; synthetic players are named by position and index.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from draft_intel.config import load_league_config
from draft_intel.domain.keepers import load_manifest, resolve_manifest
from draft_intel.domain.ledger import fold
from draft_intel.models import DerivedState, PickObserved, PickSnapshot
from draft_intel.quant.inflation import (
    MIN_POSITION_SAMPLE,
    competitive_picks,
    forward_positional_inflation,
    inflation_curve,
    market_inflation,
    realized_positional_inflation,
)
from draft_intel.quant.replacement import compute_baselines
from draft_intel.quant.scoring import build_projections
from draft_intel.quant.slots import seat_keepers
from draft_intel.quant.valuation import PlayerValue, value_board

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
CONFIG = ROOT / "config"
SLOTS = range(1, 11)


def value(
    player_id: str, *, baseline: float, position: str = "RB", is_keeper: bool = False
) -> PlayerValue:
    return PlayerValue(
        player_id=player_id,
        name=f"{position}{player_id}",
        position=position,
        team=None,
        points=100.0,
        vorp=0.0,
        market_value=baseline,
        vorp_live=baseline,
        baseline_value=baseline,
        is_keeper=is_keeper,
        in_pool_full=True,
        in_pool_live=not is_keeper,
    )


def state_from(*picks: tuple[int, str, int, int, bool]) -> DerivedState:
    """Fold picks given as ``(pick_no, player_id, slot, amount, is_keeper)``."""
    events = [
        PickObserved(
            seq=i,
            pick=PickSnapshot(
                pick_no=pick_no, player_id=player_id, slot=slot, amount=amount, is_keeper=keeper
            ),
        )
        for i, (pick_no, player_id, slot, amount, keeper) in enumerate(picks, start=1)
    ]
    return fold(events, slots=SLOTS)


# --------------------------------------------------------------- the overall figure


def test_inflation_is_exactly_one_before_a_competitive_bid_is_made():
    """Not "near" 1.0 -- exactly it, as an identity.

    baseline_value is constructed so that Σ over the live pool equals total_live_money, and
    each carries a $1 minimum. So Σ(baseline - 1) over the pool is exactly
    total_live_money - slots, which is the discretionary figure the ratio divides by itself.
    """
    pool = [value(str(i), baseline=float(i + 1)) for i in range(10)]
    slots = len(pool)
    money = int(sum(p.baseline_value for p in pool))

    result = market_inflation(pool, remaining_money=money, remaining_slots=slots)

    assert result.remaining_value == money - slots
    assert result.discretionary_remaining == money - slots
    assert result.inflation == 1.0


def test_overpaying_early_deflates_what_is_left():
    """Money leaves the room faster than value does, so the rest gets cheaper. The direction
    has to be right or the tool advises saving money in exactly the market where it should
    be spending."""
    pool = [value(str(i), baseline=11.0) for i in range(10)]
    at_par = market_inflation(pool, remaining_money=110, remaining_slots=10)
    overpaid = market_inflation(pool, remaining_money=90, remaining_slots=10)

    assert at_par.inflation == 1.0
    assert overpaid.inflation < 1.0


def test_underpaying_early_inflates_what_is_left():
    pool = [value(str(i), baseline=11.0) for i in range(10)]
    assert market_inflation(pool, remaining_money=130, remaining_slots=10).inflation > 1.0


def test_the_pool_is_capped_at_the_slots_that_remain():
    """Players nobody has room for do not soak up money that must be spent on the rest."""
    pool = [value(str(i), baseline=11.0) for i in range(10)]
    result = market_inflation(pool, remaining_money=33, remaining_slots=3)
    assert result.pool_size == 3
    assert result.remaining_value == 30.0


def test_the_pool_takes_the_most_valuable_players_not_the_first_ones():
    pool = [value("cheap", baseline=2.0), value("dear", baseline=50.0)]
    result = market_inflation(pool, remaining_money=51, remaining_slots=1)
    assert result.remaining_value == 49.0


def test_an_exhausted_board_reports_no_inflation_rather_than_dividing_by_zero():
    """End of the draft: nothing left above the minimum bid. adjusted() must still work."""
    result = market_inflation([value("a", baseline=1.0)], remaining_money=1, remaining_slots=1)
    assert result.inflation == 1.0
    assert result.adjusted(value("a", baseline=1.0)) == 1.0


def test_an_empty_board_does_not_raise():
    assert market_inflation([], remaining_money=0, remaining_slots=0).inflation == 1.0


def test_adjusted_value_scales_only_the_part_above_the_minimum_bid():
    """1 + (baseline - 1) x inflation. The $1 floor is not inflated; every roster spot costs
    at least a dollar whatever the room is doing."""
    pool = [value(str(i), baseline=11.0) for i in range(10)]
    result = market_inflation(pool, remaining_money=210, remaining_slots=10)

    assert result.inflation == 2.0
    assert result.adjusted(value("x", baseline=11.0)) == 21.0
    assert result.adjusted(value("x", baseline=1.0)) == 1.0


# ----------------------------------------------- ceremonial picks are not auction results


def test_keeper_picks_are_excluded_from_every_analytic():
    """Charter §2: ceremonial picks poison inflation calibration silently.

    Both picks cost $50. One is a keeper. The realized ratio must see one pick, not two.
    """
    state = state_from((1, "k", 1, 50, True), (2, "c", 1, 50, False))
    board = {"k": value("k", baseline=10.0), "c": value("c", baseline=10.0)}

    assert [pid for _seq, pid, _amt in competitive_picks(state)] == ["c"]
    result = realized_positional_inflation(state, board, min_sample=1)
    assert result["RB"].picks == 1
    assert result["RB"].spent == 50


def test_analytics_key_on_competitive_seq_not_pick_no():
    """Case B puts the ceremonial picks at pick_no 1-20 and shifts every competitive pick.

    A time series keyed on pick_no is therefore a different series in Case A and Case B, and
    the blocking equivalence gate cannot pass. The dense index must start at 1 regardless.
    """
    case_b = state_from((1, "k1", 1, 50, True), (2, "k2", 2, 50, True), (3, "c1", 1, 10, False))
    case_a = state_from((1, "c1", 1, 10, False))

    assert [seq for seq, _pid, _amt in competitive_picks(case_b)] == [1]
    assert [seq for seq, _pid, _amt in competitive_picks(case_a)] == [1]


def test_the_curve_is_identical_between_case_a_and_case_b():
    """The blocking gate, applied to this module's output specifically."""
    board = {
        "k1": value("k1", baseline=0.0, is_keeper=True),
        "k2": value("k2", baseline=0.0, is_keeper=True),
        **{str(i): value(str(i), baseline=11.0) for i in range(6)},
    }
    picks = [(i, str(i), 1, 11, False) for i in range(3)]

    case_b = state_from((100, "k1", 1, 50, True), (101, "k2", 2, 50, True), *picks)
    case_a = state_from(*picks)

    common = {
        "total_budget": 2000,
        "total_slots": 160,
        "keeper_spend": 100,
        "keeper_slots": 2,
    }
    assert inflation_curve(case_b, board, **common) == inflation_curve(case_a, board, **common)


def test_the_curve_advances_one_point_per_competitive_pick():
    board = {str(i): value(str(i), baseline=11.0) for i in range(6)}
    state = state_from(*[(i, str(i), 1, 11, False) for i in range(3)])
    curve = inflation_curve(
        state, board, total_budget=2000, total_slots=160, keeper_spend=0, keeper_slots=0
    )
    assert [seq for seq, _inflation in curve] == [1, 2, 3]


def test_the_curve_removes_bought_players_from_the_remaining_pool():
    """Money spent leaves the room and the player leaves the board. Missing the second half
    leaves money chasing value that is already gone, and deflates every later figure."""
    board = {str(i): value(str(i), baseline=11.0) for i in range(4)}
    state = state_from((1, "0", 1, 11, False))
    curve = inflation_curve(
        state, board, total_budget=44, total_slots=4, keeper_spend=0, keeper_slots=0
    )
    # 3 slots and $33 left against three $11 players: exactly at par.
    assert curve == [(1, 1.0)]


# ---------------------------------------------------------- realized positional inflation


def test_the_realized_ratio_is_dollars_paid_over_model_value():
    """Three RBs worth $10 each, bought for $12 each. 36 / 30 = 1.2."""
    state = state_from(*[(i, str(i), 1, 12, False) for i in range(3)])
    board = {str(i): value(str(i), baseline=10.0) for i in range(3)}

    result = realized_positional_inflation(state, board)

    assert result["RB"].spent == 36
    assert result["RB"].model_value == 30.0
    assert result["RB"].ratio == 1.2
    assert "RB is inflating at 1.20x" in result["RB"].describe()


def test_a_deflated_position_is_described_as_deflated():
    state = state_from(*[(i, str(i), 1, 8, False) for i in range(3)])
    board = {str(i): value(str(i), baseline=10.0, position="QB") for i in range(3)}
    result = realized_positional_inflation(state, board)
    assert result["QB"].ratio == 0.8
    assert "QB is deflated to 0.80x" in result["QB"].describe()


def test_positions_move_independently_which_is_the_entire_point():
    """If RB and QB always report the same number the metric carries no positional signal."""
    state = state_from(
        *[(i, f"rb{i}", 1, 15, False) for i in range(3)],
        *[(10 + i, f"qb{i}", 2, 5, False) for i in range(3)],
    )
    board = {
        **{f"rb{i}": value(f"rb{i}", baseline=10.0, position="RB") for i in range(3)},
        **{f"qb{i}": value(f"qb{i}", baseline=10.0, position="QB") for i in range(3)},
    }

    result = realized_positional_inflation(state, board)

    assert result["RB"].ratio == 1.5
    assert result["QB"].ratio == 0.5


def test_too_small_a_sample_reports_nothing_rather_than_extrapolating():
    """Two RBs going for double is a bidding war between two managers, not a market."""
    state = state_from(*[(i, str(i), 1, 20, False) for i in range(MIN_POSITION_SAMPLE - 1)])
    board = {str(i): value(str(i), baseline=10.0) for i in range(MIN_POSITION_SAMPLE - 1)}

    result = realized_positional_inflation(state, board)

    assert result["RB"].ratio is None
    assert result["RB"].is_reportable is False
    assert result["RB"].picks == MIN_POSITION_SAMPLE - 1
    assert "too few to read" in result["RB"].describe()


def test_the_sample_gate_opens_at_exactly_the_threshold():
    picks = [(i, str(i), 1, 20, False) for i in range(MIN_POSITION_SAMPLE)]
    board = {str(i): value(str(i), baseline=10.0) for i in range(MIN_POSITION_SAMPLE)}
    result = realized_positional_inflation(state_from(*picks), board)
    assert result["RB"].is_reportable


def test_a_pick_for_a_player_not_on_the_board_distorts_neither_side_of_the_ratio():
    """Skipping the numerator but not the denominator, or the reverse, silently biases the
    figure. Contributing to neither is the only treatment that leaves the ratio meaning what
    it says on the label."""
    state = state_from(*[(i, str(i), 1, 12, False) for i in range(3)], (99, "ghost", 1, 100, False))
    board = {str(i): value(str(i), baseline=10.0) for i in range(3)}

    result = realized_positional_inflation(state, board)

    assert result["RB"].picks == 3
    assert result["RB"].spent == 36
    assert result["RB"].ratio == 1.2


def test_a_position_with_no_model_value_reports_nothing_rather_than_infinity():
    """Three $1 players off the priced pool entirely. The room really did spend $3, and the
    model really does say they are worth nothing; the ratio of the two is not a number."""
    picks = [(i, str(i), 1, 1, False) for i in range(3)]
    board = {str(i): value(str(i), baseline=0.0) for i in range(3)}

    result = realized_positional_inflation(state_from(*picks), board)

    assert result["RB"].spent == 3
    assert result["RB"].model_value == 0.0
    assert result["RB"].ratio is None


def test_no_picks_at_a_position_means_no_entry_at_all():
    board = {"a": value("a", baseline=10.0)}
    assert realized_positional_inflation(state_from(), board) == {}


# ------------------------------------ the charter's forward positional formula, pinned


def test_the_forward_formula_separates_positions_rather_than_repeating_one_number():
    """**This test replaces one that asserted the opposite, and the old one was wrong.**

    The previous version claimed §4.5's forward formula was degenerate: allocate money in
    proportion to each position's remaining model *value* and ``value_pos`` cancels, handing
    every position the overall figure. The algebra held; the formula was not the charter's.
    §4.5 says "restrict money and slots to positional **need**" and "allocating FLEX
    proportionally to remaining positional **demand**" -- slots, not value. Under
    slot-proportional allocation ``value_pos`` appears only in the denominator and nothing
    cancels.

    Here: RB has 2 slots against $40 of value, QB has 2 slots against $8. Equal money, very
    different value, so the ratios must differ by a wide margin.
    """
    pool = [
        *[value(f"rb{i}", baseline=21.0, position="RB") for i in range(4)],
        *[value(f"qb{i}", baseline=5.0, position="QB") for i in range(4)],
    ]

    forward = forward_positional_inflation(
        pool, remaining_money=100, remaining_base={"RB": 2, "QB": 2}, remaining_flex=0
    )

    assert forward["RB"].money == forward["QB"].money, "equal slots, equal money"
    assert forward["RB"].value > forward["QB"].value
    rb, qb = forward["RB"].inflation, forward["QB"].inflation
    assert rb is not None and qb is not None
    assert rb != qb
    assert rb < qb, "more value to divide into"


def test_the_forward_formula_matches_its_own_stated_arithmetic():
    """$100 across 4 slots, two per position. RB pool value = 2 x (21 - 1) = 40.
    money_RB = 100 x 2/4 = 50. inflation = (50 - 2) / 40 = 1.2."""
    pool = [
        *[value(f"rb{i}", baseline=21.0, position="RB") for i in range(4)],
        *[value(f"qb{i}", baseline=5.0, position="QB") for i in range(4)],
    ]
    forward = forward_positional_inflation(
        pool, remaining_money=100, remaining_base={"RB": 2, "QB": 2}, remaining_flex=0
    )
    assert forward["RB"].value == 40.0
    assert forward["RB"].money == 50.0
    assert forward["RB"].inflation == pytest.approx(1.2)


def test_flex_is_split_proportionally_to_remaining_demand_not_evenly():
    """§4.5's own words. An even three-way split with a floor also throws slots away."""
    pool = [value(f"p{i}", baseline=5.0, position="RB") for i in range(20)]
    pool += [value(f"w{i}", baseline=5.0, position="WR") for i in range(20)]
    pool += [value(f"t{i}", baseline=5.0, position="TE") for i in range(20)]

    forward = forward_positional_inflation(
        pool, remaining_money=200, remaining_base={"RB": 8, "WR": 8, "TE": 4}, remaining_flex=5
    )

    assert forward["RB"].slots + forward["WR"].slots + forward["TE"].slots == 25, (
        "all five FLEX slots allocated, none floored away"
    )
    assert forward["TE"].slots < forward["RB"].slots, "allocated by demand, not evenly"


def test_a_position_with_no_value_left_reports_none_rather_than_a_ratio():
    """Not 1.0, which would read as "correctly priced" at a position where nothing is priced."""
    pool = [value(f"k{i}", baseline=1.0, position="K") for i in range(4)]
    forward = forward_positional_inflation(
        pool, remaining_money=100, remaining_base={"K": 2}, remaining_flex=0
    )
    assert forward["K"].value == 0.0
    assert forward["K"].inflation is None
    assert "no value left to price" in forward["K"].describe()


def test_a_position_with_almost_no_value_is_flagged_as_an_artifact():
    """Kickers do this on every board: ten slots that must be filled by players worth nothing
    over replacement, so a slot-proportional allocation divides real money by almost nothing.
    That is a property of the allocation, not a finding about the kicker market."""
    pool = [
        *[value(f"rb{i}", baseline=41.0, position="RB") for i in range(10)],
        *[value(f"k{i}", baseline=1.05, position="K") for i in range(10)],
    ]

    forward = forward_positional_inflation(
        pool, remaining_money=400, remaining_base={"RB": 8, "K": 8}, remaining_flex=0
    )

    assert forward["RB"].reliable
    assert forward["K"].reliable is False
    assert forward["K"].inflation is not None and forward["K"].inflation > 10
    assert "artifact" in forward["K"].describe()


# ------------------------------------------------- the identity, on the real board


@pytest.fixture(scope="module")
def real_board():
    """The actual priced board, built the way the CLI builds it."""
    config = load_league_config(CONFIG / "league.yaml")
    league = json.loads((FIXTURES / "league.json").read_text())
    players_map = json.loads((FIXTURES / "players_slim.json").read_text())
    projections_raw = json.loads((FIXTURES / "projections_slim.json").read_text())
    picks = json.loads((FIXTURES / "picks.json").read_text())

    projections, _ = build_projections(projections_raw, league["scoring_settings"])
    resolved = resolve_manifest(load_manifest(CONFIG / "keepers.yaml"), players_map)
    keeper_ids = frozenset(pid for _owner, pid in resolved)
    keeper_spend = sum(int(p["metadata"]["amount"]) for p in picks if p["player_id"] in keeper_ids)

    positions: dict[int, list[str]] = {}
    for slot, (_key, entry) in enumerate(sorted(resolved.items()), start=1):
        positions.setdefault((slot - 1) // 2 + 1, []).append(entry.pos)
    demand = seat_keepers(positions, starters=config.starters, teams=config.teams)

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
    return board, roster_live


def test_on_the_real_board_inflation_starts_at_exactly_one(real_board):
    """The load-bearing claim of §4.5, checked against the board the tool actually prices.

    If this drifts, baseline_value has stopped summing to total_live_money and the §4.3 sum
    invariant is broken somewhere upstream -- so this is a second, independent check on the
    valuation as much as it is a check on the inflation formula.
    """
    board, roster_live = real_board
    available = [p for p in board.players if p.in_pool_live]

    result = market_inflation(
        available, remaining_money=board.total_live_money, remaining_slots=roster_live
    )

    assert result.pool_size == roster_live
    assert result.inflation == pytest.approx(1.0, abs=0.001)


def test_the_first_real_bid_moves_inflation_off_one(real_board):
    """A no-op formula would sit at 1.0 forever and read as a working feature."""
    board, roster_live = real_board
    available = [p for p in board.players if p.in_pool_live]
    top = max(available, key=lambda p: p.baseline_value)

    after = market_inflation(
        [p for p in available if p.player_id != top.player_id],
        remaining_money=board.total_live_money - int(top.baseline_value * 2),
        remaining_slots=roster_live - 1,
    )

    assert after.inflation < 0.99
