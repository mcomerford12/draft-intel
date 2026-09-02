"""DI-034 — opponent max bids and the affordability ladder.

Two teams' worth of arithmetic, checkable on paper. No player name is hardcoded.
"""

from __future__ import annotations

import pytest

from draft_intel.domain.ledger import fold
from draft_intel.models import DerivedState, PickObserved, PickSnapshot
from draft_intel.quant.affordability import (
    MIN_AGGRESSION_SAMPLE,
    affordability,
    my_max_bid,
)
from draft_intel.quant.market import MarketValues
from draft_intel.quant.skew import SkewBoard, skew_board
from draft_intel.quant.valuation import PlayerValue

SLOTS = range(1, 4)
STARTERS = {"QB": 2, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1}
BUDGET = 200
DRAFT_ROUNDS = 16


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
        budget=BUDGET,
        total_slots=DRAFT_ROUNDS,
    )


def positions(**by_id: str) -> dict[str, str]:
    return dict(by_id)


# ------------------------------------------------------------------ max bid arithmetic


def test_max_bid_reserves_a_dollar_for_every_remaining_slot():
    """§1.1. $200 and 16 slots: bid at most $185, keeping $1 for each of the other 15."""
    result = affordability(state_from(), position="RB", my_slot=1, starters=STARTERS, positions={})
    assert result.my_open_slots == 16
    assert result.my_max_bid == BUDGET - (16 - 1)
    assert all(o.max_bid == 185 for o in result.opponents)


def test_spending_power_diverges_the_moment_keepers_differ():
    """§1.1: the ledger is uniform but remaining budgets are not, from pick 1."""
    state = state_from((1, "k1", 2, 90, True), (2, "k2", 3, 10, True))

    result = affordability(state, position="RB", my_slot=1, starters=STARTERS, positions={})

    by_slot = {o.slot: o for o in result.opponents}
    assert by_slot[2].budget_remaining == 110
    assert by_slot[3].budget_remaining == 190
    # Both have 15 open slots, so each reserves $14.
    assert by_slot[2].max_bid == 110 - 14
    assert by_slot[3].max_bid == 190 - 14


def test_max_bid_is_read_from_the_ledger_rather_than_recomputed():
    """Two implementations of the same rule drift, and one of them is the one on screen."""
    state = state_from((1, "k1", 2, 90, True))
    result = affordability(state, position="RB", my_slot=1, starters=STARTERS, positions={})
    opponent = next(o for o in result.opponents if o.slot == 2)
    assert opponent.max_bid == state.teams[2].max_bid


def test_a_team_with_no_slots_left_cannot_afford_anything():
    picks = [(i, f"p{i}", 2, 1, False) for i in range(DRAFT_ROUNDS)]
    state = state_from(*picks)
    result = affordability(state, position="RB", my_slot=1, starters=STARTERS, positions={})
    opponent = next(o for o in result.opponents if o.slot == 2)
    assert opponent.open_slots == 0
    assert opponent.can_afford is False
    assert opponent.threat == 0.0


# ------------------------------------------------------------------- positional need


def test_a_team_with_both_starting_slots_filled_does_not_need_the_position():
    state = state_from((1, "q1", 2, 5, False), (2, "q2", 2, 5, False))
    result = affordability(
        state,
        position="QB",
        my_slot=1,
        starters=STARTERS,
        positions=positions(q1="QB", q2="QB"),
    )
    opponent = next(o for o in result.opponents if o.slot == 2)
    assert opponent.starting_gap == 0
    assert opponent.needs_position is False


def test_keepers_occupy_starting_slots_exactly_as_bought_players_do():
    """§2: money, roster and slot math use every pick regardless of class."""
    state = state_from((1, "q1", 2, 30, True), (2, "q2", 2, 25, True))
    result = affordability(
        state,
        position="QB",
        my_slot=1,
        starters=STARTERS,
        positions=positions(q1="QB", q2="QB"),
    )
    assert next(o for o in result.opponents if o.slot == 2).needs_position is False


