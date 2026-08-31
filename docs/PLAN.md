# Draft Intelligence Platform — Refined Context & Build Plan

## Context

The user drafts in a 10-team, $200-budget, full-PPR **2QB** Sleeper auction on **Thursday
September 4, 2026**. Every team enters with 2 keepers retained at `floor(0.75 × sleeper
auction value)` — 20 players, mostly elite, off the board before bidding starts. That
reshapes the pool, the budgets, the replacement levels, and creates structural league-wide
inflation. The user gets one seat, one night, real money, no dress rehearsal.

They supplied a detailed charter (`CONTEXT.md`) and a keeper manifest (`keepers.yaml`).
This plan is the refined version of that charter: the same scope, with four internal
contradictions resolved, three technical impossibilities corrected, and the schedule
anchored to the real date.

**Scope decision (user, this session): full charter as written.** I raised that five
sprints will not fit four days; the user reaffirmed. Planned accordingly, with an explicit
cut-order rather than silent descoping.

---

## Decisions locked this session

| Question | Answer | Consequence |
|---|---|---|
| Keeper price source | **Sleeper auction values, read on draft day** | Board is *estimated* pre-draft, not frozen. Day-of revaluation is critical path. |
| Scope | **Full charter** | All 5 sprints planned; cut-order defined below. |
| Sleeper API access | **Widen network policy** | User action required — see Blockers. |
| Auction format | **Fast live auction** | Cockpit premise stands: glanceable, keyboard-first, no modals. |
| Draft date | **Sept 4, 2026** | 4 days. Charter's ≥2-day slack unachievable. |
| Replay fixture | **User runs a mock draft on Sleeper, supplies `draft_id`** | Excellent — also yields the Case B ceremonial fixture for free. |
| ILP bench weight | **λ as a live UI slider**, default 0.2 | Objective = starting points + λ × bench VORP. |

---

## Charter contradictions — resolved

The charter's standing instruction was to flag contradictions rather than silently pick.
Flagged in conversation; resolutions below are proposed, and each gets an ADR.

### C1. Keeper price basis (§1.1 vs §4.3 vs §4.4) — **resolved by the user's answer**

Three incompatible bases existed: Sleeper's published auction value, our own computed
`market_value`, and (via §4.4) a fallback chain for when the Sleeper field doesn't exist.
`ΣK_t` sets `total_live_money`, which scales every price — this could not stay ambiguous.

**Resolution: retention price is an observed fact with a recorded provenance, never a
derived quantity.** `keepers.yaml` gains per-keeper `price: <int|null>` and
`price_source: sleeper_draft_room | commissioner | estimated`. Resolution order:

1. `metadata.amount` on a keeper pick in the picks feed (Case A) — authoritative.
2. User types it from the Sleeper draft room via the override layer (§4.8) — authoritative.
3. `floor(0.75 × market_value)` — **estimate only**, badged as such on every number
   downstream of it, and never silently promoted to truth.

`floor(0.75 × …)` is demoted from price *source* to price *check*: it drives the
reconciliation alert (§2), not the ledger.

### C2. `floor(0.75 × $1) = $0` — needs a league ruling

A $0 pick breaks money conservation and the `max_bid = budget − (open_slots − 1)` reserve,
which assumes every filled slot cost ≥$1. **Default: clamp to $1**, assert no pick is ever
$0, surface as a `DECISIONS_FOR_REVIEW.md` item. Low probability (no keeper on the slate is
near $1) but it is a silent-corruption class of bug, so it gets an assertion.

### C3. "Inflation" names two quantities (§1.1(3) vs §4.5)

§1.1 says inflation at pick 0 is >1.0; §4.5 says it starts near 1.0. Both correct, different
quantities, guaranteed to be merged by an implementer. **Distinct names from day one:**

- `keeper_inflation` — structural, `live_value ÷ full_market_value`, fixed, ≈1.15–1.20,
  known pre-draft. This is the "the room clears X% over book" number.
