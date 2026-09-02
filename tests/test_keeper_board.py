"""DI-031 — the keeper surplus board and structural keeper inflation.

Built on a league small enough to check on paper. Two teams, $100 each, $200 in the room,
4 roster spots total, one keeper. Every figure below is derived by hand in the test that
asserts it, so a wrong implementation cannot make a test agree with it.

No player name is hardcoded; the synthetic players are named by position and index.
"""

from __future__ import annotations

import pytest

from draft_intel.quant.keeper_board import (
    PRICE_DIVERGENCE_DOLLARS,
    IncompleteScenario,
    KeeperLine,
    Scenario,
    keeper_board,
)
from draft_intel.quant.market import MarketValues
from draft_intel.quant.valuation import PlayerValue, ValueBoard

TOTAL_BUDGET = 200


def value(
    player_id: str,
    *,
    market_value: float,
    is_keeper: bool = False,
    position: str = "RB",
    baseline_value: float = 0.0,
) -> PlayerValue:
    return PlayerValue(
        player_id=player_id,
        name=f"{position}{player_id}",
        position=position,
        team=None,
        points=100.0,
        vorp=market_value,
        market_value=market_value,
        vorp_live=baseline_value,
        baseline_value=baseline_value,
        is_keeper=is_keeper,
        in_pool_full=True,
        in_pool_live=not is_keeper,
    )


def board(*players: PlayerValue, budget: int = TOTAL_BUDGET) -> ValueBoard:
    """A ValueBoard carrying only the fields the keeper board reads.

    The valuation figures are supplied directly rather than computed, so a bug in
    ``value_board`` cannot make these tests pass or fail for the wrong reason.
    """
    keepers = [p for p in players if p.is_keeper]
    available = [p for p in players if not p.is_keeper]
    return ValueBoard(
        players=players,
        total_budget=budget,
        keeper_spend=0,
        total_live_money=budget,
        discretionary=budget - len(players),
        discretionary_live=budget - len(available),
        dollars_per_vorp=1.0,
        dollars_per_vorp_live=1.0,
        pool_full_size=len(players),
        pool_live_size=len(available),
        sum_market_value=round(sum(p.market_value for p in players), 2),
        sum_baseline_value=round(sum(p.baseline_value for p in available), 2),
        keeper_book_value=round(sum(p.market_value for p in keepers), 2),
        available_book_value=round(sum(p.market_value for p in available), 2),
    )


def market(**values: float) -> MarketValues:
    return MarketValues(source="csv", values=dict(values))


# ------------------------------------------------------------------ surplus, by hand


def test_surplus_is_book_minus_paid_and_positive_means_the_room_got_them_cheap():
    """Keeper worth $40 retained at $30. Surplus $10. Nothing subtler than that."""
    priced = board(value("k1", market_value=40.0, is_keeper=True), value("a", market_value=60.0))

    result = keeper_board(
        priced, keeper_owners={"k1": "AJ"}, prices={"k1": 30}, market=market(k1=40.0)
    )

    (line,) = result.lines
    assert line.book_value == 40.0
    assert line.price_paid == 30
    assert line.surplus == 10.0
    assert result.as_loaded.keeper_surplus == 10.0


def test_a_keeper_retained_above_book_produces_negative_surplus():
    """The mock slate's situation: prices set at roughly full book, so no discount at all."""
    priced = board(value("k1", market_value=40.0, is_keeper=True), value("a", market_value=60.0))
    result = keeper_board(
        priced, keeper_owners={"k1": "AJ"}, prices={"k1": 55}, market=market(k1=40.0)
    )
    assert result.lines[0].surplus == -15.0
    assert result.as_loaded.keeper_surplus == -15.0


def test_keeper_inflation_is_live_money_over_book_still_on_the_board():
    """$200 room, $30 of keepers retained, $60 of book left available.

    live money = 200 - 30 = 170. available book = 60. inflation = 170 / 60 = 2.8333.

    Deliberately NOT a ratio of money pools. An earlier version computed
    discretionary_live / discretionary and reported a number that moves when roster size
    changes even though no price does.
    """
    priced = board(value("k1", market_value=40.0, is_keeper=True), value("a", market_value=60.0))

    result = keeper_board(
        priced, keeper_owners={"k1": "AJ"}, prices={"k1": 30}, market=market(k1=40.0)
    )

    assert result.as_loaded.total_live_money == 170
    assert result.as_loaded.available_book_value == 60.0
    assert result.as_loaded.keeper_inflation == pytest.approx(170 / 60, abs=1e-4)


