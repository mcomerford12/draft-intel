"""DI-036 — walk-away curves. No player name is hardcoded."""

from __future__ import annotations

import pytest

from draft_intel.quant import walkaway
from draft_intel.quant.optimizer import Candidate
from draft_intel.quant.slots import FLEX
from draft_intel.quant.walkaway import walkaway_board, walkaway_curve


def player(pid: str, position: str, points: float, price: int) -> Candidate:
    return Candidate(
        player_id=pid,
        name=f"{position}-{pid}",
        position=position,
        points=points,
        vorp=points,
        price=price,
    )


def board() -> list[Candidate]:
    """One clear star and a field of interchangeable alternatives."""
    return [
        player("star", "RB", 200.0, 1),
        *[player(f"r{i}", "RB", 100.0 - i, 1) for i in range(6)],
    ]


STARTERS = {"RB": 1}


# ------------------------------------------------------------------- the curve


def test_the_curve_falls_as_the_price_rises():
    """Paying more for the same player cannot leave a better team: every roster affordable at a
    higher price is also affordable at a lower one."""
    curve = walkaway_curve(
        board(), board()[0], budget=12, slots=3, starters=STARTERS, bench_weight=0.0
    )
    assert curve.monotone
    deltas = [p.delta for p in curve.points if p.feasible]
    assert deltas == sorted(deltas, reverse=True)


def test_the_walk_away_price_is_the_highest_price_still_worth_paying():
    """Not the first non-positive price, and not a fitted crossing point. The user needs "the
    most I should pay", which has to be a price they would actually bid."""
    curve = walkaway_curve(
        board(), board()[0], budget=12, slots=3, starters=STARTERS, bench_weight=0.0
    )
    assert curve.walk_away_price is not None
    at_price = curve.delta_at(curve.walk_away_price)
    assert at_price is not None and at_price > 0
    above = curve.delta_at(curve.walk_away_price + 1)
    assert above is None or above <= 0


def test_a_player_who_improves_nothing_has_no_walk_away_price():
    """A replacement-level player behind a better one at the same position, with λ=0."""
    pool = [player("best", "RB", 200.0, 1), *[player(f"r{i}", "RB", 10.0, 1) for i in range(5)]]
    curve = walkaway_curve(pool, pool[-1], budget=10, slots=2, starters=STARTERS, bench_weight=0.0)
    assert curve.walk_away_price is None
    assert "not worth buying at any price" in curve.describe()


def test_the_curve_defaults_to_every_price_the_user_could_legally_bid():
    """$12 across 3 slots means the most biddable is $10, reserving $1 for each other slot."""
    curve = walkaway_curve(board(), board()[0], budget=12, slots=3, starters=STARTERS)
    assert [p.price for p in curve.points] == list(range(1, 11))


def test_a_price_beyond_the_budget_is_infeasible_rather_than_a_number():
    curve = walkaway_curve(
        board(), board()[0], budget=12, slots=3, starters=STARTERS, prices=[5, 50]
    )
    assert curve.points[0].feasible
    assert curve.points[1].feasible is False
    assert curve.points[1].delta == float("-inf")


def test_an_infeasible_tail_does_not_make_the_curve_look_broken():
    """Infeasible is the absence of a value, not a low one. Threading -inf through the
    monotonicity comparison would report every curve that runs off the budget as broken."""
    curve = walkaway_curve(
        board(), board()[0], budget=12, slots=3, starters=STARTERS, prices=[1, 50, 5]
    )
    assert curve.monotone


def test_the_y_axis_is_delta_starting_points_as_the_charter_specifies():
    curve = walkaway_curve(
        board(), board()[0], budget=12, slots=3, starters=STARTERS, bench_weight=0.0, prices=[1]
    )
    # Buying the 200-point star instead of the best alternative (100) gains 100 starting points.
    assert curve.points[0].starting_points_delta == 100.0


# ------------------------------------------------------------- the excluded arm


def test_the_baseline_is_the_best_team_without_this_player():
    """Every delta is measured against it, so it has to be the real alternative rather than
    an empty roster."""
    pool = board()
    curve = walkaway_curve(pool, pool[0], budget=12, slots=3, starters=STARTERS, bench_weight=0.0)
    # Without the star, the best starter available scores 100.
    assert curve.baseline_objective == pytest.approx(100.0)


def test_the_excluded_arm_does_not_depend_on_the_price():
    """It is solved once for the whole curve. A player you are not buying costs nothing at
    every price, so recomputing it per point doubles the work for an unchanging answer."""
    pool = board()
    short = walkaway_curve(pool, pool[0], budget=12, slots=3, starters=STARTERS, prices=[1])
    long = walkaway_curve(pool, pool[0], budget=12, slots=3, starters=STARTERS, prices=[1, 2, 3])
    assert short.baseline_objective == long.baseline_objective