def test_flex_absorbs_overflow_collectively_not_once_per_position():
    """Two FLEX slots cannot be free for RB, WR and TE simultaneously.

    Base RB and WR are full and one extra RB is already rostered, so one FLEX is used. Exactly
    one FLEX remains, and it is the *same* slot whichever position asks about it.
    """
    state = state_from(
        (1, "r1", 2, 5, False),
        (2, "r2", 2, 5, False),
        (3, "r3", 2, 5, False),
        (4, "w1", 2, 5, False),
        (5, "w2", 2, 5, False),
    )
    board = positions(r1="RB", r2="RB", r3="RB", w1="WR", w2="WR")

    gaps = {
        position: next(
            o
            for o in affordability(
                state, position=position, my_slot=1, starters=STARTERS, positions=board
            ).opponents
            if o.slot == 2
        ).starting_gap
        for position in ("RB", "WR", "TE")
    }

    assert gaps["RB"] == 1, "one FLEX left, reachable by an RB"
    assert gaps["WR"] == 1, "the same one FLEX, reachable by a WR"
    assert gaps["TE"] == 1, "TE's own base slot is still open"


def test_a_rostered_player_the_board_does_not_know_fills_no_slot():
    """Inventing a position would report a starting slot as filled that may not be."""
    state = state_from((1, "mystery", 2, 5, False))
    result = affordability(state, position="QB", my_slot=1, starters=STARTERS, positions={})
    assert next(o for o in result.opponents if o.slot == 2).starting_gap == 2


# ------------------------------------------------------------- demonstrated aggression


PAR_BASELINE = 5.0
PAR_FILLER = 200


def padded(board: dict[str, PlayerValue]) -> dict[str, PlayerValue]:
    """The board plus enough filler that a handful of picks barely move inflation.

    Aggression is a statement about a manager, so the arithmetic behind it has to isolate the
    manager from the room. On a four-player board three picks swing inflation by an order of
    magnitude and every edge figure is dominated by that swing rather than by who bid what.
    """
    return {
        **board,
        **{
            f"pad{i}": value(f"pad{i}", baseline=PAR_BASELINE, position="TE")
            for i in range(PAR_FILLER)
        },
    }


def _skew_for(state: DerivedState, board: dict[str, PlayerValue]) -> SkewBoard:
    """Skew computed on a board sized so inflation starts at exactly 1.0."""
    full = padded(board)
    return skew_board(
        state,
        full,
        MarketValues(source="none", values={}),
        total_budget=int(PAR_BASELINE * len(full)),
        total_slots=len(full),
        keeper_spend=0,
        keeper_slots=0,
    )


def value(player_id: str, *, baseline: float, position: str) -> PlayerValue:
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
        is_keeper=False,
        in_pool_full=True,
        in_pool_live=True,
    )


def test_no_evidence_is_reported_as_none_rather_than_as_zero():
    """No read is a different statement from a read of "perfectly disciplined", and rendering
    it as 0.0 would rank an unknown manager as precisely average."""
    result = affordability(
        state_from(), position="RB", my_slot=1, starters=STARTERS, positions={}, skew=None
    )
    assert all(o.aggression is None and o.aggression_picks == 0 for o in result.opponents)


def test_too_few_picks_at_a_position_is_still_no_read():
    board = {f"r{i}": value(f"r{i}", baseline=5.0, position="RB") for i in range(4)}
    state = state_from(*[(i, f"r{i}", 2, 40, False) for i in range(MIN_AGGRESSION_SAMPLE - 1)])

    result = affordability(
        state,
        position="RB",
        my_slot=1,
        starters=STARTERS,
        positions={pid: "RB" for pid in board},
        skew=_skew_for(state, board),
    )

    opponent = next(o for o in result.opponents if o.slot == 2)
    assert opponent.aggression is None
    assert opponent.aggression_picks == MIN_AGGRESSION_SAMPLE - 1


def test_a_manager_who_has_been_overpaying_reads_as_aggressive():
    board = {f"r{i}": value(f"r{i}", baseline=5.0, position="RB") for i in range(4)}
    state = state_from(*[(i, f"r{i}", 2, 40, False) for i in range(3)])

    result = affordability(
        state,
        position="RB",
        my_slot=1,
        starters=STARTERS,
        positions={pid: "RB" for pid in board},
        skew=_skew_for(state, board),
    )

    opponent = next(o for o in result.opponents if o.slot == 2)
    assert opponent.aggression is not None
    assert opponent.aggression > 0
    assert opponent.aggression_picks == 3