def test_inflation_above_one_means_the_field_should_clear_over_book():
    """The direction has to be right or every bid is wrong all night."""
    cheap = keeper_board(
        board(value("k1", market_value=90.0, is_keeper=True), value("a", market_value=100.0)),
        keeper_owners={"k1": "AJ"},
        prices={"k1": 10},
        market=market(k1=90.0),
    )
    dear = keeper_board(
        board(value("k1", market_value=90.0, is_keeper=True), value("a", market_value=100.0)),
        keeper_owners={"k1": "AJ"},
        prices={"k1": 150},
        market=market(k1=90.0),
    )

    assert cheap.as_loaded.keeper_surplus > 0 and cheap.as_loaded.keeper_inflation > 1.0
    assert dear.as_loaded.keeper_surplus < 0 and dear.as_loaded.keeper_inflation < 1.0


def test_inflation_does_not_move_when_only_the_roster_size_changes():
    """The bug the old discretionary-ratio definition had, pinned so it cannot come back.

    Same money, same keepers, same book value; a bigger draft. No price has changed, so the
    structural inflation figure must not move either.
    """
    players = (value("k1", market_value=40.0, is_keeper=True), value("a", market_value=60.0))
    small = keeper_board(
        board(*players), keeper_owners={"k1": "AJ"}, prices={"k1": 30}, market=market(k1=40.0)
    )
    padded = board(*players, *(value(f"x{i}", market_value=0.0) for i in range(20)))
    large = keeper_board(
        padded, keeper_owners={"k1": "AJ"}, prices={"k1": 30}, market=market(k1=40.0)
    )

    assert small.as_loaded.keeper_inflation == large.as_loaded.keeper_inflation


# --------------------------------------------------------------- the two scenarios


def test_the_rule_scenario_prices_every_keeper_at_seventy_five_percent():
    """floor(0.75 * 40) == 30 and floor(0.75 * 21) == 15. Both checked, not just the round one."""
    priced = board(
        value("k1", market_value=40.0, is_keeper=True),
        value("k2", market_value=21.0, is_keeper=True),
        value("a", market_value=60.0),
    )

    result = keeper_board(
        priced,
        keeper_owners={"k1": "AJ", "k2": "Jake"},
        prices={"k1": 40, "k2": 21},
        market=market(k1=40.0, k2=21.0),
    )

    assert {line.player_id: line.rule_price for line in result.lines} == {"k1": 30, "k2": 15}
    assert result.under_rule.keeper_spend == 45
    assert result.as_loaded.keeper_spend == 61


def test_both_scenarios_are_carried_because_they_describe_different_auctions():
    """Prices at book vs prices under the rule are two different nights in the same room."""
    priced = board(value("k1", market_value=80.0, is_keeper=True), value("a", market_value=100.0))

    result = keeper_board(
        priced, keeper_owners={"k1": "AJ"}, prices={"k1": 80}, market=market(k1=80.0)
    )

    assert result.as_loaded.keeper_spend == 80  # paid full book
    assert result.under_rule.keeper_spend == 60  # floor(0.75 * 80)
    assert result.divergence == 20
    assert result.as_loaded.keeper_inflation < result.under_rule.keeper_inflation


def test_the_rule_price_is_clamped_so_a_dollar_keeper_never_becomes_free():
    """floor(0.75 * 1) == 0, and a $0 keeper breaks money conservation and the max-bid reserve."""
    priced = board(value("k1", market_value=1.0, is_keeper=True), value("a", market_value=60.0))
    result = keeper_board(
        priced, keeper_owners={"k1": "AJ"}, prices={"k1": 1}, market=market(k1=1.0)
    )
    assert result.lines[0].rule_price == 1


# ------------------------------------------------- a partial sum is a wrong answer


def test_a_missing_price_refuses_to_produce_an_inflation_figure():
    """This is the whole point of the refusal.

    One unknown price understates ΣK, which overstates live money, which inflates every price
    on the board -- and the result looks entirely reasonable. A number that is wrong in the
    direction of looking fine is worse than an exception.
    """
    priced = board(
        value("k1", market_value=40.0, is_keeper=True),
        value("k2", market_value=40.0, is_keeper=True),
        value("a", market_value=60.0),
    )

    result = keeper_board(
        priced,
        keeper_owners={"k1": "AJ", "k2": "Jake"},
        prices={"k1": 30},
        market=market(k1=40.0, k2=40.0),
    )

    assert result.as_loaded.keeper_spend == 30  # readable, and honestly a partial sum
    assert result.as_loaded.complete is False
    assert result.as_loaded.missing == 1
    for figure in ("total_live_money", "keeper_surplus", "keeper_inflation"):
        with pytest.raises(IncompleteScenario, match=figure):
            getattr(result.as_loaded, figure)


