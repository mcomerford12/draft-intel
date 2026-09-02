"""DI-035 — the roster optimizer. Exact dynamic programming, per ADR-0003.

Charter §4.7b wants the marginal value engine: *"for any player at any hypothetical price, does
bidding this much make my team better?"* — answered by solving the remaining-roster problem
twice, with the player forced in at price X and with them excluded, and reporting the delta.

§3 specifies PuLP/CBC. §4.7b requires the walk-away curve to recompute in under 200ms. Those
cannot both hold: CBC is a subprocess costing 30-150ms per solve regardless of problem size, and
a curve needs 40-80 solves. ADR-0003 resolves it — **DP in production, CBC retained as a test
oracle** — and this module is the DP half. ``tests/test_optimizer.py`` holds the oracle.

**Objective** (ADR-0004)::

    maximise  Σ(starting lineup points)  +  λ x Σ(bench VORP)

λ defaults to 0.2. λ = 0 recovers the charter's literal "starting lineup points" objective
exactly, so this is a superset rather than a deviation. Under λ = 0 the optimizer always
recommends six $1 bench players and finishing the night at $0, which is roughly right in a
shallow league and badly wrong at the margin.

----

**How the DP stays exact.**

The difficulty is FLEX. A player's contribution depends on whether they start, and whether they
start depends on the whole roster — so positions do not decouple. Three steps make them:

1. **Enumerate the FLEX split.** Two FLEX slots across RB/WR/TE is six distributions. For a
   fixed split every position has a known number of effective starting slots and the positions
   become independent.
2. **Within a position, sort by starter priority, ``points - λ x vorp``.** For a chosen set of
   players at a position, the objective is::

       Σ_starters points + λ Σ_bench vorp
         = λ Σ_all vorp  +  Σ_starters (points - λ x vorp)

   The first term does not depend on who starts, so the optimal assignment gives the starting
   slots to the largest ``points - λ x vorp``. Sorting on that key makes "the first ``s`` taken
   are the starters" a fact rather than an assumption.

   **An earlier version sorted on ``points`` alone**, and justified it with "a starter
   contributes ``points`` and a bench player ``λ x vorp``, and ``points >= vorp`` with
   ``λ < 1``, so the ordering is never worth inverting." That argument is invalid: ``points >=
   vorp`` does not imply the two orderings agree. Two running backs at $1 with λ=0.2, scoring
   100 (VORP 100) and 99 (VORP 0), are worth 119 by starting the *lower* scorer and benching
   the higher, and the points-sorted DP returned 100.

   It happened to be safe on this project's own data, because ``vorp = max(0, points -
   replacement)`` makes VORP monotone in points within a position. That precondition was
   nowhere stated, nowhere tested, and ``Candidate`` does not enforce it -- ``points`` and
   ``vorp`` are two free floats on a public API, and DI-038 lets a user override one without
   the other. Sorting on the correct key removes the precondition instead of documenting it.
3. **Knapsack the per-position tables together** over remaining slots and remaining dollars.

**The one precondition, stated because the last unstated one was a defect.** Step 1 commits each
FLEX slot to a position *before* the players are known, so a split can hand a slot to a position
the roster then buys nobody at. :func:`_split_lineup` repairs that -- spare FLEX room goes to the
best eligible player still benched -- and the objective is scored from the repaired lineup, so
what is reported is always a team that could actually be fielded. But the *search* is still
guided by the pre-repair table, and that only agrees with the repaired value while

    ``λ x vorp <= points`` for every candidate

holds: starting a player is then never worth less than benching them, every optimal lineup is
already maximal, and no split can profit by stranding a slot. Under that condition the DP is
exact, verified against a brute-force enumerator over 1,500 randomised states (1-6 slots,
λ ∈ {0, 0.2, 1.0}, forced and excluded arms). The same sweep with VORP drawn freely produced 66
mismatches -- among them a two-player roster scored **202 with no starters at all**, because
benching both beat fielding either.

The condition holds throughout this project by construction: ``vorp = max(0, points -
replacement) <= points`` and λ defaults to 0.2. It is not enforced by ``Candidate``, though, and
DI-038 lets a user override ``points`` without touching ``vorp``, so :func:`best_roster` checks
it per call and says so in :attr:`Roster.notes` when it fails. Outside it the answer is still
legal and still correctly scored -- it is simply no longer guaranteed optimal.

**Dominance pruning is exact, not a heuristic.** A player who costs at least as much as another
at the same position and scores no better can never appear in an optimal roster, so removing
them changes no answer. On a real board this cuts several hundred candidates to a few dozen,
which is what makes the DP fast enough to be the live path.

``MAX_CANDIDATES_PER_POSITION`` is a separate, *inexact* safety cap for pathological inputs. It
is set well above what dominance pruning leaves and, when it bites, says so in
:attr:`Roster.notes` rather than silently returning a possibly-suboptimal answer as if it were
optimal.

----

**Measured latency, against §4.7b's 200ms budget.** On the real 140-player live pool:

=====================  ==========  ================================================
open slots / budget    full solve  note
=====================  ==========  ================================================
14 slots / $185           ~450ms   over budget; only reachable before the first pick
8 slots / $120            ~156ms   within budget
4 slots / $60              ~45ms   within budget
=====================  ==========  ================================================

The dictionary implementation this replaced took **4.4 seconds** for the 14-slot solve, with
4.6 of them inside dictionary lookups rather than arithmetic. Vectorising the inner loop over
the budget axis is what closed most of that gap.

The 14-slot case is stated rather than explained away: it is genuinely over budget. It is also
the state that exists only before the user has bought anybody, when nothing is on the block and
there is no bid to answer. Every state that occurs during live bidding is inside the budget, and
it gets faster as the night goes on. Reporting the numbers beats claiming the target.

Dominance pruning removed **zero** candidates from that live pool, because auction price tracks
projected points closely enough that almost nobody is both cheaper and better than somebody
else. It stays because a board with mispriced players is exactly when it pays, but it is not
what makes this fast.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict

from draft_intel.quant.slots import FLEX, FLEX_ELIGIBLE

DEFAULT_BENCH_WEIGHT = 0.2
"""ADR-0004's λ. A judgement coefficient, not a measurement; badge it as such wherever shown."""

