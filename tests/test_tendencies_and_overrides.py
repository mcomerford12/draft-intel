"""DI-037 tendency profiles and DI-038 value overrides.

No player name is hardcoded; synthetic players are named by position and index.
"""

from __future__ import annotations

import pytest

from draft_intel.domain.ledger import fold
from draft_intel.models import DerivedState, PickObserved, PickSnapshot
from draft_intel.quant.market import MarketValues
from draft_intel.quant.overrides import (
    PlayerOverride,
    apply_overrides,
    renormalise,
)
from draft_intel.quant.skew import SkewBoard, skew_board
from draft_intel.quant.tendencies import MIN_PROFILE_PICKS, MIN_SLOPE_PICKS, _gini, profiles
from draft_intel.quant.valuation import PlayerValue

SLOTS = range(1, 4)


def value(
    player_id: str, *, baseline: float, position: str = "RB", in_live: bool = True
) -> PlayerValue:
    return PlayerValue(
        player_id=player_id,
        name=f"{position}{player_id}",
        position=position,
        team=None,
        points=100.0,
        vorp=baseline,
        market_value=baseline,
        vorp_live=baseline,
        baseline_value=baseline,
        is_keeper=False,
        in_pool_full=True,
        in_pool_live=in_live,
    )


def state_from(*picks: tuple[int, str, int, int, bool]) -> DerivedState:
    return fold(
        [
            PickObserved(
                seq=i,
                pick=PickSnapshot(pick_no=pn, player_id=pid, slot=slot, amount=amt, is_keeper=keep),
            )
            for i, (pn, pid, slot, amt, keep) in enumerate(picks, start=1)
        ],
        slots=SLOTS,
    )


def par_skew(state: DerivedState, board: dict[str, PlayerValue]) -> SkewBoard:
    """Skew on a board sized so inflation starts at exactly 1.0 and barely moves."""
    full = {
        **board,
        **{f"pad{i}": value(f"pad{i}", baseline=5.0, position="TE") for i in range(200)},
    }
    return skew_board(
        state,
        full,
        MarketValues(source="none", values={}),
        total_budget=int(5.0 * len(full)),
        total_slots=len(full),
        keeper_spend=0,
        keeper_slots=0,
    )


# ============================================================ DI-037 tendencies


def test_a_manager_with_too_few_picks_is_not_profiled():
    """Two picks is a history, not a tendency, and a confident read off four picks is worse
    than one that says it does not know yet -- the user acts on this with money."""
    board = {f"r{i}": value(f"r{i}", baseline=5.0) for i in range(2)}
    state = state_from(*[(i, f"r{i}", 2, 5, False) for i in range(2)])

    profile = profiles(par_skew(state, board))[2]

    assert profile.is_reportable is False
    assert profile.gini is None
    assert profile.positional_bias == ()
    assert "too few to profile" in profile.describe()[0]


def test_the_aggression_slope_is_fitted_on_competitive_seq_not_pick_no():
    """ADR-0001 D3, and this is where it bites hardest.

    In Case B the twenty ceremonial keeper picks hold pick_no 1-20 and shift every competitive
    pick by 20. A slope fitted against pick_no is a different slope in the two cases, so the
    blocking equivalence gate -- which names tendency profiles explicitly -- cannot pass.
    """
    board = {f"r{i}": value(f"r{i}", baseline=5.0) for i in range(8)}

    # The same eight competitive picks, in the same order, at two different pick_no offsets --
    # which is exactly what Case A and Case B differ by once the ceremonial keeper picks have
    # taken the first twenty numbers. The dense competitive index is identical in both, so
    # every figure fitted against it must be too.
    unshifted = profiles(
        par_skew(state_from(*[(i + 1, f"r{i}", 2, 5 + i * 3, False) for i in range(8)]), board)
    )[2]
    shifted = profiles(
        par_skew(state_from(*[(i + 21, f"r{i}", 2, 5 + i * 3, False) for i in range(8)]), board)
    )[2]

    assert unshifted.aggression_slope is not None
    assert unshifted.aggression_slope == shifted.aggression_slope
    assert unshifted.model_dump() == shifted.model_dump(), "every figure, not just the slope"


