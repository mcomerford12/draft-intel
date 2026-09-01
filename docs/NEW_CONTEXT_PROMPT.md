# Prompt for a fresh context

Paste everything below the line into a new session.

---

You're picking up `draft-intel`, a fantasy football auction draft tool, mid-build. The
previous session stopped deliberately after three failed review rounds.

**First action: read `docs/HANDOFF.md` in full.** It is current as of 2026-09-01 and is the
single source of truth for status. Then skim `docs/KANBAN.md` for the board and the six
recorded verdicts.

- **Repo:** `mcomerford12/draft-intel`
- **Branch:** `di-044-round2-fixes` — the current tip. Stacked: `di-044` → `di-042-review-fixes`
  → `di-000-process-scaffold` → `sprint-1-data-spine` → `sprint-0-discovery` → `main`.
- **Domain in one line:** 10-team, $200, full-PPR, **2QB** Sleeper auction; every team keeps 2
  players at `floor(0.75 × Sleeper auction value)`.
- **Deadline:** the draft is **Sat 2026-09-05, 21:00 ET** (Sleeper `start_time`).

## Where things stand

The data spine (Sprint 1) works: `make replay` reproduces every team's budget to the dollar
($1,979 spent / $21 left / $549 keeper spend), the golden file has been independently
re-derived three times, crash recovery survives a real `SIGKILL`, and CI is deterministic at
118 tests.

It has also been **REJECTED three times** by independent code review and adversarial
evaluation, and several silent-money defects remain open. **Sprint 2 — the priced board — has
never been started.**

## Your task, in this order

1. **Finish the one open money-safety defect in handoff §4.1**: a duplicate `pick_no` still
   loses its money, surfaced only as a reject line with no alert and a wrong total reported as
   if it were right. The other two (negative amounts, `FrozenDict.__ior__`) are closed in
   commit `0da8214`.
2. **Then stop working on Sprint 1.** Record §4.2 and §4.3 as known-open. They are all
   live-ingestion robustness and none of them touch the priced board.
3. **Build Sprint 2** — cards DI-026 → DI-039, groomed with dependencies in `docs/KANBAN.md`.
   One review pass per card, not two.
4. **The goal is `make prep`:** an estimated priced board with per-player walk-away prices, a
   tier sheet, the keeper surplus board and the QB endgame plan — printable, in the user's
   hands, with time left for them to argue with it. That is worth more on the night than
   anything else in this repo.

## Read handoff §5 before writing any code

The previous session's failure mode was writing tests that could not fail: two tautological
property tests, a Case A/B gate that passed with the classifier replaced by a constant, a
revert-chain test that stopped at the exact depth where the bug was invisible, and a commit
message claiming a repair that was never made. Concretely:

- **Validate every new regression against the prior commit**, with `PYTHONPATH` forced to the
  old `src` — the editable install otherwise resolves to the new source and the check passes
  spuriously.
- **For any assertion, ask what it would look like if the code were wrong.** If you cannot
  construct that case, it is probably an identity.
- **Wire the fix, then prove the wire.** Three separate fixes shipped connected to nothing.
- Assume the newest code is the least reviewed and most likely to be wrong.

## Non-negotiables (details in handoff §8)

`draft_slot` is the canonical team key, never `roster_id`. No keeper branch in the money
ledger. Never persist or cache `competitive_seq`. `keeper_inflation` and `market_inflation`
are different quantities and are never merged. Never hardcode player names, teams, tiers or
league settings outside `config/`. Never touch Sleeper's internal websocket or GraphQL.

## Blocked on the user — not fixable in code

Six of ten managers have not joined the league, so the tool **cannot reach the real draft at
all** (DI-043), and the commissioner needs to re-save the draft settings, which currently
contradict the league's own roster settings (DI-004). Both are in handoff §6. The first is a
strong argument for prioritising the offline priced board over live ingestion.
