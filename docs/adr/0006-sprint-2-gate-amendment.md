# ADR-0006: Sprint 2 gate amendment

- **Status:** **Accepted 2026-09-02.** Applied to the Sprint 2 gate in `docs/KANBAN.md`.
- **Date:** 2026-09-02
- **Deciders:** user (orchestrator) · drafted by the implementer at the user's request

## Context

The Sprint 2 gate, as written in `docs/KANBAN.md`:

> **Sprint 2 gate:** `make prep` produces the full estimated priced board against the real keeper
> manifest and **a human has reviewed it**. Money-conservation invariants hold. Walk-away
> recompute p99 < 200ms. The 500-run Monte Carlo and the p<0.01 bot gate are retained per the
> full-charter decision, and are cut item #1 if the schedule slips.

The draft is **2026-09-05 19:00 MDT — three days away**. All fourteen Sprint 2 cards are built
and `make ci` is green at 540 tests and 97% coverage. The gate is nonetheless not met, and two of
its five clauses will not be met by Saturday. This ADR amends three of them and leaves two
untouched.

*(Accepted as drafted, all three amendments, with both untouched clauses standing. The
consequences below are now obligations, not predictions.)*

The charter's §9 lists what is settled and not up for debate: league settings, floor rounding on
keepers, the keeper slate, the local-first stack, the valuation methodology, and the
review/evaluator independence rules. **The sprint gates are not on that list**, and the gate's own
final sentence anticipates this decision by naming its cut candidate. Amending it is therefore in
scope — but it was the orchestrator's call, not the implementer's, so it was drafted as a
proposal and applied only on their acceptance.

### Where each clause actually stands

| # | Clause | State |
|---|---|---|
| 1 | `make prep` produces the priced board | **Met against fixtures.** Cannot run against the real league: 10 of 20 keeper keys resolve (DI-043). |
| 2 | Money-conservation invariants hold | **Met.** Replay reproduces $1,979 / 20 keepers / 140 competitive exactly; six of six clean property runs. |
| 3 | A human has reviewed it | **Not met.** Blocked on the user. |
| 4 | Walk-away recompute p99 < 200ms | **Not met at any point in the draft.** Measured 11.1s at 14 open slots, 3.6s at 8, 0.8s at 4. |
| 5 | 500-run Monte Carlo + p<0.01 bot gate | **Not started.** No simulator exists in the tree. |

## Decision

### Amendment 1 — clause 4 is restated as the thing ADR-0003 actually promises

**Decided:** *the live walk-away lookup is O(1) against a board precomputed between settled
picks; the precompute completes inside 30 seconds at 8 or fewer open slots, and its cost at more
open slots is stated on the page rather than hidden.*

This is not a relaxation, it is a correction. §4.7b's 200ms is a budget for answering *"should I
bid?"* while the clock runs, and ADR-0003 already resolves that by precomputing: **the live path
is a dictionary lookup, not a solve.** A walk-away curve is dozens of optimizer solves by
construction, so 200ms was never reachable for one and the original clause measured the wrong
thing — the same error the optimizer's own latency table made until DI-050 corrected it.

The real question is whether the *precompute* fits between picks, which in a live auction is
30-60 seconds. Measured on the real 140-player pool:

| open slots | one curve | `top=25` precompute | when this state exists |
|---|---|---|---|
| 14 | 11.1s | 4m 26s | before the first pick |
| 8 | 3.6s | 1m 24s | mid-draft |
| 4 | 0.8s | 19s | late |

It fits late, is marginal mid-draft, and does not fit early. DI-051 carries the rewrite that would
close the gap (solve the curve as one DP read at many budgets); profiling says 91% of the cost is
in the combine, so the obvious optimisation buys nothing and this is real work, not tuning.

**What this obliges us to test:** the lookup path is O(1) and never solves; the precompute is
timed on the real pool at each stage and the figures are published, not asserted.

### Amendment 2 — clause 5 is cut, on the terms the gate itself set

**Decided:** *the 500-run Monte Carlo and the p<0.01 bot gate are cut from Sprint 2 and moved to
Sprint 5 (stretch).*

The gate names these as "cut item #1 if the schedule slips". The schedule has slipped. Taking the
cut explicitly is better than leaving a clause permanently unmet, because an unmet clause nobody
intends to meet quietly devalues every other clause on the list.

Two consequences worth stating plainly rather than burying:

