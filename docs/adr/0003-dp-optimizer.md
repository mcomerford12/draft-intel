# ADR-0003: DP as the live optimizer; PuLP/CBC retained as a test oracle

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** architect, quant-analyst

## Context

The charter requires two things that cannot both hold. §3 specifies PuLP (CBC) for the optimizer.
§4.7b requires the walk-away curve to recompute in under 200ms so it can update live as bidding
climbs.

CBC is invoked as a subprocess: PuLP writes an LP file, shells out, and parses the result, costing
roughly 30–150ms per solve regardless of problem size. A walk-away curve needs one solve per price
point, twice (player forced in vs excluded) — 40 to 80 solves. That is seconds, not 200ms.

## Decision

The remaining-roster problem is a bounded knapsack over ≤14 slots and ≤$200 in $1 increments, with
lineup legality expressible as position-eligibility classes. Solve it with dynamic programming:
exact, no subprocess, microseconds.

- **DP is the production engine** for walk-away curves and the roster completion planner.
- **PuLP/CBC is retained in the test suite as a correctness oracle.** A property test asserts DP and
  CBC agree on the optimal roster across randomly generated states.
- **Walk-away prices are precomputed for every player after each settled pick**, so the live path is
  a dictionary lookup rather than a solve.

## Consequences

Strictly stronger than shipping CBC: we get the speed of the fast path *and* a proof that it is
exact, rather than trusting a solver we cannot afford to call.

Precomputation also resolves the §5 requirement to enter a nomination in under two seconds — the
number is on screen before the user finishes typing the player's name.

Obliges us to keep the DP and the ILP formulation semantically identical. If the objective changes
(see ADR-0004), both must change together or the oracle test will catch the drift.
