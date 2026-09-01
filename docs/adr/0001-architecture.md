# ADR-0001: Event-sourced core with a pure fold to derived state

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** architect

## Context

The system must survive, mid-draft and without corruption: pick reversals (Sleeper's picks array
can shrink), in-place amendments, a process restart, network loss, manual keeper entry, budget
corrections, and retroactive reclassification of a pick made an hour earlier.

The charter (§4.8) already requires overrides to be events rather than mutations, and warns that
retrofitting an override layer onto mutable derived state is a rewrite. The remaining question was
whether derived state should be maintained incrementally or recomputed.

## Decision

One append-only event log carries everything — API observations and user overrides alike:

```
derived_state = f(api_events + override_events)
```

Derived state is **recomputed by a full fold on every change**, never patched incrementally.

Team identity keys on `draft_slot`, never `roster_id`. Slot → `roster_id` and slot → owner are
resolved late and are re-resolvable.

Money is uniform: every team starts at the same budget and is decremented by every pick's amount,
keeper or competitive. There is no keeper branch in the ledger.

Time-series analytics key on `competitive_seq` — a dense index over `COMPETITIVE` picks — never on
`pick_no`.

### Module boundaries

| Module | Owns | Must not |
|---|---|---|
| `sleeper/` | HTTP, caching, polling, snapshot diffing | valuation math |
| `domain/` | identity, keepers, classification, ledger | HTTP or transport |
| `quant/` | projections, replacement, pricing, inflation, skew, optimizer | UI or transport |
| `store/` | append-only persistence | interpreting events |
| `replay/` | harness, simulator | production ingestion paths |

### Replacement-baseline mapping

The charter defines two baselines in §4.2 and two valuations in §4.3 on a different axis, and never
pairs them. Four exist. Pricing uses the last-drafted baselines because bench players cost real money:

| Baseline | Universe | Feeds |
|---|---|---|
| `repl_full_starter` | all 160 | diagnostics only |
| `repl_full_lastdrafted` | all 160 | `VORP_i` → `market_value_i` |
| `repl_live_starter` | post-keeper 140 | scarcity counters, QB pressure panel |
| `repl_live_lastdrafted` | post-keeper 140 | `VORP_live_i` → `baseline_value_i` |

### Inflation naming

`keeper_inflation` (structural, `live ÷ full_market`, fixed, >1) and `market_inflation` (live,
exactly 1.00 at pick 0, drifts). Never summed, never averaged, never on a shared axis. The charter
uses the bare word "inflation" for both in §1.1(3) and §4.5.

## Consequences

Recomputing 160 picks costs microseconds, so the cost is irrelevant and the benefit is large: pick
reversal, restart recovery, retroactive reclassification and override commutativity are correct by
construction, because no incremental state exists to corrupt. The Sprint 1 property tests for those
behaviours passed on first run.

Obliges us to keep the fold pure and fast. If it ever exceeds the 200ms budget, the answer is
memoising inputs, not introducing mutable state.
