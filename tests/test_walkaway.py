"""DI-036 — walk-away curves. No player name is hardcoded."""

from __future__ import annotations

import pytest

from draft_intel.quant import walkaway
from draft_intel.quant.optimizer import Candidate, Roster
from draft_intel.quant.slots import FLEX
from draft_intel.quant.walkaway import (
    CurvePoint,
    _display_grid,
    _is_monotone,
    walkaway_board,
    walkaway_curve,
)


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


def falling_board() -> list[Candidate]:
    """A star plus a field priced along a real quality ladder.

    `board()` cannot show a curve falling: its alternatives all cost $1, so paying more for the
    star displaces nothing worth having and every delta comes out identical. A constant list is
    `sorted(reverse=True)`, so the assertion below passed against a flat line.
    """
    return [
        player("star", "RB", 200.0, 1),
        player("f1", "RB", 100.0, 10),
        player("f2", "RB", 90.0, 7),
        player("f3", "RB", 80.0, 5),
        player("f4", "RB", 70.0, 3),
        player("f5", "RB", 60.0, 1),
        player("f6", "RB", 50.0, 1),
    ]


def test_the_curve_falls_as_the_price_rises():
    """Paying more for the same player cannot leave a better team: every roster affordable at a
    higher price is also affordable at a lower one. Each extra dollar spent on the star is a
    dollar off the bench, and on a priced field that is a real downgrade."""
    curve = walkaway_curve(
        falling_board(),
        falling_board()[0],
        budget=20,
        slots=3,
        starters={"RB": 1},
        bench_weight=0.2,
    )
    assert curve.monotone
    deltas = [p.delta for p in curve.points if p.feasible]
    assert deltas == sorted(deltas, reverse=True)
    assert len(set(deltas)) > 1, "a flat line satisfies the assertion above without falling"
    assert deltas[0] > deltas[-1]


def test_the_monotonicity_predicate_itself_rejects_a_rising_curve():
    """`monotone` is the tripwire proving the optimizer returned optima -- `make prep` prints
    BROKEN off it. Every curve the optimizer can produce is monotone, so nothing built from the
    optimizer can exercise the False branch, and replacing the whole predicate body with
    `return True` survived the suite. Fed directly instead."""
    falling = [
        CurvePoint(price=1, delta=5.0, starting_points_delta=5.0, feasible=True),
        CurvePoint(price=2, delta=3.0, starting_points_delta=3.0, feasible=True),
    ]
    rising = [
        CurvePoint(price=1, delta=3.0, starting_points_delta=3.0, feasible=True),
        CurvePoint(price=2, delta=5.0, starting_points_delta=5.0, feasible=True),
    ]
    assert _is_monotone(falling) is True
    assert _is_monotone(rising) is False
    assert _is_monotone([]) is True, "nothing to contradict"
    # An infeasible price is the absence of a value, not a lower one, and must not read as a
    # rise when the curve resumes above it.
    gapped = [
        falling[0],
        CurvePoint(price=2, delta=0.0, starting_points_delta=0.0, feasible=False),
        falling[1],
    ]
    assert _is_monotone(gapped) is True


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
    curves = walkaway_board(
        board(), budget=12, slots=3, starters=STARTERS, top=3, prices=[1, 2]
    ).curves
    assert len(curves) == 3
    assert curves[0].player_id == "star", "ranked by projected points"
    assert all(len(c.points) == 2 for c in curves)


