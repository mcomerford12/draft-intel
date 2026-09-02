"""DI-036 — walk-away curves. The flagship number.

Charter §4.7b::

    Render it as a **walk-away price curve**: the x-axis is bid price, the y-axis is Δ projected
    starting points. Where it crosses zero is the walk-away number, displayed as one enormous
    digit.

The delta at each price is the marginal-value question asked once per price point: solve the
remaining-roster problem with the player forced in at that price, solve it again with them
excluded, and subtract. Positive means the bid still improves the team.

**The excluded arm is solved once for the whole curve.** It does not depend on the price -- a
player you are not buying costs nothing at every price -- so recomputing it per point doubles
the work for an answer that cannot change. That is not a micro-optimisation: the curve is 40 to
80 points, and the optimizer's own docstring records the measured cost of a solve.

**The curve is monotone non-increasing, and that is asserted rather than assumed.** Paying more
for the same player cannot leave a better team, because every roster affordable at a higher
price is also affordable at a lower one. If the curve ever rises, the optimizer is not returning
optima and the walk-away number is meaningless -- so :func:`walkaway_curve` checks and says so
rather than drawing a picture of a bug.

**Where it crosses zero is the walk-away price**, defined as the highest price at which the
delta is still positive. Not the crossing point of a fitted line and not the first
non-positive price: the number the user needs is "the most I should pay", and that is a price
they would actually bid.

**The crossing is found by binary search over every dollar, not by scanning the sampled
curve.** Reading ``max(price where delta > 0)`` off the sampled points confuses two entirely
different situations: a genuine crossing, and a curve still positive at the top of whatever grid
happened to be searched. It reported $58 for a player whose true walk-away price was $117,
under a report line reading "the MOST you should pay" -- a $59 understatement on the number
§4.7b puts on screen as one enormous digit. A coarse grid also understated by up to $2 inside
its own range.

Monotonicity is what makes the search exact, and it is asserted rather than assumed, so the two
facts hold each other up: if the curve ever rises, :attr:`WalkAway.monotone` goes false and the
binary search's premise is void at the same moment.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from itertools import pairwise

from pydantic import BaseModel, ConfigDict

from draft_intel.quant.optimizer import (
    DEFAULT_BENCH_WEIGHT,
    Candidate,
    Roster,
    best_roster,
)


class CurvePoint(BaseModel):
    """One price on the walk-away curve."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    price: int
    delta: float
    """Δ objective against not buying at all. Positive means the bid still improves the team."""

    starting_points_delta: float
    """Δ projected *starting* points, which is what §4.7b puts on the y-axis."""

    feasible: bool
    """False when no legal roster exists at this price, whatever it would be worth."""