- `market_inflation` — live, **exactly 1.00 at pick 0** by construction (proven below),
  drifts with the room's actual behavior.

Never summed, never averaged together, never share a chart axis or a label.

*Proof that `market_inflation` = 1.00 at pick 0, which is also the first unit test:* at pick 0,
`discretionary_remaining = total_live_money − 140` and `remaining_value = Σ(baseline−1)` over
the top 140 `= dpv_live × Σ VORP_live = discretionary_live`. Identical. Ratio 1.00.

### C4. Which replacement baseline feeds which valuation (§4.2 vs §4.3)

§4.2 defines two baselines, §4.3 two valuations, and nothing pairs them. Four baselines
actually exist. **Explicit mapping, asserted in code:**

| Baseline | Universe | Method | Feeds |
|---|---|---|---|
| `repl_full_starter` | all 160 | greedy starter fill | diagnostics only |
| `repl_full_lastdrafted` | all 160 | last player rostered | `VORP_i` → `market_value_i` (§4.3 i) |
| `repl_live_starter` | post-keeper 140 | greedy, both sides adjusted | scarcity counters, QB pressure panel |
| `repl_live_lastdrafted` | post-keeper 140 | last player rostered | `VORP_live_i` → `baseline_value_i` (§4.3 ii) |

Pricing uses the **last-drafted** baselines (§4.2's own instruction: bench players cost real
money). The starter baselines drive scarcity display only.

---

## Technical corrections to the charter

### T1. The 200ms walk-away curve is unachievable with PuLP/CBC

CBC is a subprocess: 30–150ms of process spawn and file I/O *per solve*. A walk-away curve
needs one solve per price point × 2 (forced-in / excluded) = 40–80 solves. Seconds, not 200ms.
The charter demands both PuLP (§3) and <200ms (§4.7b); they are mutually exclusive.

**Resolution (ADR-0003):** the remaining-roster problem is a bounded knapsack over ≤14 slots
and ≤$200 in $1 increments — a DP table of ~2,800 cells per position-eligibility class. Exact,
microseconds, no subprocess.

- **Primary engine: DP.** Serves live walk-away curves and the roster planner.
- **PuLP/CBC retained as an offline correctness oracle in tests only.** Property test:
  DP and CBC agree on the optimal roster across thousands of random states. This is
  strictly *more* rigorous than shipping CBC, because it proves the fast path exact.
- **Walk-away prices are precomputed for every player after each settled pick**, so the live
  path is a dictionary lookup, not a solve. This also fixes the §5 "type the nomination in
  under two seconds" problem — the number is already on screen when the player is named.

### T2. ILP objective — λ bench slider (user's choice)

`maximize Σ(starting points) + λ × Σ(bench VORP)`, λ default 0.2, live slider 0.0–1.0,
coefficient documented in ADR-0004. At λ=0 the charter's literal objective is recovered, so
this is a superset, not a deviation from intent. Prevents the optimizer from advising the
user to finish the night at exactly $0 with no injury cover.

### T3. Sprint 2's "optimizer beats every bot at p<0.01" gate

Retained per the full-charter decision, but recorded honestly: the bots are our own
invention, so this measures the model against itself. The **backtest against the user's real
mock draft** is the gate carrying actual signal. If the schedule slips, this is cut item #1
(see cut-order) — it is the most expensive gate with the least information content.

---

## Verified: Appendix A arithmetic is correct

Re-derived independently, as §8 Sprint 0 requires. All of it holds:

- Positional split **7 QB / 6 RB / 7 WR / 0 TE / 0 K** = 20 ✓
- Remaining base starting demand **QB 13 / RB 14 / WR 13 / TE 10 / K 10** = 60, +20 FLEX = **80** ✓
- Remaining roster spots **140** ✓ (the two totals §4.2 warns are easy to transpose)
- Per-team needs (A.3) correct row by row; every keeper fits a base slot, so no FLEX is
  consumed — but the *code* must derive this greedily, not assume it (a team keeping 3 WRs
  in some future season would break the assumption, not the algorithm)