MAX_CANDIDATES_PER_POSITION = 60
"""Inexact safety cap, applied only after exact dominance pruning. See the module docstring."""


class Candidate(BaseModel):
    """One player the optimizer may buy, at a price."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    player_id: str
    name: str
    position: str
    points: float
    vorp: float
    price: int

    def contribution(self, *, starting: bool, bench_weight: float) -> float:
        return self.points if starting else bench_weight * self.vorp

    def starter_priority(self, bench_weight: float) -> float:
        """``points - λ x vorp``: how much this player gains by starting rather than benching.

        The correct key for choosing which of a position's players fill its starting slots.
        See step 2 of the module docstring for why it is not ``points``.
        """
        return self.points - bench_weight * self.vorp


class Roster(BaseModel):
    """The best legal roster reachable from here, and what it is worth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    players: tuple[Candidate, ...]
    starters: tuple[Candidate, ...]
    bench: tuple[Candidate, ...]
    spent: int
    slots_used: int
    objective: float
    starting_points: float
    bench_weight: float
    flex_split: dict[str, int]
    notes: tuple[str, ...] = ()

    @property
    def is_exact(self) -> bool:
        """False when the safety cap bit and the answer may not be optimal."""
        return not any(note.startswith("CAPPED") for note in self.notes)


def _prune(
    candidates: Sequence[Candidate], cap: int, max_take: int
) -> tuple[list[Candidate], bool]:
    """Drop dominated candidates, then cap. Returns ``(kept, was_capped)``.

    **Dominance has to account for the slot count, and the obvious version does not.** "Costs
    no less and scores no more, therefore useless" is true when you may buy as few players as
    you like. Here every roster spot must be filled, so a cheap weak player is not useless --
    they are how the roster gets finished. Pruning five $1 running backs down to the best one
    left a board that could not fill three slots at all, and the optimizer reported the
    position infeasible.

    The correct rule counts: a player is dominated only when at least ``max_take`` *other*
    players are each no more expensive and no less productive. Fewer than that and they may
    still be needed, because the ones ahead of them can all be bought at once.

    **"No less productive" means both points and VORP**, not points alone. A player contributes
    ``points`` if they start and ``λ x vorp`` if they do not, so one who scores less but carries
    more VORP is the better bench player and cannot be pruned against. Comparing points alone
    was sound only while ``vorp = max(0, points - replacement)`` kept the two monotone together
    -- the same unstated precondition that made the starter ordering wrong, in the same place.

    Ties are broken on ``player_id`` so that exactly one of an identical pair survives the
    comparison, which is right because they are interchangeable.

    **The cap reserves room for the cheapest, or it can turn a feasible board infeasible.**
    Truncating a points-sorted list keeps the expensive players and throws away the $1 fills, so
    ten $50 wideouts and ten $1 wideouts capped at five leaves nothing buyable on $10 -- and the
    optimizer then reports, flatly and falsely, that no legal roster exists. The bottom
    ``max_take`` places are given to the cheapest survivors, which is exactly enough for any one
    position to fill every remaining slot. Feasibility after the cap is then guaranteed whenever
    it held before it: swapping each chosen player for their position's cheapest survivor never
    costs more and never changes anyone's position. Optimality is still not guaranteed -- that
    is what the ``CAPPED`` note says -- but "no roster exists" is no longer a lie.
    """
    kept: list[Candidate] = []
    for candidate in candidates:
        better = 0
        for other in candidates:
            if other is candidate:
                continue
            if (
                other.price > candidate.price
                or other.points < candidate.points
                or other.vorp < candidate.vorp
            ):
                continue
            if (
                other.price == candidate.price
                and other.points == candidate.points
                and other.vorp == candidate.vorp
                and other.player_id > candidate.player_id
            ):
                continue
            better += 1
            if better >= max_take:
                break
        if better < max_take:
            kept.append(candidate)
    kept.sort(key=lambda c: (-c.points, c.price, c.player_id))
    if len(kept) <= cap:
        return kept, False
    reserve = min(max_take, cap)
    survivors = {c.player_id for c in sorted(kept, key=lambda c: (c.price, -c.points))[:reserve]}
    for candidate in kept:
        if len(survivors) >= cap:
            break
        survivors.add(candidate.player_id)
    return [c for c in kept if c.player_id in survivors], True