def test_aggression_is_keyed_on_draft_slot_not_owner_name():
    """The project's standing rule. Names may be unresolved -- six managers have not joined --
    and two teams can share a fallback label, while the slot is always present and unique."""
    board = {f"r{i}": value(f"r{i}", baseline=5.0, position="RB") for i in range(6)}
    state = state_from(
        *[(i, f"r{i}", 2, 40, False) for i in range(3)],
        *[(10 + i, f"r{3 + i}", 3, 1, False) for i in range(3)],
    )
    skew = _skew_for(state, board)

    result = affordability(
        state,
        position="RB",
        my_slot=1,
        starters=STARTERS,
        positions={pid: "RB" for pid in board},
        owners={},  # nothing resolves; both fall back to "slot N"
        skew=skew,
    )

    by_slot = {o.slot: o for o in result.opponents}
    assert by_slot[2].aggression is not None and by_slot[2].aggression > 0
    assert by_slot[3].aggression is not None and by_slot[3].aggression < 0
    assert by_slot[2].aggression != by_slot[3].aggression


def test_aggression_at_one_position_does_not_leak_into_another():
    board = {
        **{f"r{i}": value(f"r{i}", baseline=5.0, position="RB") for i in range(3)},
        **{f"q{i}": value(f"q{i}", baseline=5.0, position="QB") for i in range(3)},
    }
    state = state_from(
        *[(i, f"r{i}", 2, 40, False) for i in range(3)],
        *[(10 + i, f"q{i}", 2, 1, False) for i in range(3)],
    )
    skew = _skew_for(state, board)
    board_positions = {pid: player.position for pid, player in board.items()}

    rb = affordability(
        state, position="RB", my_slot=1, starters=STARTERS, positions=board_positions, skew=skew
    )
    qb = affordability(
        state, position="QB", my_slot=1, starters=STARTERS, positions=board_positions, skew=skew
    )

    assert next(o for o in rb.opponents if o.slot == 2).aggression > 0  # type: ignore[operator]
    assert next(o for o in qb.opponents if o.slot == 2).aggression < 0  # type: ignore[operator]


# ------------------------------------------------------------------------ the ladder


def test_opponents_are_ordered_by_threat_and_a_needy_rich_team_leads():
    """Slot 2 is rich and needs the position; slot 3 is rich and does not."""
    state = state_from((1, "q1", 3, 5, False), (2, "q2", 3, 5, False))
    result = affordability(
        state,
        position="QB",
        my_slot=1,
        starters=STARTERS,
        positions=positions(q1="QB", q2="QB"),
    )
    assert [o.slot for o in result.opponents] == [2, 3]
    assert result.opponents[0].needs_position
    assert not result.opponents[1].needs_position


def test_contenders_excludes_teams_with_no_need_and_teams_with_no_money():
    state = state_from((1, "q1", 3, 5, False), (2, "q2", 3, 5, False))
    result = affordability(
        state,
        position="QB",
        my_slot=1,
        starters=STARTERS,
        positions=positions(q1="QB", q2="QB"),
    )
    assert [o.slot for o in result.contenders] == [2]


def test_who_is_still_in_at_a_given_price():
    state = state_from((1, "k", 2, 150, True))
    result = affordability(state, position="RB", my_slot=1, starters=STARTERS, positions={})

    assert {o.slot for o in result.still_in_at(30)} == {2, 3}
    assert {o.slot for o in result.still_in_at(50)} == {3}
    assert result.still_in_at(200) == ()


def test_the_price_that_clears_the_field_is_a_dollar_over_the_best_opponent():
    state = state_from((1, "k", 2, 150, True))
    result = affordability(state, position="RB", my_slot=1, starters=STARTERS, positions={})
    highest = max(o.max_bid for o in result.opponents)
    assert result.price_that_clears_the_field() == highest + 1
    assert result.still_in_at(result.price_that_clears_the_field()) == ()


def test_an_unmapped_slot_is_labelled_by_number_not_dropped():
    """A live opponent must not vanish from the threat list because its manager has not joined."""
    result = affordability(
        state_from(), position="RB", my_slot=1, starters=STARTERS, positions={}, owners={2: "AJ"}
    )
    assert {o.owner for o in result.opponents} == {"AJ", "slot 3"}


