"""DI-035 — the roster optimizer, and the CBC oracle ADR-0003 requires.

ADR-0003 keeps PuLP/CBC in the test suite as a correctness oracle: the DP is the production
engine because CBC cannot meet §4.7b's latency budget, and the oracle is what makes that trade
"strictly stronger than shipping CBC" rather than "trusting a solver we cannot afford to call".

The oracle is written from the charter's ILP formulation independently, not by transcribing the
DP. An oracle derived from the implementation it checks proves only that the code agrees with
itself.

No player name is hardcoded; synthetic players are named by position and index.
"""

from __future__ import annotations

import random

import pulp
import pytest

from draft_intel.quant.optimizer import (
    DEFAULT_BENCH_WEIGHT,
    Candidate,
    best_roster,
    marginal_value,
)
from draft_intel.quant.slots import FLEX, FLEX_ELIGIBLE

STARTERS = {"QB": 2, "RB": 2, "WR": 2, "TE": 1, FLEX: 2, "K": 1}
TINY = {"QB": 1, "RB": 1, FLEX: 1}


def player(
    pid: str, position: str, points: float, price: int, vorp: float | None = None
) -> Candidate:
    return Candidate(
        player_id=pid,
        name=f"{position}-{pid}",
        position=position,
        points=points,
        vorp=points if vorp is None else vorp,
        price=price,
    )


# --------------------------------------------------------------------- by hand


def test_the_best_roster_is_the_one_with_the_most_starting_points():
    """One QB slot, one RB slot, $10, 2 slots. The $5 QB scoring 100 and the $5 RB scoring 90
    beat any other legal pair."""
    pool = [
        player("q1", "QB", 100.0, 5),
        player("q2", "QB", 40.0, 1),
        player("r1", "RB", 90.0, 5),
        player("r2", "RB", 30.0, 1),
    ]
    result = best_roster(pool, budget=10, slots=2, starters={"QB": 1, "RB": 1}, bench_weight=0.0)
    assert {p.player_id for p in result.players} == {"q1", "r1"}
    assert result.starting_points == 190.0
    assert result.spent == 10


def test_a_tighter_budget_forces_the_cheaper_lineup():
    pool = [
        player("q1", "QB", 100.0, 5),
        player("q2", "QB", 40.0, 1),
        player("r1", "RB", 90.0, 5),
        player("r2", "RB", 30.0, 1),
    ]
    result = best_roster(pool, budget=6, slots=2, starters={"QB": 1, "RB": 1}, bench_weight=0.0)
    assert result.spent <= 6
    assert result.starting_points == 130.0  # the $5 QB and the $1 RB


def test_every_slot_is_filled_because_a_team_with_an_empty_spot_is_not_legal():
    pool = [player(f"r{i}", "RB", 10.0 - i, 1) for i in range(5)]
    result = best_roster(pool, budget=5, slots=3, starters={"RB": 1}, bench_weight=0.1)
    assert result.slots_used == 3
    assert len(result.players) == 3


def test_flex_is_allocated_to_whichever_position_pays_best():
    """One FLEX between RB and WR. The best available FLEX-eligible player is a WR, so the
    split that gives WR the FLEX slot wins."""
    pool = [
        player("r1", "RB", 50.0, 1),
        player("w1", "WR", 50.0, 1),
        player("w2", "WR", 49.0, 1),
        player("r2", "RB", 10.0, 1),
    ]
    result = best_roster(
        pool, budget=3, slots=3, starters={"RB": 1, "WR": 1, FLEX: 1}, bench_weight=0.0
    )
    assert result.starting_points == 149.0
    assert result.flex_split["WR"] == 1


def test_flex_can_never_be_handed_to_an_ineligible_position():
    pool = [player(f"q{i}", "QB", 100.0 - i, 1) for i in range(4)]
    result = best_roster(pool, budget=4, slots=3, starters={"QB": 1, FLEX: 2}, bench_weight=0.0)
    assert all(position in FLEX_ELIGIBLE for position in result.flex_split)
    assert len(result.starters) == 1, "only the one QB slot can be started"


# ------------------------------------------------------------ the bench weight (ADR-0004)