NEG = -1e18
"""Sentinel for "unreachable". A float array cannot hold ``None``, and ``-inf`` propagates
``nan`` through ``-inf + -inf`` comparisons in ways that are tedious to guard everywhere."""


def _position_table(
    candidates: Sequence[Candidate],
    *,
    mandatory: Sequence[Candidate],
    starting_slots: int,
    max_take: int,
    budget: int,
    bench_weight: float,
) -> tuple[np.ndarray, list[np.ndarray], list[Candidate]]:
    """``(values, parent snapshots, ordered)`` for one position.

    ``values[t, b]`` is the best objective taking ``t`` players at total cost ``b``.

    **One parent snapshot per candidate, not one array.** A single parents array is not enough
    to walk a path back: a later candidate can improve a state an earlier path depends on, and
    the walk then reads the newer parent and reconstructs a roster holding the same player
    twice. It did exactly that -- the objective was right and the roster was wrong, which is the
    worse of the two failures. ``snapshots[k]`` is the parents array as it stood *before*
    candidate ``k`` was processed -- index 0 is the empty initial array -- so after consuming
    candidate ``j`` the walk continues in ``snapshots[j]``, the state that transition read.

    **Vectorised over the budget axis.** The dictionary version of this ran the full 14-slot
    solve in about 4.4 seconds against §4.7b's 200ms budget, and profiling put 4.6 of those
    seconds in dictionary lookups rather than in arithmetic. Each ``(take this candidate)``
    transition is a shift-and-max over the whole budget row, which is one numpy operation
    instead of 186 dictionary probes.

    **Forced players are merged into the sorted list and made mandatory**, rather than being
    handled by reducing ``starting_slots``. That earlier shortcut assumed a forced player always
    occupies a starting slot, which is wrong whenever a cheaper available player outscores them:
    the DP would count the better player as bench while the final lineup started them, so the
    objective it optimised was not the objective it reported. Merging keeps one rule -- the
    highest scorers among those taken are the starters -- true everywhere.
    """
    required = {c.player_id for c in mandatory}
    ordered = sorted(
        [*mandatory, *candidates],
        key=lambda c: (-c.starter_priority(bench_weight), c.price, c.player_id),
    )
    shape = (max_take + 1, budget + 1)

    values = np.full(shape, NEG, dtype=np.float64)
    parents = np.full(shape, -1, dtype=np.int32)
    values[0, 0] = 0.0
    snapshots: list[np.ndarray] = [parents]

    for index, candidate in enumerate(ordered):
        price = candidate.price
        must = candidate.player_id in required
        if price > budget or (must and max_take < 1):
            if must:
                return np.full(shape, NEG), [np.full(shape, -1, dtype=np.int32)], ordered
            # A snapshot per candidate even when the candidate is skipped, so that snapshot
            # indices and candidate indices stay aligned. They diverged once and the walk
            # indexed past the end of the list.
            snapshots.append(parents)
            continue

        # A mandatory candidate has no "skip" branch, so its successor array starts empty
        # rather than as a copy of the current one.
        nxt = np.full(shape, NEG) if must else values.copy()
        nxt_parents = np.full(shape, -1, dtype=np.int32) if must else parents.copy()

        for taken in range(max_take - 1, -1, -1):
            gain = candidate.contribution(
                starting=taken < starting_slots, bench_weight=bench_weight
            )
            shifted = values[taken, : budget + 1 - price] + gain
            # Slices are views, so writing through `better` updates `nxt` in place.
            target = nxt[taken + 1, price:]
            better = shifted > target
            target[better] = shifted[better]
            nxt_parents[taken + 1, price:][better] = index

        values, parents = nxt, nxt_parents
        snapshots.append(nxt_parents)
    return values, snapshots, ordered