def test_a_manager_who_pays_more_as_the_night_runs_has_a_positive_slope():
    board = {f"r{i}": value(f"r{i}", baseline=5.0) for i in range(8)}
    state = state_from(*[(i, f"r{i}", 2, 2 + i * 4, False) for i in range(8)])

    profile = profiles(par_skew(state, board))[2]

    assert profile.aggression_slope is not None and profile.aggression_slope > 0
    assert profile.early_mean_skew is not None and profile.late_mean_skew is not None
    assert profile.late_mean_skew > profile.early_mean_skew
    assert "heats up" in " ".join(profile.describe())


def test_the_slope_is_withheld_below_its_own_sample_floor():
    """A slope needs more than a ratio does: two points always fit a line perfectly."""
    board = {f"r{i}": value(f"r{i}", baseline=5.0) for i in range(MIN_SLOPE_PICKS - 1)}
    state = state_from(*[(i, f"r{i}", 2, 5, False) for i in range(MIN_SLOPE_PICKS - 1)])
    profile = profiles(par_skew(state, board))[2]
    assert profile.picks >= MIN_PROFILE_PICKS
    assert profile.aggression_slope is None


def test_stars_and_scrubs_shows_a_higher_gini_than_a_balanced_roster():
    board = {f"r{i}": value(f"r{i}", baseline=5.0) for i in range(12)}
    spread = state_from(*[(i, f"r{i}", 2, 10, False) for i in range(6)])
    lumpy = state_from(*[(i, f"r{i}", 2, 55 if i == 0 else 1, False) for i in range(6)])

    balanced = profiles(par_skew(spread, board))[2]
    concentrated = profiles(par_skew(lumpy, board))[2]

    assert balanced.gini == 0.0
    assert concentrated.gini is not None and concentrated.gini > 0.6
    assert "stars-and-scrubs" in " ".join(concentrated.describe())
    assert "balanced" in " ".join(balanced.describe())


def test_gini_is_none_rather_than_zero_when_there_is_no_spend():
    """Zero would read as "perfectly balanced", which is the opposite of "no information"."""
    assert _gini([]) is None
    assert _gini([0, 0, 0]) is None
    assert _gini([10, 10, 10]) == 0.0


def test_a_manager_who_pays_up_during_a_run_reads_as_chasing():
    """A run is measured across the whole room: what a manager reacts to is the room taking
    four running backs in a row, whoever took them."""
    board = {
        **{f"r{i}": value(f"r{i}", baseline=5.0, position="RB") for i in range(4)},
        **{f"q{i}": value(f"q{i}", baseline=5.0, position="QB") for i in range(4)},
    }
    state = state_from(
        (1, "r0", 1, 5, False),
        (2, "r1", 3, 5, False),
        (3, "r2", 2, 40, False),  # our manager, paying up mid-run
        # Then a stretch with no run of its own: the positions alternate, so these picks are
        # the baseline the run pick is compared against. Four consecutive QBs here would be a
        # second run, every pick would be "during a run", and the comparison would be with
        # itself -- which is how the first version of this test measured exactly zero.
        (4, "q0", 2, 1, False),
        (5, "r3", 2, 1, False),
        (6, "q1", 2, 1, False),
        (7, "q2", 2, 1, False),
    )

    profile = profiles(par_skew(state, board))[2]

    assert profile.run_picks >= 1
    assert profile.run_picks < profile.picks, "or the comparison is with itself"
    assert profile.chases_runs is not None and profile.chases_runs > 0
    assert "chases positional runs" in " ".join(profile.describe())


def test_no_picks_during_a_run_is_reported_as_unknown_not_as_discipline():
    board = {f"q{i}": value(f"q{i}", baseline=5.0, position="QB") for i in range(6)}
    state = state_from(*[(i, f"q{i}", 2, 5, False) for i in range(6)])
    profile = profiles(par_skew(state, board))[2]
    # Every pick is a QB, so every pick IS in a run; invert the case with mixed positions.
    mixed_board = {
        **{f"q{i}": value(f"q{i}", baseline=5.0, position="QB") for i in range(3)},
        **{f"r{i}": value(f"r{i}", baseline=5.0, position="RB") for i in range(3)},
    }
    mixed = state_from(
        (1, "q0", 2, 5, False),
        (2, "r0", 2, 5, False),
        (3, "q1", 2, 5, False),
        (4, "r1", 2, 5, False),
        (5, "q2", 2, 5, False),
        (6, "r2", 2, 5, False),
    )
    assert profile.run_picks > 0
    assert profiles(par_skew(mixed, mixed_board))[2].chases_runs is None