def test_lambda_zero_recovers_the_charters_literal_objective():
    """§4.7b maximises starting lineup points alone. Under λ=0 the bench is free money, so the
    optimizer buys the best starter it can and fills the rest at $1 -- finishing at $0, which
    ADR-0004 says is roughly right in a shallow league and badly wrong at the margin."""
    pool = [
        player("r1", "RB", 100.0, 9),
        player("r2", "RB", 90.0, 5),
        player("r3", "RB", 50.0, 1),
        player("r4", "RB", 40.0, 1),
    ]
    result = best_roster(pool, budget=10, slots=2, starters={"RB": 1}, bench_weight=0.0)
    assert result.starting_points == 100.0
    assert result.spent == 10


def test_a_positive_lambda_stops_the_optimizer_spending_everything_on_one_starter():
    """The same board with λ=0.2. The bench player is now worth 0.2 x its VORP, so the
    cheaper starter plus a real bench player beats the expensive starter plus a scrub."""
    pool = [
        player("r1", "RB", 100.0, 9),
        player("r2", "RB", 90.0, 5),
        player("r3", "RB", 80.0, 5),
        player("r4", "RB", 1.0, 1),
    ]
    greedy = best_roster(pool, budget=10, slots=2, starters={"RB": 1}, bench_weight=0.0)
    balanced = best_roster(pool, budget=10, slots=2, starters={"RB": 1}, bench_weight=0.2)

    assert {p.player_id for p in greedy.players} == {"r1", "r4"}
    assert {p.player_id for p in balanced.players} == {"r2", "r3"}
    assert balanced.starting_points < greedy.starting_points, "worse starters, better team"


def test_a_higher_lambda_never_lowers_the_objective_of_its_own_solution():
    """Sanity on the parameter itself: λ scales a non-negative term."""
    pool = [player(f"r{i}", "RB", 50.0 - i, 2) for i in range(6)]
    low = best_roster(pool, budget=10, slots=3, starters={"RB": 1}, bench_weight=0.1)
    high = best_roster(pool, budget=10, slots=3, starters={"RB": 1}, bench_weight=0.5)
    assert high.objective >= low.objective


# ------------------------------------------------------------------- forced and excluded


def test_forcing_a_player_in_puts_them_on_the_roster_at_the_stated_price():
    """The forced price is the hypothetical bid, not the player's board value."""
    pool = [player("r1", "RB", 100.0, 5), player("r2", "RB", 90.0, 5)]
    result = best_roster(
        pool,
        budget=15,
        slots=2,
        starters={"RB": 2},
        bench_weight=0.0,
        forced=[player("x", "RB", 10.0, 8)],
    )
    assert {p.player_id for p in result.players} == {"x", "r1"}
    assert result.spent == 13, "the $8 hypothetical bid plus the best affordable partner"


def test_starters_are_chosen_on_points_minus_lambda_vorp_not_on_points():
    """The defect the CBC oracle was structurally blind to.

    Two $1 running backs, one starting slot, λ=0.2. Starting the 100-point / 100-VORP player
    and benching the 99-point / 0-VORP one scores 100. Starting the *lower* scorer and benching
    the higher scores 99 + 0.2 x 100 = 119, because the bench term rewards the VORP that goes
    with him.

    The old justification -- "points >= vorp with λ < 1, so the ordering is never worth
    inverting" -- does not follow, and the DP returned 100. It was safe only because
    ``vorp = max(0, points - replacement)`` keeps the two monotone together within a position,
    an unstated precondition that ``Candidate`` does not enforce and that DI-038's value
    overrides are positioned to break.
    """
    pool = [player("a", "RB", 100.0, 1, vorp=100.0), player("b", "RB", 99.0, 1, vorp=0.0)]
    result = best_roster(pool, budget=10, slots=2, starters={"RB": 1}, bench_weight=0.2)

    assert result.objective == pytest.approx(119.0)
    assert [p.player_id for p in result.starters] == ["b"]


def test_a_player_who_would_rather_be_benched_still_starts_if_a_slot_is_open():
    """The starting lineup is maximal, because a real manager must field one.

    An empty QB slot with a quarterback on the bench is not a roster anybody can submit. The
    optimizer models the legal lineup, not the paper-optimal one -- so a player whose λ x vorp
    beats their points still occupies the slot.

    Unreachable on real data, where vorp = max(0, points - replacement) makes λ x vorp < points
    for everyone. Pinned because the oracle originally disagreed here and it took a brute-force
    run to work out which of the two was modelling the actual league.
    """
    pool = [player("q", "QB", 10.0, 1, vorp=300.0), player("r", "RB", 50.0, 1, vorp=50.0)]
    result = best_roster(pool, budget=10, slots=2, starters={"QB": 1, "RB": 1}, bench_weight=1.0)

    assert [p.player_id for p in result.starters] == ["r", "q"]
    assert result.objective == pytest.approx(60.0), "not 350: the QB slot cannot sit empty"


