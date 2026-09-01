# Kanban Board

Single source of truth for work state (charter §7). Updated at every state transition.

**Columns:** `Backlog → Ready → In Progress → In Review → In Eval → Done`, plus `Blocked`.
**WIP limits:** In Progress ≤ 3 · In Review ≤ 2 · In Eval ≤ 2. If a limit is hit, finish work
before starting work.

**Git discipline (§7):** branch per card (`di-014-pick-reversal`), no direct commits to `main`,
conventional commits, squash-merge only after both verdicts, tag a release at every sprint gate.

**Deadline:** draft is **Sat Sept 5 2026, 9:00 PM ET** (per Sleeper `start_time`; the user said
9/4 — worth confirming). The charter's ≥2 days of slack before draft day is not achievable.

---

## Status summary

| Sprint | State | Gate |
|---|---|---|
| Sprint 0 — Discovery & scaffolding | ⬜ In Review (PR #1) | Fixtures + findings ✅, league validated ⚠️ (fails, see DI-004) |
| Sprint 1 — Data spine | ⬜ In Review (PR #2) | Replay exact ✅, Case A/B bit-identical ✅, CI green ✅ |
| Sprint 2 — Intelligence core | ⬜ Ready | `make prep` priced board, reviewed by a human |
| Sprint 3 — Cockpit | ⬜ Backlog | Playwright 160-pick replay, p99 ≤ 2s |
| Sprint 4 — Hardening | ⬜ Backlog | 60-minute rehearsal ×2 |

---

## Blocked

### [DI-004] League settings contradict themselves — commissioner action required
- **Sprint:** 0 · **Owner:** user/commissioner · **Size:** S
- `league.roster_positions` says 2 QB / 0 DEF / 6 BN / 16 slots.
  `draft.settings` says 1 QB / 1 DEF / 5 BN / 15 rounds. Also `max_keepers: 1`, not 2.
- **Why blocking-ish:** whether QB slots are 1 or 2 is the largest single input to the
  valuation model. The tool boots on `roster_positions` (ADR-0002) and warns, so development
  is unblocked — but the *league* is not correct until the commissioner re-saves.
- **Acceptance criteria:**
  - [ ] Commissioner re-saves draft settings; `draft.settings` agrees with `roster_positions`
  - [ ] `max_keepers` set to 2
  - [ ] `make smoke` reports zero warnings

---

## Done — Sprint 0 (PR #1, `sprint-0-discovery`)

| ID | Card | Notes |
|---|---|---|
| DI-001 | API discovery spike against live 2026 season | 9 findings, `docs/api-findings.md` |
| DI-002 | Locate real `league_id` / `draft_id` / `roster_id` | league `1391959336820953088`, roster_id 3 |
| DI-003 | Resolve 20 keepers to `player_id` confirming by position | Found a collision the charter missed: Lamar Jackson QB vs CB |
| DI-005 | Determine whether an auction-value field exists for 2026 | **It does not.** ADP only. Forces observed-price design |
| DI-006 | Keeper reconnaissance (Case A vs Case B) | Mock is a clean Case B fixture |
| DI-007 | Reproduce Appendix A structural findings independently | Verified: 7/6/7/0/0, 80 vs 140, AJ/Mason/Burt |
| DI-008 | Commit fixtures | `fixtures/`, trimmed but retaining name collisions |
| DI-009 | Refined charter: contradictions + technical corrections | `docs/PLAN.md`, `docs/DECISIONS_FOR_REVIEW.md` |

## Done — Sprint 1 (PR #2, `sprint-1-data-spine`)

| ID | Card | Notes |
|---|---|---|
| DI-010 | Repo scaffold: uv, ruff, mypy --strict, pytest, `make ci` | |
| DI-011 | Config tripwire, graded blocking/warning | ADR-0002 |
| DI-012 | Pydantic models + event type union | |
| DI-013 | Async Sleeper client: retry, backoff, breaker, 1s floor | |
| DI-014 | SQLite store, WAL, append-only event log | |
| DI-015 | Keeper manifest load + `player_id` resolution | |
| DI-016 | Identity: slot ↔ roster_id ↔ owner, late-bound | |
| DI-017 | Poller + snapshot diffing → events | Handles undo, amend, pause |
| DI-018 | `pick_class` engine + `competitive_seq` | Manifest match outranks `is_keeper` |
| DI-019 | Ledger: `fold(replay(events))` | No keeper branch anywhere |
| DI-020 | Override events + supersession/de-duplication | |
| DI-021 | Crash-restart recovery including overrides | |
| DI-022 | Replay harness | |
| DI-023 | Case A synthesis + equivalence test | **Blocking gate — passes** |
| DI-024 | Property test suite | 11 properties |

---

## In Progress

### [DI-025] Process scaffolding: kanban, ADRs, agent definitions
- **Sprint:** 0 (retroactive) · **Owner:** orchestrator · **Size:** S
- **Why:** charter §8 lists `.claude/agents/`, the ADR template and `docs/adr/0001` as Sprint 0
  deliverables. They were skipped; commit messages already reference ADR numbers that did not exist.
- **Acceptance criteria:**
  - [x] `docs/KANBAN.md` exists and reflects true state
  - [x] ADR template + ADR-0001..0004 written
  - [x] `.claude/agents/` defines the §6 roster with tool allowlists
  - [x] Independence rules stated in a form an agent can follow

---

## Ready — Sprint 2 (Intelligence Core)

Cards are ordered by dependency. Each gets its own branch and PR.

| ID | Card | Owner | Size | Depends |
|---|---|---|---|---|
| DI-026 | Projections ingestion + apply league `scoring_settings` to raw stats | quant | M | — |
| DI-027 | `MarketValueProvider` interface + ADP-curve, CSV, internal-baseline impls | quant | M | 026 |
| DI-028 | Keeper slot assignment (greedy: base slot, then FLEX) | quant | S | 026 |
| DI-029 | Four replacement baselines per ADR-0001 mapping table | quant | L | 028 |
| DI-030 | Dual valuation: `market_value` and `baseline_value` + 3 invariants | quant | L | 029 |
| DI-031 | Keeper surplus board + structural `keeper_inflation` figure | quant | M | 030 |
| DI-032 | Live `market_inflation`, overall and per position | quant | M | 030 |
| DI-033 | Skew: market and edge, all aggregations | quant | M | 030 |
| DI-034 | Opponent max-bid and affordability engine | quant | S | 030 |
| DI-035 | DP roster optimizer + CBC oracle equivalence test (ADR-0003) | quant | L | 030 |
| DI-036 | Walk-away curves, precomputed per player | quant | M | 035 |
| DI-037 | Manager tendency profiles (keyed on `competitive_seq`) | quant | M | 033 |
| DI-038 | Value override plumbing: per-player, positional multiplier, blacklist | quant | M | 030 |
| DI-039 | `make prep` — the priced board and printable report | quant | L | 031,036 |

**Sprint 2 gate:** `make prep` produces the full estimated priced board against the real keeper
manifest and **a human has reviewed it**. Money-conservation invariants hold. Walk-away recompute
p99 < 200ms. The 500-run Monte Carlo and the p<0.01 bot gate are retained per the full-charter
decision, and are cut item #1 if the schedule slips.

## Backlog — Sprints 3–5

Epic level only until Sprint 2 closes.

- **Sprint 3 — Cockpit:** FastAPI + WebSocket · React cockpit per §5 · nomination entry +
  reconciliation · override UI and inspector · three-way visual badging · keeper arming switch
  with `N/20` readout · λ slider · keyboard map · charts
- **Sprint 4 — Hardening:** chaos suite · offline mode · snapshot/restore · `RUNBOOK.md` ·
  `DRAFT_DAY_CHEATSHEET.md` · 60-minute rehearsal run as both Case A and Case B
- **Sprint 5 — Stretch:** nomination advisor · post-draft report · opponent bid modelling