def test_positional_bias_reports_where_the_money_went():
    board = {
        **{f"r{i}": value(f"r{i}", baseline=5.0, position="RB") for i in range(3)},
        **{f"q{i}": value(f"q{i}", baseline=5.0, position="QB") for i in range(3)},
    }
    state = state_from(
        *[(i, f"r{i}", 2, 30, False) for i in range(3)],
        *[(10 + i, f"q{i}", 2, 1, False) for i in range(3)],
    )

    profile = profiles(par_skew(state, board))[2]
    bias = {b.position: b for b in profile.positional_bias}

    assert bias["RB"].spent == 90
    assert bias["QB"].spent == 3
    assert bias["RB"].share_of_spend == pytest.approx(90 / 93, abs=1e-3)


def test_nomination_behaviour_is_named_as_unmeasurable_rather_than_approximated():
    """The charter asks for it. Sleeper's picks feed records who WON each player and carries no
    field anywhere for who put them up, so any number here would be invented."""
    board = {f"r{i}": value(f"r{i}", baseline=5.0) for i in range(6)}
    state = state_from(*[(i, f"r{i}", 2, 5, False) for i in range(6)])
    profile = profiles(par_skew(state, board))[2]
    assert any("nomination behaviour" in item for item in profile.unavailable)
    assert any("not measurable" in line for line in profile.describe())


def test_profiles_are_keyed_on_draft_slot_not_owner_name():
    board = {f"r{i}": value(f"r{i}", baseline=5.0) for i in range(12)}
    state = state_from(
        *[(i, f"r{i}", 2, 40, False) for i in range(6)],
        *[(10 + i, f"r{6 + i}", 3, 1, False) for i in range(6)],
    )
    result = profiles(par_skew(state, board), owners={})
    assert set(result) == {2, 3}
    assert result[2].owner == "slot 2" and result[3].owner == "slot 3"
    assert result[2].spent != result[3].spent


# ============================================================= DI-038 overrides


def board_of(*players: PlayerValue) -> list[PlayerValue]:
    return list(players)


def test_an_override_keeps_the_model_number_alongside_the_users():
    """§4.8: never let the user forget they are looking at a number they typed. A type that can
    lose the original makes that a matter of discipline downstream rather than a property."""
    board = board_of(value("a", baseline=10.0))
    result = apply_overrides(
        board,
        total_live_money=10,
        players={"a": PlayerOverride(baseline_value=25.0, note="he is fine, I watched him")},
    )

    (row,) = result.values
    assert row.baseline_value == 25.0
    assert row.player.baseline_value == 10.0
    assert row.deltas()["baseline_value"] == 15.0
    assert row.sources["baseline_value"] == "manual"
    assert "10.0 -> 25.0 (manual)" in row.describe()
    assert "he is fine" in row.describe()


def test_a_positional_multiplier_scales_a_whole_position_at_once():
    """§4.8 calls this the highest-leverage knob in a live draft, because positional mispricing
    is recognised wholesale rather than one player at a time."""
    board = board_of(
        value("t1", baseline=10.0, position="TE"),
        value("t2", baseline=20.0, position="TE"),
        value("r1", baseline=10.0, position="RB"),
    )
    result = apply_overrides(board, total_live_money=40, positional_multipliers={"TE": 1.15})
    by_id = {v.player_id: v for v in result.values}

    assert by_id["t1"].baseline_value == 11.5
    assert by_id["t2"].baseline_value == 23.0
    assert by_id["r1"].baseline_value == 10.0, "other positions untouched"
    assert by_id["t1"].sources["baseline_value"] == "multiplier"


def test_an_explicit_override_beats_the_multiplier_rather_than_being_scaled_by_it():
    """§4.8's precedence rule. Scaling a number the user typed means the user did not win."""
    board = board_of(value("t1", baseline=10.0, position="TE"))
    result = apply_overrides(
        board,
        total_live_money=10,
        positional_multipliers={"TE": 2.0},
        players={"t1": PlayerOverride(baseline_value=30.0)},
    )
    assert result.values[0].baseline_value == 30.0, "not 60"