def test_dominance_pruning_compares_vorp_as_well_as_points():
    """A player who scores less but carries more VORP is the better bench player, so pruning on
    points alone discards the roster the optimizer needs.

    Two slots, so a player is dropped once **two** others beat them. Under a points-only rule
    ``deep`` is beaten by both ``rich`` and ``second`` and is pruned away -- leaving a best
    roster worth 100 instead of 600. The rule has to compare both dimensions, because the two
    contributions a player can make are ``points`` if they start and ``λ x vorp`` if they do not.
    """
    pool = [
        player("rich", "RB", 100.0, 1, vorp=0.0),
        player("second", "RB", 99.0, 1, vorp=0.0),
        player("deep", "RB", 90.0, 1, vorp=500.0),
    ]

    result = best_roster(pool, budget=10, slots=2, starters={"RB": 1}, bench_weight=1.0)

    assert "deep" in {p.player_id for p in result.players}
    assert result.objective == pytest.approx(600.0), "100 starting + 500 bench VORP"


def test_a_forced_player_does_not_take_a_starting_slot_from_a_better_one():
    """The defect the earlier implementation had. Forcing a weak player used to reserve a
    starting slot for them, so a stronger available player was scored as bench -- the DP
    optimised an objective it did not report."""
    pool = [player("r1", "RB", 100.0, 1)]
    result = best_roster(
        pool,
        budget=10,
        slots=2,
        starters={"RB": 1},
        bench_weight=0.0,
        forced=[player("weak", "RB", 5.0, 1)],
    )
    assert [p.player_id for p in result.starters] == ["r1"]
    assert result.starting_points == 100.0
    assert result.objective == pytest.approx(100.0)


def test_excluding_a_player_keeps_them_off_the_roster():
    pool = [player("r1", "RB", 100.0, 1), player("r2", "RB", 90.0, 1)]
    result = best_roster(
        pool,
        budget=5,
        slots=1,
        starters={"RB": 1},
        bench_weight=0.0,
        excluded=frozenset({"r1"}),
    )
    assert [p.player_id for p in result.players] == ["r2"]


def test_forcing_a_player_the_budget_cannot_cover_is_infeasible_not_wrong():
    result = best_roster(
        [player("r1", "RB", 100.0, 1)],
        budget=5,
        slots=2,
        starters={"RB": 1},
        forced=[player("x", "RB", 99.0, 99)],
    )
    assert result.objective == float("-inf")
    assert any("INFEASIBLE" in note for note in result.notes)


def test_a_board_too_thin_to_fill_the_slots_is_infeasible():
    """ "There is no legal roster from here" is a real answer during a draft, and the completion
    planner's most important output when it is true."""
    result = best_roster([player("r1", "RB", 10.0, 1)], budget=50, slots=5, starters={"RB": 1})
    assert result.objective == float("-inf")
    assert any("no legal roster" in note for note in result.notes)


# ------------------------------------------------------------------- marginal value


def test_marginal_value_is_positive_below_the_walk_away_price_and_negative_above():
    """§4.7b. The point where it crosses zero is the walk-away number."""
    pool = [
        player("star", "RB", 100.0, 1),
        *[player(f"r{i}", "RB", 50.0, 1) for i in range(5)],
    ]
    star = next(p for p in pool if p.player_id == "star")

    cheap = marginal_value(pool, star, 1, budget=10, slots=3, starters={"RB": 1}, bench_weight=0.0)
    dear = marginal_value(pool, star, 9, budget=10, slots=3, starters={"RB": 1}, bench_weight=0.0)

    assert cheap > 0
    assert dear < cheap


def test_a_price_that_leaves_no_legal_roster_reads_as_never_rather_than_as_a_number():
    pool = [player(f"r{i}", "RB", 50.0, 1) for i in range(5)]
    star = player("star", "RB", 100.0, 1)
    assert marginal_value(
        [*pool, star], star, 200, budget=10, slots=3, starters={"RB": 1}
    ) == float("-inf")


