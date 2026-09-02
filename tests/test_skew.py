"""DI-033 — skew, the headline metric.

Every figure is derived by hand in the test that asserts it. No player name is hardcoded;
synthetic players are named by position and index.
"""

from __future__ import annotations

import pytest

from draft_intel.domain.ledger import fold
from draft_intel.models import DerivedState, PickObserved, PickSnapshot
from draft_intel.quant.market import MarketValues
from draft_intel.quant.skew import MIN_VALUE_FOR_PCT, PickSkew, SkewBoard, skew_board
from draft_intel.quant.valuation import PlayerValue

SLOTS = range(1, 11)


def value(
    player_id: str,
    *,
    baseline: float,
    position: str = "RB",
    is_keeper: bool = False,
    points: float = 100.0,
) -> PlayerValue:
    return PlayerValue(
        player_id=player_id,
        name=f"{position}{player_id}",
        position=position,
        team=None,
        points=points,
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
    return fold(
        [
            PickObserved(
                seq=i,
                pick=PickSnapshot(
                    pick_no=pick_no,
                    player_id=player_id,
                    slot=slot,
                    amount=amount,
                    is_keeper=keeper,
                ),
            )
            for i, (pick_no, player_id, slot, amount, keeper) in enumerate(picks, start=1)
        ],
        slots=SLOTS,
    )


def par_board(
    count: int = 10, *, baseline: float = 11.0, **kwargs: object
) -> dict[str, PlayerValue]:
    """A board where inflation sits at exactly 1.0 while picks land at ``baseline``."""
    return {str(i): value(str(i), baseline=baseline, **kwargs) for i in range(count)}  # type: ignore[arg-type]


def at_par(
    state: DerivedState,
    board: dict[str, PlayerValue],
    market: MarketValues,
    owners: dict[int, str] | None = None,
) -> SkewBoard:
    """$110 across 10 slots against ten $11 players: inflation is exactly 1.0 at pick 0."""
    return skew_board(
        state,
        board,
        market,
        total_budget=110,
        total_slots=10,
        keeper_spend=0,
        keeper_slots=0,
        owners=owners,
    )


# ------------------------------------------------------ the two measures, kept apart


def test_the_two_skews_are_different_quantities_from_different_sources():
    """§4.6's whole point. Consensus says $20, our model says $11, the room paid $15.

    Market skew is -5 (the room got it under consensus). Edge skew is +4 (the room paid over
    what our model says). Both true at once, and merging them destroys the disagreement that
    is the entire signal.
    """
    board = par_board(10)
    state = state_from((1, "0", 1, 15, False))
    market = MarketValues(source="csv", values={"0": 20.0})

    result = at_par(state, board, market)

    (pick,) = result.picks
    assert pick.inflation_at_pick == 1.0
    assert pick.adjusted_value == 11.0
    assert pick.market_skew == -5.0
    assert pick.edge_skew == 4.0


def test_market_skew_uses_the_consensus_value_not_our_own_model():
    """Passing our own number on both sides makes the two skews the same figure computed twice,
    and the gap between them -- which is the only thing that says whether *we* disagree with the
    room -- becomes zero by construction."""
    board = par_board(10)
    state = state_from((1, "0", 1, 15, False))

    ours = at_par(state, board, MarketValues(source="csv", values={"0": 11.0}))
    theirs = at_par(state, board, MarketValues(source="csv", values={"0": 30.0}))

    assert ours.picks[0].market_skew == ours.picks[0].edge_skew
    assert theirs.picks[0].market_skew != theirs.picks[0].edge_skew
    assert theirs.picks[0].edge_skew == ours.picks[0].edge_skew, "edge skew is unaffected"


def test_a_pick_with_no_consensus_value_is_excluded_from_market_skew_not_counted_as_zero():
    """Counting it as zero would drag every aggregate toward "the room paid consensus"."""
    board = par_board(10)
    state = state_from((1, "0", 1, 15, False), (2, "1", 1, 15, False))
    market = MarketValues(source="csv", values={"0": 20.0})

    result = at_par(state, board, market)

    unpriced = next(p for p in result.picks if p.player_id == "1")
    assert unpriced.market_value is None
    assert unpriced.market_skew is None
    assert unpriced.market_skew_pct is None
    assert result.overall.market_priced == 1
    assert result.overall.picks == 2
    assert any("excluded from market skew" in note for note in result.caveats())


# ----------------------------------------- judged against the inflation the room faced


def test_a_pick_is_judged_against_the_inflation_before_it_not_after():
    """Measuring a pick against the state it helped create measures it partly against its own
    effect: a big overpay deflates the rest of the board, so judging it against the *after*
    figure flatters it.

    Ten $11 players, $110 and 10 slots: inflation is exactly 1.0. The first pick goes for $51 --
    a $40 overpay. Before: 1.0, so adjusted value $11 and edge skew +$40. After, only $59
    remains for 9 slots against $90 of value, so inflation drops to 0.5556 and the same pick
    would score as +$45 against a $6.11 adjusted value. The first number is the true one.
    """
    board = par_board(10)
    state = state_from((1, "0", 1, 51, False))

    result = at_par(state, board, MarketValues(source="none", values={}))

    (pick,) = result.picks
    assert pick.inflation_at_pick == 1.0
    assert pick.adjusted_value == 11.0
    assert pick.edge_skew == 40.0


def test_later_picks_are_judged_against_the_deflated_board_the_earlier_ones_left():
    """The corollary: after a big overpay there is less money for everyone, so the same nominal
    price on a later player is a bigger overpay in real terms."""
    board = par_board(10)
    state = state_from((1, "0", 1, 51, False), (2, "1", 2, 11, False))

    result = at_par(state, board, MarketValues(source="none", values={}))

    first, second = result.picks
    assert second.inflation_at_pick < first.inflation_at_pick
    assert second.adjusted_value < first.adjusted_value
    assert second.edge_skew > 0, "$11 is an overpay once the room is short of money"


# ---------------------------------------------------- ceremonial picks stay out of it


def test_keeper_picks_never_reach_the_skew_board():
    """Charter §2: they were not competitive bids and they poison this silently."""
    board = {**par_board(4), "k": value("k", baseline=0.0, is_keeper=True)}
    state = state_from((1, "k", 1, 90, True), (2, "0", 1, 11, False))

    result = skew_board(
        state,
        board,
        MarketValues(source="none", values={}),
        total_budget=110,
        total_slots=10,
        keeper_spend=90,
        keeper_slots=1,
    )

    assert [p.player_id for p in result.picks] == ["0"]
    assert result.overall.spent == 11


def test_a_pick_naming_a_player_off_the_board_is_skipped_rather_than_invented():
    board = par_board(4)
    state = state_from((1, "0", 1, 11, False), (2, "ghost", 1, 50, False))
    result = at_par(state, board, MarketValues(source="none", values={}))
    assert [p.player_id for p in result.picks] == ["0"]
    assert result.overall.spent == 11, "the phantom's dollars do not enter the aggregate either"


# ------------------------------------------------------------------- aggregations


def test_per_team_rollup_sums_and_averages_over_that_team_only():
    board = par_board(6)
    state = state_from((1, "0", 1, 21, False), (2, "1", 1, 1, False), (3, "2", 2, 11, False))

    result = at_par(
        state, board, MarketValues(source="none", values={}), owners={1: "AJ", 2: "Jake"}
    )

    assert result.by_team["AJ"].picks == 2
    assert result.by_team["AJ"].spent == 22
    assert result.by_team["Jake"].picks == 1
    assert result.by_team["Jake"].spent == 11
    assert set(result.by_team) == {"AJ", "Jake"}


def test_an_unmapped_slot_still_gets_a_row():
    """Six managers have not joined the real league. A team's skew must not vanish because of it."""
    board = par_board(4)
    state = state_from((1, "0", 7, 11, False))
    result = at_par(state, board, MarketValues(source="none", values={}), owners={})
    assert "slot 7" in result.by_team


def test_per_position_rollup_separates_positions():
    board = {
        **{str(i): value(str(i), baseline=11.0, position="RB") for i in range(3)},
        **{f"q{i}": value(f"q{i}", baseline=11.0, position="QB") for i in range(3)},
    }
    state = state_from((1, "0", 1, 21, False), (2, "q0", 1, 5, False), (3, "1", 2, 21, False))

    result = at_par(state, board, MarketValues(source="none", values={}))

    assert result.by_position["RB"].picks == 2
    assert result.by_position["QB"].picks == 1
    assert result.by_position["RB"].total_edge_skew > 0
    assert result.by_position["QB"].total_edge_skew < 0


def test_dollars_per_projected_point_is_the_per_team_efficiency_figure():
    """§4.6. $22 spent on 200 projected points is $0.11 per point."""
    board = {str(i): value(str(i), baseline=11.0, points=100.0) for i in range(4)}
    state = state_from((1, "0", 1, 11, False), (2, "1", 1, 11, False))

    result = at_par(state, board, MarketValues(source="none", values={}), owners={1: "AJ"})

    assert result.by_team["AJ"].projected_points == 200.0
    assert result.by_team["AJ"].dollars_per_projected_point == 0.11


def test_no_projected_points_reports_nothing_rather_than_dividing_by_zero():
    board = {"0": value("0", baseline=11.0, points=0.0)}
    state = state_from((1, "0", 1, 11, False))
    result = at_par(state, board, MarketValues(source="none", values={}))
    assert result.overall.dollars_per_projected_point is None


def test_a_single_pick_reports_no_standard_deviation_rather_than_zero():
    """Zero spread would read as a disciplined bidder rather than as a sample of one."""
    board = par_board(4)
    single = at_par(
        state_from((1, "0", 1, 11, False)), board, MarketValues(source="none", values={})
    )
    assert single.overall.stdev_edge_skew is None

    pair = at_par(
        state_from((1, "0", 1, 21, False), (2, "1", 1, 1, False)),
        board,
        MarketValues(source="none", values={}),
    )
    assert pair.overall.stdev_edge_skew is not None
    assert pair.overall.stdev_edge_skew > 0


# ---------------------------------------------------------------------- percentages


def test_skew_is_reported_as_dollars_and_as_a_percentage_of_value():
    """§4.6 asks for both. $15 paid against a $10 consensus is +$5 and +50%."""
    pick = PickSkew(
        competitive_seq=1,
        player_id="a",
        name="RBa",
        position="RB",
        slot=1,
        price_paid=15,
        market_value=10.0,
        market_value_is_estimate=False,
        adjusted_value=12.0,
        inflation_at_pick=1.0,
    )
    assert pick.market_skew == 5.0
    assert pick.market_skew_pct == 50.0
    assert pick.edge_skew == 3.0
    assert pick.edge_skew_pct == 25.0


@pytest.mark.parametrize("tiny", [0.0, 0.5, MIN_VALUE_FOR_PCT - 0.01])
def test_a_percentage_on_a_near_zero_value_is_withheld_rather_than_reported(tiny):
    """$2 paid for a player valued at $0.10 is +1900%, which tells nobody anything. The dollar
    figure still stands."""
    pick = PickSkew(
        competitive_seq=1,
        player_id="a",
        name="RBa",
        position="RB",
        slot=1,
        price_paid=2,
        market_value=tiny,
        market_value_is_estimate=False,
        adjusted_value=tiny,
        inflation_at_pick=1.0,
    )
    assert pick.market_skew_pct is None
    assert pick.edge_skew_pct is None
    assert pick.market_skew == round(2 - tiny, 2)


# ------------------------------------------------------------------------- caveats


def test_an_estimated_consensus_is_called_out_as_not_evidence():
    """The fallback providers borrow our own ladder, so the two skews converge by construction.
    Presenting their gap as a finding would be presenting an artefact as a signal."""
    board = par_board(4)
    state = state_from((1, "0", 1, 11, False))
    market = MarketValues(source="adp_rank_transfer", values={"0": 11.0})

    result = at_par(state, board, market)

    assert result.picks[0].market_value_is_estimate
    assert any("converge by construction" in note for note in result.caveats())


def test_real_auction_values_raise_no_caveat():
    board = par_board(4)
    state = state_from((1, "0", 1, 11, False))
    result = at_par(state, board, MarketValues(source="csv", values={"0": 11.0}))
    assert result.caveats() == []


def test_the_biggest_overpays_and_bargains_are_the_extremes_of_edge_skew():
    board = par_board(6)
    state = state_from((1, "0", 1, 30, False), (2, "1", 1, 11, False), (3, "2", 2, 1, False))
    result = at_par(state, board, MarketValues(source="none", values={}))

    assert result.biggest_overpays(1)[0].player_id == "0"
    assert result.biggest_bargains(1)[0].player_id == "2"