def test_the_forced_arm_never_buys_the_player_twice():
    """The forced copy is priced at the hypothetical bid; the board copy must be excluded, or
    the optimizer can buy both and the delta is measured against a roster that cannot exist."""
    pool = board()
    curve = walkaway_curve(
        pool, pool[0], budget=12, slots=3, starters=STARTERS, bench_weight=0.2, prices=[3]
    )
    assert curve.points[0].feasible
    assert curve.points[0].delta > 0


# ---------------------------------------------------------------------- guards


def test_curving_a_player_who_is_not_on_the_board_is_an_error():
    """Otherwise they are silently measured against a pool that still contains them."""
    with pytest.raises(ValueError, match="not on the board"):
        walkaway_curve(
            board(), player("ghost", "RB", 50.0, 1), budget=10, slots=2, starters=STARTERS
        )


def test_at_lambda_zero_the_walk_away_price_is_just_the_budget_ceiling():
    """ADR-0004's complaint, made concrete.

    With the bench worth nothing, money held back is worth nothing either, so the delta is flat
    all the way up and the curve only ever "crosses" where the budget runs out. The advice is
    always "bid everything you legally can", which is how the user ends the night at $0 with no
    injury cover.
    """
    pool = [
        player("star", "RB", 200.0, 1),
        *[player(f"good{i}", "RB", 150.0, 8) for i in range(3)],
        *[player(f"scrub{i}", "RB", 10.0, 1) for i in range(4)],
    ]
    lean = walkaway_curve(pool, pool[0], budget=20, slots=3, starters=STARTERS, bench_weight=0.0)

    assert lean.walk_away_price == 18, "budget 20 across 3 slots: the ceiling, nothing else"
    deltas = [p.delta for p in lean.points if p.feasible]
    assert len(set(deltas)) == 1, "flat, because the money saved buys nothing worth having"


def test_the_bench_weight_moves_the_walk_away_number():
    """ADR-0004: λ is a judgement coefficient, and the UI is required to say that moving the
    slider moves the number. Here is the evidence that it does -- on the same board as above."""
    pool = [
        player("star", "RB", 200.0, 1),
        *[player(f"good{i}", "RB", 150.0, 8) for i in range(3)],
        *[player(f"scrub{i}", "RB", 10.0, 1) for i in range(4)],
    ]
    lean = walkaway_curve(pool, pool[0], budget=20, slots=3, starters=STARTERS, bench_weight=0.0)
    fat = walkaway_curve(pool, pool[0], budget=20, slots=3, starters=STARTERS, bench_weight=1.0)

    assert fat.walk_away_price is not None
    assert lean.walk_away_price is not None
    assert fat.walk_away_price < lean.walk_away_price, (
        "valuing the bench holds money back, which lowers what the star is worth"
    )


# ------------------------------------------------------------------ precompute


def test_the_board_precomputes_curves_for_the_most_valuable_players_only():
    """ADR-0003 wants the live path to be a lookup. A curve costs two solves per price point,
    so covering every player at every dollar does not fit between two picks."""
    curves = walkaway_board(board(), budget=12, slots=3, starters=STARTERS, top=3, prices=[1, 2])
    assert len(curves) == 3
    assert curves[0].player_id == "star", "ranked by projected points"
    assert all(len(c.points) == 2 for c in curves)


def test_a_precomputed_board_is_keyed_so_the_live_path_is_a_lookup():
    curves = {
        c.player_id: c
        for c in walkaway_board(board(), budget=12, slots=3, starters=STARTERS, top=2, prices=[1])
    }
    assert curves["star"].delta_at(1) is not None
    assert curves["star"].delta_at(999) is None


def test_flex_slots_are_honoured_in_the_curve():
    pool = [
        player("star", "RB", 200.0, 1),
        player("w1", "WR", 190.0, 1),
        *[player(f"r{i}", "RB", 50.0, 1) for i in range(4)],
    ]
    curve = walkaway_curve(
        pool,
        pool[0],
        budget=10,
        slots=3,
        starters={"RB": 1, "WR": 1, FLEX: 1},
        bench_weight=0.0,
        prices=[1],
    )
    assert curve.points[0].feasible
    assert curve.points[0].delta > 0


def test_the_precompute_ranks_by_vorp_not_raw_points():
    """Raw points are not comparable across positions.

    In a 2QB league a quarterback outscores every running back on the board, so ranking by
    points returns a target list of twelve quarterbacks and nothing else -- which is exactly
    what the first `make prep` run printed. VORP is measured against each position's own
    replacement level, which is what makes it the right axis for "worth bidding on".
    """
    pool = [
        Candidate(player_id="qb", name="QB-qb", position="QB", points=320.0, vorp=40.0, price=1),
        Candidate(player_id="rb", name="RB-rb", position="RB", points=250.0, vorp=140.0, price=1),
        *[
            Candidate(
                player_id=f"f{i}", name=f"RB-f{i}", position="RB", points=50.0, vorp=5.0, price=1
            )
            for i in range(4)
        ],
    ]
    curves = walkaway_board(
        pool, budget=10, slots=2, starters={"QB": 1, "RB": 1}, top=1, prices=[1]
    )
    assert [c.player_id for c in curves] == ["rb"]