def _reconstruct(
    snapshots: Sequence[np.ndarray],
    ordered: Sequence[Candidate],
    taken: int,
    spend: int,
) -> tuple[Candidate, ...]:
    """Walk the back-pointers from one state to the players that reached it.

    Each hop steps back to the snapshot taken *before* the candidate it just consumed, which is
    the state that transition actually read. Reading the latest snapshot throughout is what
    produced rosters holding the same player twice.
    """
    out: list[Candidate] = []
    step = len(snapshots) - 1
    while taken > 0 and step >= 0:
        index = int(snapshots[step][taken, spend])
        if index < 0:
            break
        candidate = ordered[index]
        out.append(candidate)
        taken -= 1
        spend -= candidate.price
        step = index
    return tuple(reversed(out))


def _flex_splits(flex_slots: int) -> list[dict[str, int]]:
    """Every way to hand ``flex_slots`` FLEX slots to the eligible positions."""
    eligible = sorted(FLEX_ELIGIBLE)
    splits: list[dict[str, int]] = []

    def walk(index: int, left: int, acc: dict[str, int]) -> None:
        if index == len(eligible) - 1:
            splits.append({**acc, eligible[index]: left})
            return
        for take in range(left + 1):
            walk(index + 1, left - take, {**acc, eligible[index]: take})

    walk(0, flex_slots, {})
    return splits


