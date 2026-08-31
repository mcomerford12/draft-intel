# Decisions For Review

Per charter §11: resolve autonomously, document, flag for the user. Nothing here
blocks work; everything here changes a number if the user answers differently.

## Open — needs a ruling

| # | Item | Default taken | Why it matters |
|---|---|---|---|
| 1 | `floor(0.75 × $1) = $0` | **Clamp retention to $1** (`minimum_retention_price: 1`) | A $0 pick breaks money conservation and the `max_bid = budget − (open_slots − 1)` reserve, which assumes every filled slot cost ≥$1. No keeper on this slate is near $1, so this is a correctness guard rather than a live concern — but the Hypothesis property tests the charter demands *will* generate the case. |
| 2 | Are the 2 keeper slots positionally constrained? | **Assume not** (charter §11.4) | The slate is consistent with unconstrained (Mason kept 2 WR). If constrained, it changes opponent-need modelling. |
| 3 | Injury-risk coefficients (§4.3) | Modest, configurable, ADR-documented | Deliberately small so the risk discount never dominates VORP. |
| 4 | Clear overrides on a new day? | Prompt if last session >12h ago (§11.9) | Prevents a stale 7:10pm TE nudge silently skewing draft-day prices. |

## Resolved this session

| # | Item | Resolution |
|---|---|---|
| 5 | Keeper price basis (was ambiguous across §1.1 / §4.3 / §4.4) | Observed fact with `price_source` provenance. `floor(0.75 × …)` demoted to reconciliation check. See `config/keepers.yaml`. |
| 6 | Value-snapshot date (§A.6, was `TBD`) | **Draft day, 2026-09-04.** Prices read from Sleeper auction values that morning. |
| 7 | "Inflation" naming collision (§1.1(3) vs §4.5) | Split into `keeper_inflation` (structural, fixed, >1) and `market_inflation` (live, exactly 1.00 at pick 0). |
| 8 | Which replacement baseline feeds which valuation (§4.2 vs §4.3) | Explicit 4-cell mapping table in `docs/PLAN.md`. Pricing uses the last-drafted baselines. |
| 9 | Live optimizer engine (§3 PuLP vs §4.7b 200ms — mutually exclusive) | DP primary, PuLP/CBC retained as offline test oracle. Deviation → ADR-0003. |
| 10 | ILP bench weight (§4.7b degenerate on bench) | `+ λ × Σ bench VORP`, λ default 0.2, live UI slider. λ=0 recovers the charter's literal objective. ADR-0004. |
| 11 | Draft date | **2026-09-04.** Charter's ≥2-day slack is not achievable; cut-order defined in `docs/PLAN.md`. |

## Charter statements this session invalidated

- **§1.1(5) and §4.9: "the entire valuation model can be computed, validated, and
  frozen days before the draft."** Not true given keeper prices arrive on draft day.
  `ΣK_t` sets `total_live_money`, which scales every live price. `make prep` produces
  an **estimated** board pre-draft, and draft-morning revaluation is critical path
  rather than a convenience. The charter already requires sub-200ms revaluation on
  keeper-set change — that requirement is now load-bearing.
- **§2's framing of manual keeper entry as a fallback.** It is now the *primary*
  route by which real retention prices enter the system, so it must be a rehearsed
  flow in the RUNBOOK, not an emergency path.