# -------------------------------------------------------- dominance pruning is exact


def test_a_dominated_player_never_changes_the_answer():
    """Costs no less, scores no more: cannot appear in any optimal roster."""
    good = [player("r1", "RB", 100.0, 5), player("r2", "RB", 60.0, 2)]
    dominated = [*good, player("junk", "RB", 50.0, 9), player("junk2", "RB", 10.0, 5)]

    lean = best_roster(good, budget=10, slots=2, starters={"RB": 1}, bench_weight=0.2)
    padded = best_roster(dominated, budget=10, slots=2, starters={"RB": 1}, bench_weight=0.2)

    assert lean.objective == padded.objective
    assert {p.player_id for p in lean.players} == {p.player_id for p in padded.players}


def test_the_safety_cap_says_so_rather_than_pretending_to_be_optimal():
    """Points RISE with price, so no player dominates another and pruning removes nothing.

    A pool where points fall as price rises is entirely pruned away by dominance alone and the
    cap never bites -- which is what an earlier version of this test built, and it therefore
    asserted nothing about the cap.
    """
    pool = [player(f"r{i}", "RB", 10.0 + i, i + 1) for i in range(80)]
    result = best_roster(pool, budget=200, slots=2, starters={"RB": 1}, cap=5)
    assert result.is_exact is False
    assert any(note.startswith("CAPPED") for note in result.notes)


def test_an_uncapped_solve_reports_itself_exact():
    pool = [player(f"r{i}", "RB", 100.0 - i, 1) for i in range(5)]
    assert best_roster(pool, budget=10, slots=2, starters={"RB": 1}).is_exact


# ============================================================================
# The CBC oracle (ADR-0003)
# ============================================================================


def cbc_best_roster(
    pool: list[Candidate], *, budget: int, slots: int, starters: dict[str, int], bench_weight: float
) -> float:
    """The charter's §4.7b ILP, written from the formulation rather than from the DP.

    Binary ``take`` per player; ``start_base`` and ``start_flex`` for the two ways a player can
    reach the starting lineup, so a player cannot occupy both a base slot and FLEX.

    **The starting lineup is maximal**, and that constraint is the whole difficulty. A fantasy
    manager must field a legal lineup: an empty QB slot with a quarterback on the bench is not a
    roster anybody can submit. Without it the solver benches players whose ``λ x vorp`` exceeds
    their ``points`` and leaves their slot empty, which scores better on paper and cannot happen
    in the league. Encoded as ``Σ start_p >= min(slots_p, Σ take_p)``, linearised with a binary
    switch per position because ``min`` is not linear.

    On this project's real data the question never arises -- within a position
    ``vorp = max(0, points - replacement)``, so ``λ x vorp < points`` for every player and
    starting is always better. It arises here because the random pool deliberately decouples the
    two, which is what makes the oracle able to see the starter-ordering bug at all.

    Returns the objective only. Ties are common on synthetic boards and two different optimal
    rosters are both correct answers, so comparing membership would fail on agreement.
    """
    problem = pulp.LpProblem("roster", pulp.LpMaximize)
    by_id = {p.player_id: p for p in pool}
    big_m = len(pool) + 1

    take = {pid: pulp.LpVariable(f"t_{pid}", cat="Binary") for pid in by_id}
    start_base = {pid: pulp.LpVariable(f"b_{pid}", cat="Binary") for pid in by_id}
    start_flex = {
        pid: pulp.LpVariable(f"f_{pid}", cat="Binary")
        for pid, p in by_id.items()
        if p.position in FLEX_ELIGIBLE
    }

    def started(pid: str) -> pulp.LpAffineExpression:
        return start_base[pid] + start_flex.get(pid, 0)

    problem += pulp.lpSum(
        by_id[pid].points * started(pid)
        + bench_weight * by_id[pid].vorp * (take[pid] - started(pid))
        for pid in take
    )
    problem += pulp.lpSum(by_id[pid].price * take[pid] for pid in take) <= budget
    problem += pulp.lpSum(take.values()) == slots
    for pid in take:
        problem += started(pid) <= take[pid]

    # Every position in the POOL needs a constraint, not every position in `starters`. A
    # position with no base slots has a limit of zero, and omitting it lets the solver start
    # unlimited players there.
    for position in {p.position for p in pool}:
        members = [pid for pid in by_id if by_id[pid].position == position]
        room = starters.get(position, 0)
        taken_here = pulp.lpSum(take[pid] for pid in members)
        filled = pulp.lpSum(start_base[pid] for pid in members)
        problem += filled <= room
        # filled >= min(room, taken_here), via a switch that picks which bound binds.
        switch = pulp.LpVariable(f"z_{position}", cat="Binary")
        problem += filled >= room - big_m * (1 - switch)
        problem += filled >= taken_here - big_m * switch

    flex_room = starters.get(FLEX, 0)
    flex_filled = pulp.lpSum(start_flex.values())
    spare = pulp.lpSum(take[pid] - start_base[pid] for pid in start_flex)
    problem += flex_filled <= flex_room
    flex_switch = pulp.LpVariable("z_flex", cat="Binary")
    problem += flex_filled >= flex_room - big_m * (1 - flex_switch)
    problem += flex_filled >= spare - big_m * flex_switch

    problem.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[problem.status] != "Optimal":
        return float("-inf")
    return round(pulp.value(problem.objective), 4)