- **AJ, Mason, Burt are exactly the three teams holding no QB** and therefore needing two ✓

A.4's structural thesis stands. The QB market is the exploitable one, and the user needing
only one QB against three teams needing two apiece is the defining feature of their draft.

---

## Architecture

Stack per §3, unchanged: Python 3.12 + uv, FastAPI + uvicorn, httpx, SQLite (WAL) +
SQLAlchemy 2.x, Pydantic v2, React 18 + TS + Vite, TanStack Query/Table, Zustand, Tailwind +
shadcn/ui, Recharts, pytest + respx + Hypothesis, Vitest, Playwright, ruff + mypy --strict.
Binds `0.0.0.0`, prints LAN URL + QR. `make draft` starts everything.

**The one spine that makes the rest correct:**

```
derived_state = f(api_events + override_events)
```

Append-only event log, never a mutation. Picks, budget corrections, value overrides, manual
keepers, reclassifications — all the same log. This is what makes pick reversal, restart,
late correction, and manual keeper entry safe simultaneously, and it is why §4.8 must land
in Sprint 1 rather than being retrofitted.

```
ingest/     sleeper client, poller, snapshot diffing, event log, pick_class engine
quant/      projections, replacement levels, dual valuation, inflation, skew, DP optimizer
api/        FastAPI routes, WebSocket push, DI wiring
web/        React cockpit
config/     keepers.yaml (user-editable, price + price_source per keeper)
docs/       KANBAN.md, adr/, api-findings.md, RUNBOOK.md, DRAFT_DAY_CHEATSHEET.md
```

Agent team per §6 with the independence rules. Given four days, the roster runs
`architect`, `data-engineer`, `quant-analyst`, `backend-engineer`, `frontend-engineer`,
`test-engineer`, `code-reviewer`, `evaluator`. Independent review + adversarial evaluation
are enforced **without exception on `quant/` and `ingest/`** — where a silent error costs
real money — and best-effort elsewhere.

---

## Schedule — anchored to Sept 4

The charter's ≥2-day slack is not achievable. Each day ends with a working artifact, so
value is banked continuously rather than all at the end.

**Aug 31 (today) — Sprint 0.** Repo skeleton, uv/pnpm, ruff/mypy/eslint, CI, `make` targets,
`.claude/agents/`, ADR template. API discovery spike against live 2026 endpoints; commit
fixtures; `docs/api-findings.md` records exactly which auction-value/ADP fields exist.
Resolve all 20 keepers to `player_id` **confirming by position** — the Josh Allen QB/LB
collision and Caleb/Kyren Williams — and print the human-review confirmation table.
Validate live league settings against §1 and fail loudly on mismatch.
*Gate: `make ci` green, fixtures committed, confirmation table reviewed by the user.*

**Sept 1 — Sprint 1 (highest risk, and the day it must land).** Async client with backoff and
1s poll floor. Daily player cache. Event-sourced ingestion with snapshot diffing (undo, edit,
pause). `pick_class` engine: manifest match → `is_keeper` → arming switch → manual
reclassification. Override event log. Derived state engine. SQLite persistence with
crash-restart. Replay harness. Mock auction simulator.
*Gate: replay the user's mock draft, reproduce every budget to the dollar. Kill mid-replay,
resume identical. **Case A / Case B equivalence must be bit-identical.***

**Sept 2 — Sprint 2, and the day that matters most to the user personally.** Projections +
league scoring. Four replacement baselines. Dual valuation. Keeper surplus board.
`MarketValueProvider` ×3. Live + positional inflation. Skew, both measures. Opponent
affordability. DP optimizer + walk-away curves. Tendency profiles.
*Gate: **`make prep` produces the full estimated priced board and the user reads it.** This
is the single highest-value deliverable in the plan — it is the user's chance to argue with
the model while there is still time to fix it.*