def test_a_blacklisted_player_is_worth_nothing_whatever_anybody_typed():
    """The instruction is "never bid", not "bid this much"."""
    board = board_of(value("a", baseline=50.0))
    result = apply_overrides(
        board,
        total_live_money=50,
        players={"a": PlayerOverride(baseline_value=99.0, blacklisted=True)},
    )
    assert result.values[0].baseline_value == 0.0
    assert result.values[0].market_value == 0.0
    assert "BLACKLISTED" in result.values[0].describe()


def test_the_blacklist_can_also_be_supplied_as_a_bare_set_of_ids():
    board = board_of(value("a", baseline=50.0))
    result = apply_overrides(board, total_live_money=50, blacklist=frozenset({"a"}))
    assert result.values[0].blacklisted
    assert result.values[0].baseline_value == 0.0


def test_values_are_not_renormalised_and_the_deviation_is_shown():
    """§4.8: one edit must not ripple through every other price. The board stops reconciling,
    and that fact is displayed rather than smoothed away."""
    board = board_of(value("a", baseline=10.0), value("b", baseline=10.0))
    result = apply_overrides(
        board, total_live_money=20, players={"a": PlayerOverride(baseline_value=30.0)}
    )

    assert result.values[1].baseline_value == 10.0, "the other player did not move"
    assert result.sum_baseline_after == 40.0
    assert result.deviation == 20.0
    assert result.moved == 20.0
    banner = result.banner()
    assert banner is not None and "NOT renormalised" in banner


def test_an_untouched_board_raises_no_banner():
    board = board_of(value("a", baseline=10.0))
    assert apply_overrides(board, total_live_money=10).banner() is None


def test_renormalisation_is_a_preview_and_applies_nothing():
    """§4.8 requires it to be explicit, opt-in, and previewed."""
    board = board_of(value("a", baseline=10.0), value("b", baseline=10.0))
    result = apply_overrides(
        board, total_live_money=20, players={"a": PlayerOverride(baseline_value=30.0)}
    )

    preview = renormalise(result)

    assert preview is not None
    assert preview.factor == pytest.approx(0.5)
    assert preview.after == pytest.approx(20.0)
    assert result.values[0].baseline_value == 30.0, "the board itself is unchanged"
    assert "would scale" in preview.describe()


def test_a_board_that_already_reconciles_offers_no_renormalisation():
    """Returning a factor of 1.0 would let a caller render "renormalise (no change)" as an
    available action."""
    board = board_of(value("a", baseline=10.0), value("b", baseline=10.0))
    assert renormalise(apply_overrides(board, total_live_money=20)) is None


def test_players_outside_the_live_pool_do_not_count_toward_the_deviation():
    board = board_of(value("a", baseline=10.0), value("k", baseline=99.0, in_live=False))
    result = apply_overrides(board, total_live_money=10)
    assert result.sum_baseline_after == 10.0
    assert result.deviation == 0.0


def test_an_override_naming_nobody_is_an_error_not_a_silent_no_op():
    """Silently dropping it leaves the user believing a correction was applied."""
    with pytest.raises(KeyError, match="not on the board"):
        apply_overrides(
            board_of(value("a", baseline=10.0)),
            total_live_money=10,
            players={"ghost": PlayerOverride(baseline_value=5.0)},
        )


@pytest.mark.parametrize("factor", [0.0, -1.0])
def test_a_non_positive_multiplier_is_refused(factor):
    """A negative multiplier makes every price at that position negative, which passes silently
    into the optimizer and inverts its preferences."""
    with pytest.raises(ValueError, match="use the blacklist"):
        apply_overrides(
            board_of(value("t1", baseline=10.0, position="TE")),
            total_live_money=10,
            positional_multipliers={"TE": factor},
        )


def test_points_can_be_overridden_independently_of_price():
    board = board_of(value("a", baseline=10.0))
    result = apply_overrides(
        board, total_live_money=10, players={"a": PlayerOverride(points=250.0)}
    )
    assert result.values[0].points == 250.0
    assert result.values[0].baseline_value == 10.0
    assert result.values[0].sources["points"] == "manual"