- **§4.9 item 1's p25/p50/p75 stays refused.** The Monte Carlo is what would make percentile
  labels real. `make prep` currently prints a *sourced two-point band* — prices as loaded against
  prices under the 75% rule — and says on the page that these are not percentiles. That deviation
  was already recorded; this amendment makes it permanent for this draft rather than pending.
- **We lose the only planned check on the valuation as a whole.** Every current test checks a
  component. The Monte Carlo would have asked whether the model wins drafts against bots, which is
  a different question and the only one that would have caught a model that is internally
  consistent and collectively wrong. **This is the real cost of the cut**, and it is not mitigated
  by 540 passing tests.

### Amendment 3 — clause 1 is qualified, not weakened

**Decided:** *`make prep` produces the priced board against the real keeper manifest and the real
projections; running against the live league additionally requires DI-043, which is outside this
sprint's control.*

The board renders today from the real manifest, the real projections and the real scoring
settings. What it cannot do is resolve all twenty keepers against the live league, because five
managers have not joined — and the tool correctly refuses rather than guessing. Holding a sprint
open on somebody else's Sleeper signup is not a useful gate; naming the dependency is.

### Not amended

**Clause 2 (money conservation) and clause 3 (a human has reviewed it) stand exactly as written.**

Clause 3 in particular is not softened, and the proposal was explicit that it would not be. §4.9's entire premise is that *"a valuation model you first see three minutes before the
auction is one you cannot sanity-check."* Two review rounds and two adversarial evaluation rounds
have found real defects in this board — including prices sourced from the wrong draft entirely —
and none of that is a substitute for the person who knows this league reading it and disagreeing.
It is the one clause whose absence would make the rest ceremonial.

### What "Sprint 2 complete" now requires

Under the amended gate, Sprint 2 closes when:

1. the user reads the priced board and their corrections are applied *(blocked on the user)*;
2. a re-review round runs on the eight cards whose last recorded verdict is a rejection, and both
   verdicts pass — **DI-027, DI-031, DI-032, DI-033, DI-035, DI-036, DI-037, DI-039**. Every
   finding behind those rejections is closed, but no re-review has run, and every round so far has
   found something real;
3. cards are written for **DI-026, DI-028, DI-029 and DI-030**, which predate the card schema and
   have no acceptance criteria or verdict fields at all;
4. clauses 1, 2 and 4-as-amended are re-verified and the figures published.

Only DI-034 and DI-038 currently hold both an APPROVED reviewer verdict and an APPROVED evaluator
verdict. **Two of fourteen cards are Done under §6 as written.**

## Consequences

**Easier.** Sprint 2 becomes closeable before the draft rather than permanently short of a clause
nobody intends to meet. Clause 4 starts measuring the thing the user actually experiences — the
latency of an answer during a nomination — instead of the latency of an internal routine.

**Harder.** The valuation ships this draft with no end-to-end check. If the model is wrong in a
way every component test agrees with, nothing here will catch it before 7pm Saturday. The user's
read of the board is now the *only* whole-model review, which raises the stakes on clause 3
considerably.

**Newly obliged to test — done, and mutation-verified 4/4.** That the live walk-away path performs
no solve *and* reads an index rather than walking the board; that a board says when the user's
position has moved past it, because every curve on a stale board answers a question about a roster
they no longer have; and that `make prep` states its own keeper-resolution status, so "priced
against the real manifest" cannot quietly become "priced against as much of it as resolved".

**Two of those tests were wrong on the first attempt, and the record is worth keeping.** Forbidding
a *solve* does not guarantee a *lookup* — a linear scan calls no optimizer either — so the first
version was timed instead, on the reasoning that cost is the only observable difference. The scan
does 4,000 lookups over a 4,000-curve board in 0.24s, under the 0.5s bound, and passed against the
defect. Chasing it with a bigger board trades a real assertion for a guess about machine speed, so
the index is now asserted directly: empty it, and a lookup that reads it must miss. Separately, the
keeper-resolution test asserted `resolved == expected` on a fixture where all twenty resolve, which
a line printing the expected count twice satisfies just as well; the incomplete case — the live
league's own state, at 10 of 20 — is now exercised directly.

**Not changed by this ADR.** The charter's §6 independence rules, the valuation methodology, the
keeper slate, and both remaining gate clauses. This ADR narrows what Sprint 2 promises; it does
not lower what it must prove about money.