def best_roster(
    candidates: Iterable[Candidate],
    *,
    budget: int,
    slots: int,
    starters: Mapping[str, int],
    bench_weight: float = DEFAULT_BENCH_WEIGHT,
    forced: Sequence[Candidate] = (),
    excluded: frozenset[str] = frozenset(),
    cap: int = MAX_CANDIDATES_PER_POSITION,
) -> Roster:
    """The highest-objective legal roster buyable with ``budget`` across ``slots``.

    Args:
        candidates: Available players at their current inflation-adjusted prices.
        budget: Dollars left.
        slots: Roster spots left to fill. The result fills exactly this many, because a roster
            with an empty spot is not a legal team.
        starters: Per-team starting slots including ``FLEX``.
        bench_weight: ADR-0004's λ.
        forced: Players committed at a stated price -- the "with them in" arm of the
            marginal-value question. They are merged into their position's candidate list as
            mandatory takes rather than costed separately, so the starter/bench rule applies to
            them on the same terms as everyone else.
        excluded: Player ids the DP may not buy -- the "without them" arm.
        cap: Candidates kept per position after exact dominance pruning.

    Returns a roster with ``objective`` of negative infinity and an ``INFEASIBLE`` note when no
    legal roster exists, rather than raising: "there is no legal roster from here" is a real
    answer during a draft, and it is the completion planner's most important output when true.
    """
    forced = tuple(forced)
    forced_ids = {c.player_id for c in forced}
    infeasible = _infeasible(bench_weight)

    if len(forced) > slots or sum(c.price for c in forced) > budget:
        return infeasible(
            f"forcing {len(forced)} player(s) at ${sum(c.price for c in forced)} exceeds "
            f"${budget} across {slots} slot(s)"
        )

    by_position: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        if candidate.player_id in excluded or candidate.player_id in forced_ids:
            continue
        by_position.setdefault(candidate.position, []).append(candidate)

    notes: list[str] = []

    # The exactness precondition, checked per call rather than assumed. See the module docstring:
    # a player worth more benched than started can make a split profit by stranding a starting
    # slot, and the search is guided by the pre-repair table.
    dominated_bench = sum(
        1
        for group in (*by_position.values(), forced)
        for c in group
        if c.starter_priority(bench_weight) < 0
    )
    if dominated_bench:
        notes.append(
            f"NON-DOMINANT BENCH: {dominated_bench} candidate(s) score more benched than "
            f"started at λ={bench_weight}; the roster returned is legal and correctly scored "
            "but is no longer guaranteed optimal"
        )

    pruned: dict[str, list[Candidate]] = {}
    for position, group in by_position.items():
        kept, capped = _prune(group, cap, slots)
        pruned[position] = kept
        if capped:
            notes.append(
                f"CAPPED {position}: {len(group)} candidates pruned to {cap}; the answer may "
                "not be optimal"
            )

    forced_by_position: dict[str, list[Candidate]] = {}
    for candidate in forced:
        forced_by_position.setdefault(candidate.position, []).append(candidate)

    base = {position: count for position, count in starters.items() if position != FLEX}
    best: Roster | None = None
    cache: dict[tuple[str, int], tuple[np.ndarray, list[np.ndarray], list[Candidate]]] = {}
    for split in _flex_splits(starters.get(FLEX, 0)):
        roster = _solve_split(
            pruned,
            base=base,
            split=split,
            budget=budget,
            slots=slots,
            bench_weight=bench_weight,
            forced_by_position=forced_by_position,
            notes=notes,
            cache=cache,
        )
        if roster is not None and (best is None or roster.objective > best.objective):
            best = roster

    if best is None:
        reason = f"no legal roster fills {slots} slot(s) within ${budget}"
        if any(note.startswith("CAPPED") for note in notes):
            reason += " from the capped candidate list"
        return infeasible(reason, notes=notes)
    return best


def _infeasible(bench_weight: float) -> Callable[..., Roster]:
    """Build the "no legal roster" result, so its shape is stated once."""

    def make(reason: str, notes: Sequence[str] = ()) -> Roster:
        return Roster(
            players=(),
            starters=(),
            bench=(),
            spent=0,
            slots_used=0,
            objective=float("-inf"),
            starting_points=0.0,
            bench_weight=bench_weight,
            flex_split={},
            notes=(*notes, f"INFEASIBLE: {reason}"),
        )

    return make