def test_a_precomputed_board_is_keyed_so_the_live_path_is_a_lookup():
    curves = {
        c.player_id: c
        for c in walkaway_board(
            board(), budget=12, slots=3, starters=STARTERS, top=2, prices=[1]
        ).curves
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
    assert [c.player_id for c in curves.curves] == ["rb"]


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


def test_the_walk_away_price_is_exact_even_though_the_plotted_curve_is_sampled():
    """§4.7b budgets the *curve*, and a curve priced at every dollar is 172 solves -- 39 seconds
    at 14 open slots. The plotted grid is now shaped rather than dense, which is only safe
    because the walk-away price comes from a binary search over the whole legal range and not
    from the grid. Pinned against the dense curve so the two can never drift apart.
    """
    pool = falling_board()
    sampled = walkaway_curve(
        pool, pool[0], budget=20, slots=3, starters={"RB": 1}, bench_weight=0.2
    )
    dense = walkaway_curve(
        pool,
        pool[0],
        budget=20,
        slots=3,
        starters={"RB": 1},
        bench_weight=0.2,
        prices=list(range(1, sampled.max_legal_bid + 1)),
    )
    assert sampled.walk_away_price == dense.walk_away_price
    assert len(sampled.points) < len(dense.points), "or nothing was saved"


def test_the_display_grid_is_dense_where_the_money_is_and_always_spans_the_range():
    """Most auction decisions happen under $10, so that is where the resolution goes."""
    grid = _display_grid(172)
    assert grid[0] == 1 and grid[-1] == 172, "both ends of the legal range are plotted"
    assert grid == sorted(set(grid)), "strictly increasing, no repeats"
    assert grid[:10] == list(range(1, 11)), "every dollar through $10"
    assert len(grid) < 172 / 4, "the whole point is that it is much smaller"
    # A ceiling inside the dense band is plotted in full rather than truncated.
    assert _display_grid(6) == [1, 2, 3, 4, 5, 6]
    assert _display_grid(1) == [1]


# ------------------- ADR-0006: the amended gate's clause 4, tested rather than asserted


def test_the_live_lookup_is_a_dictionary_hit_and_never_a_solve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0006 replaced "walk-away recompute p99 < 200ms" with what ADR-0003 actually promises:
    the live path is a lookup against a board precomputed between settled picks.

    A curve is dozens of optimizer solves by construction, so any design that computes one while
    the nomination clock runs has already lost. This pins the promise the amended clause makes —
    `get` must not touch the optimizer at all.
    """
    pool = falling_board()
    precomputed = walkaway_board(pool, budget=20, slots=3, starters={"RB": 1}, top=2)

    calls: list[int] = []

    def refuse(*_args: object, **_kwargs: object) -> Roster:
        calls.append(1)
        raise AssertionError("the live lookup path must never call the optimizer")

    monkeypatch.setattr(walkaway, "best_roster", refuse)
    hit = precomputed.get(pool[0].player_id)
    miss = precomputed.get("nobody")
    assert precomputed.covers(pool[0].player_id)
    assert not precomputed.covers("nobody")

    assert calls == [], "the live path solved; that is the whole thing clause 4 forbids"
    assert hit is not None and hit.walk_away_price is not None
    assert miss is None, "outside the board is None — not precomputed, not 'worth nothing'"


def test_the_lookup_reads_the_index_rather_than_walking_the_board():
    """The companion to the test above, and the half it cannot see. Forbidding a *solve* is not
    the same as guaranteeing a *lookup*: a linear scan calls no optimizer either and returns the
    identical object, so swapping the mapping for `next(c for c in self.curves ...)` escaped.

    **Timing it was the wrong instrument.** A first attempt asserted 4,000 lookups over a 4,000
    curve board finished inside half a second; the scan does it in 0.24s, so the test passed
    against the defect. Chasing that with a bigger board or a tighter bound trades a real
    assertion for a machine-speed guess.

    So the index is asserted directly instead: empty it, and a lookup that reads it must miss.
    A scan ignores it and finds the curve anyway, which is exactly the difference that matters.
    """
    pool = falling_board()
    precomputed = walkaway_board(pool, budget=20, slots=3, starters={"RB": 1}, top=2)
    target = pool[0].player_id

    assert precomputed.get(target) is not None
    precomputed._by_player.clear()

    assert precomputed.get(target) is None, "the lookup walked the list instead of the index"
    assert not precomputed.covers(target)


def test_a_board_knows_when_the_users_position_has_moved_past_it():
    """Every curve is an answer about one budget and one open-slot count. The moment the user
    buys somebody, all of them describe a roster they no longer have — and a stale walk-away
    price is exactly the plausible-but-wrong figure this project keeps finding."""
    pool = falling_board()
    precomputed = walkaway_board(pool, budget=20, slots=3, starters={"RB": 1}, top=1)

    assert precomputed.is_current_for(budget=20, slots=3)
    assert not precomputed.is_current_for(budget=14, slots=2), "they bought someone for $6"
    assert not precomputed.is_current_for(budget=20, slots=2)
    assert not precomputed.is_current_for(budget=19, slots=3)