def test_the_partial_sum_would_have_looked_completely_reasonable():
    """Proof the refusal is load-bearing rather than defensive decoration.

    With one $40 keeper's price missing, the naive figure is 170/60 = 2.83x. The true figure
    with both prices loaded is 140/60 = 2.33x. Neither looks wrong; they are 21% apart.
    """
    priced = board(
        value("k1", market_value=40.0, is_keeper=True),
        value("k2", market_value=40.0, is_keeper=True),
        value("a", market_value=60.0),
    )
    complete = keeper_board(
        priced,
        keeper_owners={"k1": "AJ", "k2": "Jake"},
        prices={"k1": 30, "k2": 30},
        market=market(k1=40.0, k2=40.0),
    )

    assert complete.as_loaded.keeper_inflation == pytest.approx(140 / 60, abs=1e-4)
    naive = (TOTAL_BUDGET - 30) / 60
    assert naive == pytest.approx(170 / 60, abs=1e-4)
    assert abs(naive - complete.as_loaded.keeper_inflation) > 0.4


def test_divergence_between_two_partial_sums_is_not_reported_as_a_small_disagreement():
    priced = board(
        value("k1", market_value=40.0, is_keeper=True),
        value("k2", market_value=40.0, is_keeper=True),
        value("a", market_value=60.0),
    )
    result = keeper_board(
        priced,
        keeper_owners={"k1": "AJ", "k2": "Jake"},
        prices={"k1": 30},
        market=market(k1=40.0, k2=40.0),
    )
    assert result.divergence is None


def test_no_auction_values_means_no_rule_scenario_rather_than_a_zero_one():
    """Until values arrive, the rule cannot be applied. Reporting ΣK of $0 would be a lie."""
    priced = board(value("k1", market_value=40.0, is_keeper=True), value("a", market_value=60.0))
    result = keeper_board(
        priced,
        keeper_owners={"k1": "AJ"},
        prices={"k1": 30},
        market=MarketValues(source="none", values={}),
    )

    assert result.lines[0].rule_price is None
    assert result.under_rule.complete is False
    with pytest.raises(IncompleteScenario):
        _ = result.under_rule.keeper_inflation


# ------------------------------------------------------------ reconciliation alerts


def test_a_loaded_price_that_is_not_what_the_rule_produces_is_surfaced():
    """Charter §2. A keeper mispriced by $20 moves that team's whole evening."""
    priced = board(value("k1", market_value=80.0, is_keeper=True), value("a", market_value=60.0))

    result = keeper_board(
        priced, keeper_owners={"k1": "AJ"}, prices={"k1": 80}, market=market(k1=80.0)
    )

    (line,) = result.lines
    assert line.rule_price == 60
    assert line.price_divergence == 20
    assert line.diverged
    assert any("rule implies $60" in alert and "+20" in alert for alert in result.alerts())


def test_a_price_within_rounding_of_the_rule_is_not_flagged():
    """Rounding and a stale auction value both land here; flagging them trains the user to
    ignore the alerts, which is worse than not having them."""
    priced = board(value("k1", market_value=80.0, is_keeper=True), value("a", market_value=60.0))
    result = keeper_board(
        priced,
        keeper_owners={"k1": "AJ"},
        prices={"k1": 60 + PRICE_DIVERGENCE_DOLLARS - 1},
        market=market(k1=80.0),
    )
    assert result.lines[0].diverged is False
    assert not [alert for alert in result.alerts() if alert.startswith("AJ:")]
    # The league-level total still reports its $2 gap. That is a different statement -- twenty
    # sub-threshold divergences in the same direction are a real shift in the money.
    assert any(alert.startswith("loaded keeper spend is $+2") for alert in result.alerts())


def test_alerts_are_ordered_worst_divergence_first():
    priced = board(
        value("k1", market_value=80.0, is_keeper=True),
        value("k2", market_value=80.0, is_keeper=True),
        value("a", market_value=60.0),
    )
    result = keeper_board(
        priced,
        keeper_owners={"k1": "AJ", "k2": "Jake"},
        prices={"k1": 70, "k2": 100},
        market=market(k1=80.0, k2=80.0),
    )
    divergences = [alert for alert in result.alerts() if "rule implies" in alert]
    assert "+40" in divergences[0] and "+10" in divergences[1]