**Sept 3 — Sprint 3 + Sprint 4 compressed.** FastAPI + WebSocket. Full cockpit per §5:
nomination bar, status strip, league grid, big board, analytics, pick feed, keyboard map,
three-way visual badging (measured / modeled / typed), override inspector, λ slider,
keeper-mode arming switch with `keepers seen: N/20`. Then chaos suite, offline mode,
RUNBOOK, cheat sheet.
*Gate: Playwright drives a full 160-pick replay. Then a 60-minute rehearsal, **run as Case B**
(the expected case) with injected failures and zero developer intervention.*

**Sept 4 — draft morning.** Not a build day. Run the RUNBOOK: read the real keeper prices
out of the Sleeper draft room, enter them, confirm full revaluation lands inside 200ms,
confirm `keepers seen: N/20` reconciles, print the tier sheet, open the cockpit.

**Cut-order if the schedule slips** — cut in this sequence, and tell the user each time:
1. 500-run Monte Carlo + the p<0.01 bot gate (T3)
2. Manager tendency profiles, spend Gini, treemaps
3. Nomination advisor (already Sprint 5)
4. Playwright E2E (keep the replay harness — it is cheaper and catches more)
5. Charts, reduced to the inflation curve alone

**Never cut:** money-conservation property tests, Case A/B equivalence, the keeper
double-count audit, the 2QB replacement-level check, `make prep`.

---

## Verification

Beyond per-card tests, these are the checks that would actually catch a draft-night failure:

- **Money conservation (Hypothesis):** `Σ spent + Σ remaining == $2,000` after any sequence
  of adds/removes/edits, `spent` including keepers. With overrides present, reconciles to
  `$2,000 + Σ override_deltas` and the banner reports exactly that figure.
- **Case A / Case B equivalence:** same draft, keepers pre-loaded vs. arriving as the first
  20 ordinary picks — every derived output bit-identical. The strongest single guarantee
  that draft night works either way.
- **Keeper de-duplication:** any interleaving of manual keeper entry and matching real pick
  counts each keeper exactly once; no team ever exceeds 2.
- **Slot totals:** remaining starting slots == 80 **and** remaining roster spots == 140.
  Assert both — a test checking one passes while the other is wrong.
- **DP == CBC:** the fast optimizer agrees with the ILP oracle across thousands of states.
- **2QB check:** QB replacement level materially higher than a 1QB league; if QB1 prices like
  a 1QB league, the model is wrong.
- **Ceremonial contamination audit:** deliberately misclassify one ceremonial pick as
  `COMPETITIVE` and confirm the distortion is *detectable* — proving the filter is
  load-bearing rather than decorative.
- **Perf:** full recompute p99 < 200ms; pick-to-pixel p99 ≤ 2s.
- **Legibility:** can the walk-away number be read from three feet away.

---

## Blockers — need the user

1. **Sleeper username or `league_id`.** Requested but not captured. Blocks `league_id`,
   `draft_id`, `roster_id`, and the settings tripwire. Everything else can start without it.
2. **Network policy.** `api.sleeper.app` and `api.sleeper.com` are denied at this
   environment's egress proxy (403 on CONNECT; GitHub and PyPI work). The user chose to widen
   it — that is done in the Claude Code on the web environment settings, not by me. Fallback
   if it can't be widened today: I ship a self-contained discovery script the user runs
   locally and commits the fixtures back. Sprint 0's discovery spike cannot complete either way
   without one of these.
3. **Mock draft `draft_id`** when their simulated Sleeper draft finishes — the Sprint 1 gate
   fixture.

One standing note: the finished tool runs on the user's laptop on draft day. They will need
Python 3.12 + uv and Node + pnpm working locally, and that should be confirmed on Sept 1,
not discovered on Sept 4.