def _solve_split(
    pruned: Mapping[str, list[Candidate]],
    *,
    base: Mapping[str, int],
    split: Mapping[str, int],
    budget: int,
    slots: int,
    bench_weight: float,
    forced_by_position: Mapping[str, list[Candidate]],
    notes: Sequence[str],
    cache: dict[tuple[str, int], tuple[np.ndarray, list[np.ndarray], list[Candidate]]],
) -> Roster | None:
    """Solve one FLEX distribution, where the positions are independent.

    The combine is a two-dimensional (max, +) convolution over slots and dollars. Iterating it
    as nested dictionary lookups cost 4.6 of the 4.4-second full solve -- 8.9 million dict
    probes -- so instead each reachable ``(take, cost)`` cell of a position's table is applied
    to the whole accumulated grid at once, as a single shifted numpy maximum. Only cells that
    are actually reachable are visited, which is what keeps the outer loop short.

    ``cache`` is keyed on ``(position, starting_slots)`` because a position's table depends on
    nothing else. Across the six FLEX splits, QB and K have one table each rather than six.
    """
    positions = sorted(set(pruned) | set(base) | set(forced_by_position))

    combined = np.full((slots + 1, budget + 1), NEG)
    combined[0, 0] = 0.0
    # `(position index, take, cost)` of the contribution that reached each state.
    trail: list[np.ndarray] = []

    tables: list[tuple[np.ndarray, list[np.ndarray], list[Candidate]]] = []
    for position in positions:
        starting = base.get(position, 0) + split.get(position, 0)
        key = (position, starting)
        if key not in cache:
            cache[key] = _position_table(
                pruned.get(position, []),
                mandatory=forced_by_position.get(position, []),
                starting_slots=starting,
                max_take=slots,
                budget=budget,
                bench_weight=bench_weight,
            )
        tables.append(cache[key])

    for values, _snapshots, _ordered in tables:
        nxt = np.full((slots + 1, budget + 1), NEG)
        choice = np.full((slots + 1, budget + 1, 2), -1, dtype=np.int32)
        takes, costs = np.nonzero(values > NEG / 2)
        for take, cost in zip(takes.tolist(), costs.tolist(), strict=True):
            gain = values[take, cost]
            source = combined[: slots + 1 - take, : budget + 1 - cost]
            target = nxt[take:, cost:]
            candidate_value = source + gain
            better = candidate_value > target
            target[better] = candidate_value[better]
            choice[take:, cost:][better] = (take, cost)
        combined = nxt
        trail.append(choice)
        if not np.any(combined > NEG / 2):
            return None

    row = combined[slots]
    best_spend = int(np.argmax(row))
    if row[best_spend] <= NEG / 2:
        return None

    players = _unwind(tables, trail, slots, best_spend)
    starters_chosen, bench = _split_lineup(
        players, base=base, split=split, bench_weight=bench_weight
    )
    # Scored from the lineup that is reported, not from the table cell that found it. The two
    # agree everywhere the DP is exact, and where they do not -- a split that stranded a FLEX
    # slot, repaired above -- the table cell is the value of a team nobody could field. Reporting
    # the cell would put a number on the page that the roster underneath it does not support.
    objective = sum(c.points for c in starters_chosen) + bench_weight * sum(c.vorp for c in bench)
    return Roster(
        players=players,
        starters=starters_chosen,
        bench=bench,
        spent=best_spend,
        slots_used=len(players),
        objective=round(float(objective), 4),
        starting_points=round(sum(c.points for c in starters_chosen), 2),
        bench_weight=bench_weight,
        flex_split=dict(split),
        notes=tuple(notes),
    )


def _unwind(
    tables: Sequence[tuple[np.ndarray, list[np.ndarray], list[Candidate]]],
    trail: Sequence[np.ndarray],
    slots: int,
    spend: int,
) -> tuple[Candidate, ...]:
    """Recover the roster from the combine's choice arrays, last position first."""
    players: list[Candidate] = []
    used, left = slots, spend
    for index in range(len(trail) - 1, -1, -1):
        take, cost = (int(x) for x in trail[index][used, left])
        if take < 0:
            break
        _values, snapshots, ordered = tables[index]
        players.extend(_reconstruct(snapshots, ordered, take, cost))
        used -= take
        left -= cost
    return tuple(players)