def random_pool(rng: random.Random, size: int) -> list[Candidate]:
    """A random board with **VORP drawn independently of points**.

    The first version of this helper left ``vorp`` defaulting to ``points``, which explored a
    two-dimensional input space along its one-dimensional diagonal -- and the DP's starter
    ordering can only be wrong when the two disagree. Twelve seeds passed against a DP that
    sorted starters on ``points`` instead of ``points - λ x vorp``, and the oracle was
    structurally incapable of noticing.

    On real data ``vorp = max(0, points - replacement)`` does make VORP monotone in points
    within a position, so the diagonal is where this project's own boards live. That is exactly
    why it had to stop being where the oracle looks: ``Candidate`` does not enforce the
    relationship, and DI-038 lets a user override ``points`` without touching ``vorp``.
    """
    positions = ["QB", "RB", "WR", "TE", "K"]
    return [
        player(
            f"p{i}",
            rng.choice(positions),
            float(rng.randint(10, 300)),
            rng.randint(1, 25),
            vorp=float(rng.randint(0, 300)),
        )
        for i in range(size)
    ]


@pytest.mark.parametrize("seed", range(30))
def test_the_dp_agrees_with_the_cbc_oracle(seed: int) -> None:
    """ADR-0003's correctness proof: the fast engine is exact, not merely fast.

    Small random states, because CBC is a subprocess and this is a test rather than the live
    path. That size limit is exactly the constraint that put the DP in production.
    """
    rng = random.Random(seed)
    pool = random_pool(rng, 14)
    budget = rng.randint(12, 40)
    slots = rng.randint(2, 5)
    bench_weight = rng.choice([0.0, DEFAULT_BENCH_WEIGHT, 0.5])
    starters = {"QB": 1, "RB": 1, "WR": 1, FLEX: 1}

    dp = best_roster(pool, budget=budget, slots=slots, starters=starters, bench_weight=bench_weight)
    oracle = cbc_best_roster(
        pool, budget=budget, slots=slots, starters=starters, bench_weight=bench_weight
    )

    if oracle == float("-inf"):
        assert dp.objective == float("-inf")
        return
    assert dp.objective == pytest.approx(oracle, abs=1e-4), (
        f"seed {seed}: DP {dp.objective} vs CBC {oracle}"
    )


def test_the_oracle_would_actually_catch_a_wrong_dp():
    """A test that never fails proves nothing. Deliberately hand CBC a different objective and
    confirm the comparison notices -- otherwise the agreement above could be vacuous."""
    rng = random.Random(99)
    pool = random_pool(rng, 20)
    starters = {"QB": 1, "RB": 1, "WR": 1, FLEX: 1}
    dp = best_roster(pool, budget=120, slots=4, starters=starters, bench_weight=0.0)
    wrong = cbc_best_roster(pool, budget=120, slots=4, starters=starters, bench_weight=1.0)

    assert dp.objective != float("-inf"), "a comparison of two infeasible answers proves nothing"
    assert dp.objective != pytest.approx(wrong, abs=1e-4)