class WalkAway(BaseModel):
    """A player's whole walk-away curve, and the one number off it that matters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    player_id: str
    name: str
    position: str
    points: list[CurvePoint]

    walk_away_price: int | None
    """The highest price at which buying still improves the team. ``None`` if never worth it.

    Found by binary search over every dollar up to the legal maximum bid, independently of which
    prices the displayed curve happens to sample.
    """

    max_legal_bid: int
    """``budget - (slots - 1)``: the most this user could bid without stranding a roster spot."""

    baseline_objective: float
    """The best team achievable without this player. Every delta is measured against it."""

    monotone: bool
    """False when the curve rises somewhere, which means the deltas cannot be trusted."""

    @property
    def worth_it_at_any_legal_price(self) -> bool:
        """True when the delta is still positive at the maximum legal bid.

        Distinct from "the curve did not cross": here it genuinely never crosses within what
        the user can afford, so the binding constraint is the budget rather than the player's
        value. The two read identically off a sampled curve and mean different things.
        """
        return self.walk_away_price is not None and self.walk_away_price >= self.max_legal_bid

    def delta_at(self, price: int) -> float | None:
        for point in self.points:
            if point.price == price:
                return point.delta
        return None

    def describe(self) -> str:
        if self.walk_away_price is None:
            return f"{self.name}: not worth buying at any price on this board"
        return f"{self.name}: walk away above ${self.walk_away_price}"


def walkaway_curve(
    candidates: Sequence[Candidate],
    player: Candidate,
    *,
    budget: int,
    slots: int,
    starters: dict[str, int],
    bench_weight: float = DEFAULT_BENCH_WEIGHT,
    prices: Sequence[int] | None = None,
) -> WalkAway:
    """Build the curve for one player.

    Args:
        candidates: The live board at inflation-adjusted prices, including ``player``.
        player: The player on the block.
        budget: The user's remaining dollars.
        slots: The user's remaining roster spots.
        starters: Per-team starting slots including ``FLEX``.
        bench_weight: ADR-0004's λ. Moving it moves the walk-away number, and the UI is
            required to say so.
        prices: Price points to evaluate. Defaults to every dollar from $1 to the user's
            maximum legal bid, which is the whole range they can actually offer.

    Raises:
        ValueError: if ``player`` is not among ``candidates``. Curving a player who is not on
            the board silently measures them against a pool that still contains them.
    """
    if not any(c.player_id == player.player_id for c in candidates):
        raise ValueError(f"{player.name} is not on the board being curved")

    # The most this user can legally bid: every other open slot still needs its dollar.
    ceiling = budget - (slots - 1)
    span = list(prices) if prices is not None else list(range(1, max(1, ceiling) + 1))

    without = best_roster(
        candidates,
        budget=budget,
        slots=slots,
        starters=starters,
        bench_weight=bench_weight,
        excluded=frozenset({player.player_id}),
    )
    baseline = without.objective
    baseline_points = without.starting_points

    points: list[CurvePoint] = []
    for price in span:
        with_them = _forced(candidates, player, price, budget, slots, starters, bench_weight)
        feasible = with_them.objective != float("-inf")
        points.append(
            CurvePoint(
                price=price,
                delta=(
                    round(with_them.objective - baseline, 4)
                    if feasible and baseline != float("-inf")
                    else float("-inf")
                ),
                starting_points_delta=(
                    round(with_them.starting_points - baseline_points, 2) if feasible else 0.0
                ),
                feasible=feasible,
            )
        )

    return WalkAway(
        player_id=player.player_id,
        name=player.name,
        position=player.position,
        points=points,
        walk_away_price=_find_crossing(
            lambda price: _delta(
                candidates, player, price, budget, slots, starters, bench_weight, baseline
            ),
            ceiling=max(1, ceiling),
        ),
        max_legal_bid=max(1, ceiling),
        baseline_objective=baseline,
        monotone=_is_monotone(points),
    )


def _delta(
    candidates: Sequence[Candidate],
    player: Candidate,
    price: int,
    budget: int,
    slots: int,
    starters: dict[str, int],
    bench_weight: float,
    baseline: float,
) -> float:
    roster = _forced(candidates, player, price, budget, slots, starters, bench_weight)
    if roster.objective == float("-inf") or baseline == float("-inf"):
        return float("-inf")
    return roster.objective - baseline


def _find_crossing(delta_at: Callable[[int], float], *, ceiling: int) -> int | None:
    """The highest price with a positive delta, by binary search over ``1..ceiling``.

    Exact because the curve is monotone non-increasing, and costs about eight solves against
    the ceiling's worth of a linear scan. Returns ``None`` when even $1 is not worth paying.
    """
    if delta_at(1) <= 0:
        return None
    low, high = 1, ceiling
    while low < high:
        middle = (low + high + 1) // 2
        if delta_at(middle) > 0:
            low = middle
        else:
            high = middle - 1
    return low


def _forced(
    candidates: Sequence[Candidate],
    player: Candidate,
    price: int,
    budget: int,
    slots: int,
    starters: dict[str, int],
    bench_weight: float,
) -> Roster:
    return best_roster(
        candidates,
        budget=budget,
        slots=slots,
        starters=starters,
        bench_weight=bench_weight,
        forced=[player.model_copy(update={"price": price})],
        excluded=frozenset({player.player_id}),
    )


def _is_monotone(points: Sequence[CurvePoint]) -> bool:
    """Whether the curve never rises as price increases.

    Only the feasible points are compared. An infeasible price is not a lower value, it is the
    absence of one, and threading negative infinity through the comparison would report every
    curve that runs off the end of the budget as broken.
    """
    feasible = [point for point in points if point.feasible]
    return all(later.delta <= earlier.delta + 1e-9 for earlier, later in pairwise(feasible))


def walkaway_board(
    candidates: Sequence[Candidate],
    *,
    budget: int,
    slots: int,
    starters: dict[str, int],
    bench_weight: float = DEFAULT_BENCH_WEIGHT,
    top: int = 25,
    prices: Sequence[int] | None = None,
) -> list[WalkAway]:
    """Precompute curves for the most valuable players, per ADR-0003.

    ADR-0003 requires walk-away prices to be precomputed after each settled pick so the live
    path is a dictionary lookup rather than a solve. This is that precompute, and ``top`` is
    the honest limit on it: a curve costs two solves per price point, so covering the whole
    board at every dollar is not something that fits between two picks.

    **Ranked by VORP, not by projected points.** Raw points are not comparable across
    positions -- in a 2QB league a quarterback outscores every running back on the board, so
    ranking by points returns a target list of twelve quarterbacks and nothing else. VORP is
    already measured against each position's own replacement level, which is what makes it the
    right axis for "who is worth bidding on" rather than "who scores most".
    """
    ranked = sorted(candidates, key=lambda c: (-c.vorp, -c.points))[:top]
    return [
        walkaway_curve(
            candidates,
            player,
            budget=budget,
            slots=slots,
            starters=starters,
            bench_weight=bench_weight,
            prices=prices,
        )
        for player in ranked
    ]