def _split_lineup(
    players: Sequence[Candidate],
    *,
    base: Mapping[str, int],
    split: Mapping[str, int],
    bench_weight: float,
) -> tuple[tuple[Candidate, ...], tuple[Candidate, ...]]:
    """Assign the chosen players to starting slots, per the fixed FLEX split.

    Ordered by ``starter_priority``, the same key the DP scored by. If these two ever disagree
    the reported objective is not the one that was optimised, which is the defect the earlier
    forced-player handling had -- and sorting here on ``points`` while the DP sorted on
    ``points - λ x vorp`` would reintroduce it in a subtler form.

    **The lineup is then made maximal, which the fixed split alone does not guarantee.** The
    split commits each FLEX slot to a position before the players are known, so it can hand one
    to a position the roster ends up buying nobody at. That slot is then unfillable while a
    FLEX-eligible player sits on the bench -- and a lineup with an open slot and an eligible
    player behind it is not a lineup anybody could field. Left alone the DP scores it anyway,
    and because a benched player is worth ``λ x vorp``, that fiction can *outscore* every legal
    lineup: on a two-player roster it returned an objective of 202 with **no starters at all**.
    Any spare FLEX room is reassigned here to the best eligible player still on the bench.
    """
    starters: list[Candidate] = []
    bench: list[Candidate] = []
    by_position: dict[str, list[Candidate]] = {}
    for player in players:
        by_position.setdefault(player.position, []).append(player)

    for position, group in by_position.items():
        group.sort(key=lambda c: (-c.starter_priority(bench_weight), c.price, c.player_id))
        room = base.get(position, 0) + split.get(position, 0)
        starters.extend(group[:room])
        bench.extend(group[room:])

    # Only room that came from FLEX is transferable; an unfilled base slot belongs to its own
    # position and nobody else can stand in it. Positions the roster bought nobody at are the
    # common case and are counted here too.
    spare_flex = sum(
        min(max(0, base.get(position, 0) + count - len(by_position.get(position, ()))), count)
        for position, count in split.items()
    )

    if spare_flex > 0:
        promotable = sorted(
            (c for c in bench if c.position in FLEX_ELIGIBLE),
            key=lambda c: (-c.starter_priority(bench_weight), c.price, c.player_id),
        )[:spare_flex]
        promoted = {c.player_id for c in promotable}
        starters.extend(promotable)
        bench = [c for c in bench if c.player_id not in promoted]

    starters.sort(key=lambda c: -c.points)
    bench.sort(key=lambda c: -c.points)
    return tuple(starters), tuple(bench)


def marginal_value(
    candidates: Sequence[Candidate],
    player: Candidate,
    price: int,
    *,
    budget: int,
    slots: int,
    starters: Mapping[str, int],
    bench_weight: float = DEFAULT_BENCH_WEIGHT,
) -> float:
    """Charter §4.7b: does buying this player at this price make the team better?

    Solves twice -- forced in at ``price``, and excluded -- and returns the difference in
    objective. Positive means yes.

    An infeasible arm returns negative infinity, so a price that leaves no legal roster gives a
    negative-infinity delta rather than a plausible-looking number. That is the correct answer
    and the walk-away curve reads it as "never".
    """
    at_price = player.model_copy(update={"price": price})
    with_them = best_roster(
        candidates,
        budget=budget,
        slots=slots,
        starters=starters,
        bench_weight=bench_weight,
        forced=[at_price],
    )
    without = best_roster(
        candidates,
        budget=budget,
        slots=slots,
        starters=starters,
        bench_weight=bench_weight,
        excluded=frozenset({player.player_id}),
    )
    if with_them.objective == float("-inf"):
        return float("-inf")
    if without.objective == float("-inf"):
        return float("inf")
    return round(with_them.objective - without.objective, 4)