# ------------------------- review round 2: the crossing must not be the grid's edge


def test_the_walk_away_price_is_independent_of_which_prices_the_curve_samples():
    """The defect: `max(price where delta > 0)` over the *sampled* points cannot tell a genuine
    crossing from a curve still positive at the top of whatever grid was searched.

    On the real board it reported $58 against a true $117 -- a $59 understatement on the number
    §4.7b displays as one enormous digit, under a report line reading "the MOST you should pay".
    A coarse grid also understated by up to $2 inside its own range.
    """
    pool = [player("star", "RB", 500.0, 1), *[player(f"r{i}", "RB", 10.0, 1) for i in range(5)]]

    coarse = walkaway_curve(
        pool, pool[0], budget=60, slots=3, starters=STARTERS, bench_weight=0.0, prices=[1, 5]
    )
    fine = walkaway_curve(pool, pool[0], budget=60, slots=3, starters=STARTERS, bench_weight=0.0)

    assert coarse.walk_away_price == fine.walk_away_price
    assert coarse.walk_away_price is not None
    assert coarse.walk_away_price > max(p.price for p in coarse.points), (
        "the answer is not bounded by the sampled grid"
    )


def test_a_player_worth_buying_at_any_affordable_price_says_so_distinctly():
    """ "The curve never crossed" and "the budget ran out first" read identically off a sampled
    curve and mean different things: one is about the player, the other about the wallet."""
    pool = [player("star", "RB", 5000.0, 1), *[player(f"r{i}", "RB", 1.0, 1) for i in range(5)]]
    curve = walkaway_curve(pool, pool[0], budget=20, slots=3, starters=STARTERS, bench_weight=0.0)

    assert curve.max_legal_bid == 18
    assert curve.walk_away_price == 18
    assert curve.worth_it_at_any_legal_price


def test_a_player_with_a_real_crossing_is_not_flagged_as_budget_bound():
    """λ must be non-zero for a crossing to exist at all: under λ=0 the money saved by walking
    away buys nothing, so the delta is flat and the budget is always the binding constraint.
    That is ADR-0004's complaint, and it is why this fixture prices the alternatives."""
    pool = [player("star", "RB", 200.0, 1), *[player(f"r{i}", "RB", 150.0, 8) for i in range(6)]]
    curve = walkaway_curve(pool, pool[0], budget=40, slots=3, starters=STARTERS, bench_weight=1.0)

    assert curve.walk_away_price is not None
    assert curve.walk_away_price < curve.max_legal_bid
    assert curve.worth_it_at_any_legal_price is False


def test_the_binary_search_finds_the_same_answer_as_an_exhaustive_scan():
    """Exactness rests on monotonicity, which is asserted separately -- so check the two agree
    on a board where the crossing is somewhere in the middle."""
    pool = [player("star", "RB", 300.0, 1), *[player(f"r{i}", "RB", 120.0, 4) for i in range(6)]]
    curve = walkaway_curve(pool, pool[0], budget=40, slots=3, starters=STARTERS, bench_weight=0.2)
    exhaustive = [
        price
        for price in range(1, curve.max_legal_bid + 1)
        if (
            walkaway_curve(
                pool,
                pool[0],
                budget=40,
                slots=3,
                starters=STARTERS,
                bench_weight=0.2,
                prices=[price],
            )
            .points[0]
            .delta
            > 0
        )
    ]
    assert curve.monotone
    assert curve.walk_away_price == (max(exhaustive) if exhaustive else None)


# ------------------------------------------------ mutation escapes from the DI-049 batch


def test_the_monotonicity_flag_is_computed_not_asserted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mutation replacing `monotone=_is_monotone(points)` with `monotone=True` survived the
    whole suite. Every real curve here is monotone -- necessarily, because the optimizer is
    exact -- so no assertion could tell a computed True from a hardcoded one.

    That flag is the tripwire proving the optimizer returned optima, and `make prep` prints
    BROKEN off it. A tripwire wired to a constant is worse than no tripwire, because the page
    then says the curves are sound on a night when they are not. Pinned by forcing the
    predicate to disagree with reality and checking the flag follows it.
    """
    monkeypatch.setattr(walkaway, "_is_monotone", lambda points: False)
    curve = walkaway_curve(board(), board()[0], budget=10, slots=3, starters=STARTERS)
    assert curve.monotone is False, "the flag must come from the check, not from a literal"


def test_the_maximum_legal_bid_never_goes_below_a_dollar():
    """`budget - (slots - 1)` is negative for a user who cannot cover a dollar per open slot.
    Unfloored, `max_legal_bid` reports a negative number and `worth_it_at_any_legal_price`
    becomes trivially true -- at the exact moment the budget is the binding constraint."""
    curve = walkaway_curve(board(), board()[0], budget=2, slots=6, starters=STARTERS)
    assert curve.max_legal_bid == 1, "budget 2 across 6 slots: the floor, not -3"
    assert all(point.price >= 1 for point in curve.points)