def test_an_estimated_market_source_badges_the_whole_board():
    """A rule-implied price computed from an ADP rank transfer is not a rule-implied price."""
    priced = board(value("k1", market_value=40.0, is_keeper=True), value("a", market_value=60.0))
    result = keeper_board(
        priced,
        keeper_owners={"k1": "AJ"},
        prices={"k1": 30},
        market=MarketValues(source="adp_rank_transfer", values={"k1": 40.0}),
    )

    assert result.market_is_estimate
    assert any(
        "every rule-implied figure on this board is an estimate" in a for a in result.alerts()
    )


def test_a_real_market_source_is_not_badged():
    priced = board(value("k1", market_value=40.0, is_keeper=True), value("a", market_value=60.0))
    result = keeper_board(
        priced, keeper_owners={"k1": "AJ"}, prices={"k1": 30}, market=market(k1=40.0)
    )
    assert result.market_is_estimate is False
    assert not [a for a in result.alerts() if "estimate" in a]


def test_keepers_with_no_loaded_price_are_named_not_counted_silently():
    priced = board(
        value("k1", market_value=40.0, is_keeper=True),
        value("k2", market_value=40.0, is_keeper=True),
        value("a", market_value=60.0),
    )
    result = keeper_board(
        priced,
        keeper_owners={"k1": "AJ", "k2": "Jake"},
        prices={"k1": 30},
        market=market(k1=40.0, k2=40.0),
    )
    assert any("no loaded retention price" in a and "RBk2" in a for a in result.alerts())


# ---------------------------------------------------------------- resolution errors


def test_a_keeper_missing_from_the_priced_board_raises_rather_than_being_skipped():
    """Skipping would understate ΣK, which scales every price in the model."""
    priced = board(value("a", market_value=60.0))
    with pytest.raises(KeyError, match="not on the priced board"):
        keeper_board(
            priced, keeper_owners={"ghost": "AJ"}, market=MarketValues(source="x", values={})
        )


def test_a_player_priced_as_available_is_not_silently_accepted_as_a_keeper():
    """The two sides of the keeper adjustment must agree, or supply and demand have diverged."""
    priced = board(value("a", market_value=60.0))
    with pytest.raises(KeyError, match="priced as available"):
        keeper_board(priced, keeper_owners={"a": "AJ"}, market=MarketValues(source="x", values={}))


def test_lines_group_by_team_and_sort_by_book_value_within_it():
    priced = board(
        value("k1", market_value=10.0, is_keeper=True),
        value("k2", market_value=90.0, is_keeper=True),
        value("a", market_value=60.0),
    )
    result = keeper_board(
        priced, keeper_owners={"k1": "AJ", "k2": "AJ"}, market=MarketValues(source="x", values={})
    )
    assert [line.player_id for line in result.by_team()["AJ"]] == ["k2", "k1"]


# ------------------------------------------------------------------ line-level maths


def test_a_line_with_no_price_reports_none_rather_than_zero_surplus():
    line = KeeperLine(owner="AJ", slot=1, player_id="k", name="RBk", position="RB", book_value=40.0)
    assert line.surplus is None
    assert line.rule_surplus is None
    assert line.price_divergence is None
    assert line.diverged is False


def test_rule_surplus_uses_the_rule_price_not_the_loaded_one():
    line = KeeperLine(
        owner="AJ",
        slot=1,
        player_id="k",
        name="RBk",
        position="RB",
        book_value=40.0,
        market_value=40.0,
        price_paid=35,
        rule_price=30,
    )
    assert line.surplus == 5.0
    assert line.rule_surplus == 10.0
    assert line.price_divergence == 5


def test_an_empty_keeper_slate_is_complete_rather_than_incomplete():
    """Zero keepers is a coherent state -- a redraft league -- and must not raise."""
    scenario = Scenario(
        label="empty",
        keeper_spend=0,
        total_budget=TOTAL_BUDGET,
        available_book_value=200.0,
        keeper_book_value=0.0,
        complete=True,
    )
    assert scenario.total_live_money == TOTAL_BUDGET
    assert scenario.keeper_inflation == 1.0


def test_a_board_with_no_available_book_value_does_not_divide_by_zero():
    scenario = Scenario(
        label="all kept",
        keeper_spend=100,
        total_budget=TOTAL_BUDGET,
        available_book_value=0.0,
        keeper_book_value=200.0,
        complete=True,
    )
    assert scenario.keeper_inflation == 1.0