def test_the_user_is_never_on_their_own_threat_list():
    result = affordability(state_from(), position="RB", my_slot=1, starters=STARTERS, positions={})
    assert 1 not in {o.slot for o in result.opponents}
    assert len(result.opponents) == 2


def test_a_slot_outside_the_league_raises_rather_than_listing_everyone():
    """Silently returning every team as an opponent puts the user on their own threat list."""
    with pytest.raises(KeyError, match="not in this league"):
        affordability(state_from(), position="RB", my_slot=99, starters=STARTERS, positions={})


# ------------------------------------------------------------------ my max bid, labelled


def test_my_max_bid_labels_the_binding_constraint():
    """§4.7a requires the label, and it is the useful half: "out of money" and "not worth it"
    are entirely different situations, and a bare number says neither."""
    state = state_from((1, "k", 1, 190, True))

    tight, reason = my_max_bid(state, my_slot=1, adjusted_value=100.0)
    assert reason == "budget"
    assert tight == state.teams[1].max_bid

    rich, reason = my_max_bid(state_from(), my_slot=1, adjusted_value=40.0)
    assert reason == "value"
    assert rich == 40


def test_a_strategic_premium_raises_the_value_ceiling_only():
    state = state_from()
    plain, _ = my_max_bid(state, my_slot=1, adjusted_value=40.0)
    with_premium, reason = my_max_bid(state, my_slot=1, adjusted_value=40.0, strategic_premium=5.0)
    assert with_premium == plain + 5
    assert reason == "value"


def test_the_premium_can_never_push_a_bid_past_what_the_budget_allows():
    state = state_from((1, "k", 1, 190, True))
    capped, reason = my_max_bid(state, my_slot=1, adjusted_value=100.0, strategic_premium=500.0)
    assert reason == "budget"
    assert capped == state.teams[1].max_bid
    assert capped <= state.teams[1].remaining


def test_describe_says_where_each_opponent_drops_out():
    state = state_from((1, "k", 2, 150, True))
    lines = affordability(
        state, position="RB", my_slot=1, starters=STARTERS, positions={}, owners={2: "AJ"}
    ).describe()
    assert any("AJ: out above $" in line and "no read yet" in line for line in lines)


# ------------------------------------- mutation escapes closed (DI-034 verification)


def test_a_manager_we_have_no_read_on_is_still_a_threat():
    """Zeroing an unknown manager's threat sorts every quiet one to the bottom, precisely when
    they are about to spend. No read means ordinary, not harmless.

    Slot 2 has no read and needs the position; slot 3 has spent its budget down to nothing.
    """
    state = state_from(*[(i, f"p{i}", 3, 12, False) for i in range(15)])

    result = affordability(state, position="RB", my_slot=1, starters=STARTERS, positions={})

    unknown = next(o for o in result.opponents if o.slot == 2)
    broke = next(o for o in result.opponents if o.slot == 3)
    assert unknown.aggression is None
    assert unknown.threat > broke.threat
    assert result.opponents[0].slot == 2


def test_still_in_at_includes_a_team_bidding_exactly_its_maximum():
    """A team's max bid is a bid it can make, not one dollar past what it can make. Off by one
    here drops the most dangerous opponent from the list at exactly the price that matters."""
    state = state_from((1, "k", 2, 150, True))
    result = affordability(state, position="RB", my_slot=1, starters=STARTERS, positions={})
    opponent = next(o for o in result.opponents if o.slot == 2)

    assert opponent in result.still_in_at(opponent.max_bid)
    assert opponent not in result.still_in_at(opponent.max_bid + 1)


def test_a_team_with_money_but_no_roster_spot_cannot_bid():
    """The ledger already forces max_bid to 0 on a full roster, so this is belt and braces --
    but the two conditions mean different things and a future ledger change must not silently
    make a full team look live."""
    from draft_intel.quant.affordability import Opponent

    full = Opponent(
        slot=2,
        owner="AJ",
        budget_remaining=50,
        open_slots=0,
        max_bid=50,
        needs_position=True,
        starting_gap=1,
        aggression=None,
        aggression_picks=0,
    )
    assert full.can_afford is False
    assert full.threat == 0.0
