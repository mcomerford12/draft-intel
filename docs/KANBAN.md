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
| Sprint 1 — Data spine | 🟥 **REJECTED again** (PR #2, #4) — see DI-EVAL-2 | Replay exact ✅, CI green ❌ (2 of 6 clean runs fail), Case A/B gate no longer vacuous ✅ but breaks on a stale manifest ⚠️ — 3 blocking |
| Sprint 2 — Intelligence core | ⬜ Ready | `make prep` priced board, reviewed by a human |
| Sprint 3 — Cockpit | ⬜ Backlog | Playwright 160-pick replay, p99 ≤ 2s |
| Sprint 4 — Hardening | ⬜ Backlog | 60-minute rehearsal ×2 |

---

## Blocked

### [DI-043] Six managers have not joined the league — manifest cannot fully resolve
- **Sprint:** 1 · **Owner:** user/commissioner · **Size:** S · **Surfaced by:** DI-EVAL-1 B1
- Only 4 of 10 managers have joined, so slot-to-owner resolves 8 of 20 keeper keys against
  the real league. `manifest_keys(require=20)` now raises loudly rather than silently
  classifying the other 12 keepers as competitive bids, but the tool cannot run against the
  real draft until the remaining six join: **Jake, Connor, Keenan, Willie, Burt, TD.**
- Their Sleeper display names are also unknown until then, so `config/owners.yaml` cannot be
  completed. The four known are `mattchupiccu`, `ajthebeard`, `MasonWAlpert`, `steeveegee300`.
- **Acceptance criteria:**
  - [ ] All 10 managers joined; `build_identity(...).is_complete(10)` is true
  - [ ] `config/owners.yaml` maps all 10 manifest owners to display names
  - [ ] `manifest_keys(require=20)` resolves without raising

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

## In Review

### [DI-040] Sprint 1 code review verdict: REJECT — 12 blocking findings

- **Sprint:** 1 · **Owner:** data-engineer · **Reviewer:** code-reviewer
- **Verdict: REJECT** (1st of 2 — a second rejection escalates to the orchestrator for scope
  renegotiation rather than a third attempt at the same approach).
- Every finding reproduced by execution, not inferred from reading.

**Blocking**

- [ ] B1 `ledger.py:45,67,74` — `fold` iterates `events` twice; a generator yields empty state,
      no exception, no alert. `f(events)` is not total over its own declared `Iterable` type
- [ ] B2 `ledger.py:67,75` — `Revert` has no kind guard; reverting a `PickObserved` deletes the
      pick and its money. `OVERRIDE_KINDS` (`models.py:132`) was defined and never imported
- [ ] B3 `ledger.py:75` — `Revert` of a `Revert` is a silent no-op; undo-of-undo fails
- [ ] B4 `models.py:62` — `seq` defaults to 0, so `Revert(target_seq=0)` neutralises every
      unstamped event; no seq-uniqueness check anywhere
- [ ] B5 `ledger.py:74` — fold orders by list position, not `seq`. `[Removed, Observed]`
      resurrects a removed pick; competing `ManualKeeper`s resolve last-by-position
- [ ] B6 `ledger.py:94-99` — slot mismatch double-counts a keeper, silently.
      `classify.py:74` `dict()` also hides same-slot duplicates from `reconcile`
- [ ] B7 `ledger.py:116-121` — `competitive_seq` renumbers every later pick on a mid-draft
      `Reclassify` or `PickRemoved`; unusable as a stable time-series key (blocks DI-037)
- [ ] B8 `poller.py:57-64` — an out-of-range slot raises out of `parse_picks` and kills the
      poll cycle, contrary to its own docstring
- [ ] B9 `poller.py:16-29,43-44` — `"35.0"`, `"$35"` parse to $0; a pick missing `player_id`
      is dropped with its money. Nothing surfaces either
- [ ] B10 `test_properties.py:60-64,69-79` — the money-conservation properties are tautologies.
      `remaining` is defined as `budget - spent`, so the identity holds for any `spent`
- [ ] B11 `test_replay_gate.py:94-98` + `harness.py:53-67` — the Case A/B gate is vacuous:
      it passes with the classifier replaced by a constant function. `to_case_a` flips only
      `is_keeper`, which never reaches `DerivedState`
- [ ] B12 `test_properties.py:145-156` — diff round-trip only tests the empty-previous case;
      `poller.py:82,85` (amend/remove emission) have zero coverage

**Major** — M1 1s rate floor unenforced on the retry path (measured 502ms gap) and under
concurrency (4 calls → 3 simultaneous); `client.py:78` uncovered · M2 4xx retried contrary to
docstring; 404 resets the breaker · M3 no over-roster alert, and
`test_store_and_client.py:60` enshrines a 17-slot roster as expected · M4 `DerivedState.teams`
is a mutable dict inside a frozen model · M5 league settings hardcoded (`classify.py:94`,
`cli.py:29-31,53,70`) · M6 `config/league.yaml` referenced by the error message and by
ADR-0002 but does not exist · M7 keeper-limit property fired 1 time in 200 examples · M8
retention-price property restates the implementation character for character · M9 `pick_no`
is unsafe as a diff key under renumbering · M10 four production dependencies with no ADR

**Verified clean** — golden numbers independently reproduced from the fixture by a script
importing none of the project code; no `roster_id` keying; no runtime name matching; no keeper
branch in the money ledger; no websocket/GraphQL; breaker counts one logical call as one
failure; ruff, mypy --strict, 55 tests, 97% coverage all as claimed.

### [DI-042] Fix all blocking findings from DI-040 and DI-EVAL-1
- **Sprint:** 1 · **Owner:** data-engineer · **Size:** L · **Branch:** `di-042-review-fixes`
- **Status:** fixes applied, CI green (82 tests, 97%). Awaiting re-review and re-evaluation.
- 13 of the new regression tests were run against commit `fa4f177` in a worktree and **fail
  there**, confirming they encode the defects rather than restating the fix.
- **Blocking findings closed:**
  - [x] B1 `fold` consumes `events` once; generators fold identically to lists
  - [x] B2 `Revert` refuses any non-override target and alerts; `OVERRIDE_KINDS` now wired
  - [x] B3 a `Revert` may itself be reverted, reinstating the override
  - [x] B4 `UNSTAMPED` named; `Revert(target_seq=0)` refused; duplicate seq alerts
  - [x] B5 fold orders by `seq`, not list position
  - [x] B6 supersession keys on `player_id` alone; slot mismatch alerts, counted once
  - [x] B7 `competitive_seq` documented as recompute-only, never to be cached; coherence tested
  - [x] B8 malformed rows never raise out of `parse_picks`
  - [x] B9 `parse_amount` reads `"35.0"`, `"$35"`, `"1,200"`; everything unreadable is surfaced
        through a new `ParseResult.rejects` channel
  - [x] B10 money properties compare `spent` against an independent replay of the log
  - [x] B11 Case A gets an empty manifest and Case B the full one, so each case relies on the
        mechanism it would really have; a companion test proves the gate is not vacuous
  - [x] B12 diff round-trip now runs between arbitrary snapshots; amend/remove branches covered
  - [x] eval-B1 roster/user fallback for slot-to-owner; `manifest_keys(require=)` raises
  - [x] eval-B2 unknown slots alert; every adjustment lands on a team so reconciliation holds
  - [x] eval-B3 covered by B6
- **Major also closed:** M1 rate floor holds across retries and under concurrency ·
  M2 4xx no longer retried, 404 no longer clears the breaker · M3 over-roster and
  underfunded-team alerts · M4 `teams` exposed as a `Mapping` · M6 `config/league.yaml`
  now exists and is loaded · keeper under-count alerts via `expect_keepers`
- **Deferred with reason:** M5 (some league constants still inline in `cli.py`, a Sprint-1
  hand harness) · M9 partially — the diff now emits remove+observe on a `pick_no` that
  changes player, but `Reclassify` still keys on `pick_no` · M10 dependency ADR not written

### [DI-041] Independence enforcement is weaker than claimed
- **Sprint:** 0 · **Owner:** orchestrator · **Size:** S
- DI-025 claimed `code-reviewer` and `evaluator` "have no write tools, so the rule that they
  cannot author what they assess is enforced by the allowlist rather than by instruction."
  **That is false.** Both carry `Bash`, which writes files. The reviewer voluntarily declined
  to write; the evaluator wrote its verdict into `docs/KANBAN.md` directly.
- Not harmful here — a verdict is what we wanted — but the guarantee does not exist.
- **Acceptance criteria:**
  - [ ] Either remove `Bash` from both, or restate the independence rule as convention
  - [ ] Do not describe allowlist enforcement that is not actually enforced

---

## In Eval

### [DI-EVAL-3] Sprint 1 gate — adversarial re-evaluation of `di-044-round2-fixes`

- **Verdict: REJECTED.** 1 blocking, 4 major, 4 minor. **This is the third eval rejection**, and
  the escalation rule the board states after DI-EVAL-2 (orchestrator scope renegotiation, not a
  further pass at the same approach) is now overdue. Say plainly what is true: this round is a
  large improvement. **All three DI-EVAL-2 blockers and all three DI-EVAL-1 blockers are closed
  in the production path and survive mutation testing.** What blocks is one defect raised for the
  third consecutive time and left open, one new defect in this round's own code, and a minimum
  bar delivered 3.5 of 6.
- Every finding below was produced by running the artifact. Nothing is inferred from reading.
  `docs/PLAN.md`, `docs/HANDOFF.md` and commit messages were not read.

#### The suite is now deterministic — DI-EVAL-2 B2 closed

**12 of 12 clean runs green**, each from a freshly deleted `.hypothesis`: 8 x `uv run pytest -q`
and 4 x full `make ci` (`ruff check`, `ruff format --check`, `mypy --strict`, `pytest`).
**92 passed, 96% coverage.** DI-EVAL-2 measured 4 of 6. `parse_amount` is now total: zero raises
across 200,000 random hostile strings plus a hand-built adversarial list
(`inf/INF/-inf/infinity/nan/1e400/1e-400/0x20/1_000/٣٥/１２３/"9"*4400/½/∞/`, floats, bools,
bytes, complex, `list`, `dict`, bare `object()`). `parse_pick` never raised on any of 14 hostile
row shapes. Criterion 16's parser contract is genuinely met.

#### Independently re-derived and PASSING

Golden numbers re-derived from `fixtures/picks.json` by a script importing none of the project
code: per-slot `(picks, spent)` = `{1:(16,199), 2:(16,200), 3:(16,195), 4:(16,200), 5:(16,200),
6:(16,200), 7:(16,200), 8:(16,200), 9:(16,185), 10:(16,200)}`, total 1979, keeper spend
(`pick_no<=20`) 549, `is_keeper` true on 0 of 160 rows, 160 distinct `pick_no`. `uv run python -m
draft_intel.cli replay` reproduces all of it to the dollar.

| # | Criterion | Result |
|---|---|---|
| 1 | Replay reproduces every roster and budget to the dollar | **PASS** — matches the independent derivation exactly |
| 2 | Kill mid-replay, resume, identical state incl. overrides | **PARTIAL** — real `SIGKILL` at pick 77 (exit 137), 80 events survived, byte-exact reload, resume to 240 events folds to 1979 with `override_delta -15` and the reverted `ManualKeeper` absent. But `DerivedState.rejects` does not survive the store round-trip — see MAJOR-3 |
| 3 | Correction decrements from the corrected baseline | **PASS** — budget 185 / spent 195 / remaining -10; order-independent; a second correction stacks from the corrected baseline (185 -> 175) |
| 4 | Removing a pick restores budget and slot | **PASS** |
| 5 | Amending an amount updates derived state | **PASS** — spend 50 -> 61, `filled_slots` unchanged |
| 6 | Case A / Case B bit-identical | **PASS** on the fixture and its twin; **PARTIAL** on the renumbered twin — see MAJOR-4 |
| 7 | Keeper counted exactly once under any interleaving | **PASS** — see the double-count audit below |
| 8 | Money conservation / exact reconciliation | **PARTIAL** — the identity is now structurally exact; one unreported money-loss channel remains, see MAJOR-2 |
| 9 | `max_bid` never strands a team | **PASS** — 0 violations across all 160 prefixes of the fixture |
| 10 | Retention price is `floor(0.75*v)` | **PASS** — 0 divergences from `max(1, floor(Fraction(3,4)*v))` for v in 1..20,000 |
| 11 | Manifest hard alert + roster/user fallback, both production-reachable | **PASS** — see below |
| 12 | Out-of-league slots alerted, excluded from `override_delta`, no phantom team | **PASS** |
| 13 | Supersession and alerting on `player_id` across teams | **PASS** |
| 14 | Alerts on keeper under-count, roster overflow, `remaining < open_slots` | **PASS** |
| 15 | The max-bid test states the invariant it actually means | **PASS** — see below |
| 16 | Ingestion never raises; unreadable rows surface where a consumer looks | **PARTIAL** — parser contract met; see MAJOR-2 and MAJOR-3 |

**Criterion 11 is closed in production, verified against the LIVE API.** `uv run python -m
draft_intel.cli smoke` reaches Sleeper and prints:
`identity : 4/10 slots resolved [(1,'MasonWAlpert'), (2,'ajthebeard'), (3,'mattchupiccu'),
(4,'steeveegee300')]` — resolved through `slot_to_roster_id -> rosters.json -> users.json`, the
fallback DI-EVAL-2 M5 reported as reachable from no entry point — followed by
`BLOCKER unmapped draft slots: [5,6,7,8,9,10]` and `BLOCKER resolved 8 of 20 keeper keys; owners
with no draft slot: ['Burt','Connor','Jake','Keenan','TD','Willie']`. `cli.replay` passes
`require=teams*keepers_per_team`. `reconcile()` is now called from `cli.replay` (DI-EVAL-2
minimum bar item 4, first half).

**Criterion 15 is closed.** `test_max_bid_never_strands_a_team` now guards on
`remaining >= open_slots` and pins the broke case separately. Re-run of the exact DI-EVAL-2
falsifier — fixture pick 21 changed from $37 to $180 — the test now **passes**, and the state it
produces (`slot 5 spent=334 remaining=-134 open=9 max_bid=0`) raises
`slot 5 has $-134 for 9 open spots - cannot fill its roster at $1 each` rather than an assertion
failure.

**Revert chains are correct.** Depths 0..8 all match hand-derivation
(`-40, 0, -40, 0, -40, 0, -40, 0, -40`); DI-EVAL-2's parity table is fully repaired. Branching
chains, dangling targets, self-targets, `target_seq=0`, unstamped reverts and duplicate-seq
reverts all behave or alert.

**The regression tests are load-bearing.** Six mutations injected into an isolated copy of the
tree with its own venv — **all six caught**: (1) flat single-pass revert cancellation -> 2 failures;
(2) `float()` fallback in `parse_amount` -> 2; (3) `fold` drops `rejects` -> 1; (4) `UNSTAMPED`
sorts first -> 1; (5) orphan picks mint teams and orphan adjustments counted -> 2; (6) supersession
back to `(slot, player_id)` -> 2. Restored tree: 92 passed.

**Contamination audit — the filter is load-bearing.** Case B (`fixtures/picks.json`) vs its Case A
twin under the split-mechanism gate (empty manifest for A, full manifest for B): `model_dump()`
identical, keeper spend 549, competitive 140 both sides. Non-vacuity confirmed by breaking each
mechanism in turn — A-payload with empty manifest, A-payload with a constant `COMPETITIVE`
classifier, and with a constant `KEEPER` classifier — **all three diverge**. Deliberately dropping
one manifest key (pick 9, Lamar Jackson QB $29, slot 5) is detectable everywhere: competitive
140 -> 141, keeper spend 549 -> 520, competitive QB count 13 -> 14, **competitive QB spend
157 -> 186 (+18%, the position that matters most in 2QB)**, all 140 `competitive_seq` indices
shift, Case A/B equality breaks. `total_spent` unchanged at 1979 — there is genuinely no keeper
branch in the ledger.

**Keeper double-count audit — passes.** `ManualKeeper(slot=3, P, $30)` + pick `P` on slot 4:
slot 3 $0, slot 4 $30, `total_spent` 30, one `superseded` entry, one `SLOT MISMATCH` alert, and
identical output under both event orderings. Removing the pick reinstates the manual entry at
slot 3 for $30 — counted once, never twice, never zero. The triple-signal fixture (manual entry
+ `is_keeper` pick + `Reclassify`, all for the same keeper) yields `filled_slots 1, spent 30,
keepers 1, open_slots 15` — removed from supply and from demand exactly once each.

**Standing audit — 2QB: NOT AUDITABLE HERE, unchanged from DI-EVAL-1 and DI-EVAL-2.** There is
still no value model. Inputs re-derived independently: `league.roster_positions` gives 2 QB x 10 =
**20 starting QB slots**; the keeper slate is `{QB:7, WR:7, RB:6}`, so **13 QB slots remain to be
bought**; the fixture's 140 competitive picks contain 13 QBs for $157. `config/league.yaml` and
`LeagueConfig.starters` both say `QB: 2` and the `draft.settings` mismatch is still WARNING-graded
and still live (`smoke` prints `draft.slots_qb: expected 2, draft says 1`). **Re-run at DI-030.**

---

#### BLOCKING

**B1 — Negative amounts are still not refused end to end, on either entry path, with zero alerts.
Raised as DI-EVAL-1 m2, DI-EVAL-2 M3, and written into DI-EVAL-2's minimum bar as item 6. Not
delivered.**

```
fold([obs(pick_no=1, player_id='A', slot=1, amount=-500)], slots=range(1,11))
#   slot 1: spent -500   remaining 700   max_bid 686   alerts ()
fold([ManualKeeper(seq=1, slot=1, player_id='A', amount=-500)], slots=range(1,11))
#   slot 1: spent -500   remaining 700   max_bid 686   alerts ()   rejects ()
ManualKeeper.amount has ge=0?  False
PickSnapshot.amount has ge=0?  False
```

The minimum bar read "`ge=0` on `PickSnapshot.amount` and `ManualKeeper.amount`, **or** an alert on
any negative roster entry." Neither was done. What was done is a complaint string from
`parse_amount` — which reaches `DerivedState.rejects` only on the feed path, and `ManualKeeper`
does not go through the parser at all. `models.py:141-152` calls `ManualKeeper` "the primary path
by which real keeper prices enter the system, not a fallback"; a human typing `-30` into it today
passes **every** guard in the system:

- `fold` alerts on overdrawn, over-roster, underfunded, keeper over/under-count — none fire on a
  negative, because a negative makes a team look *richer*.
- the sign-flipped twin does alert: `obs(..., amount=3000)` gives two alerts. `-500` gives zero.
- `reconcile()` — now wired into `cli.replay` — cannot catch it either: **every `price` in
  `config/keepers.yaml` is `null`** (verified: 20 of 20), which the manifest's own header says is
  the expected state until draft day, and `reconcile` skips the amount comparison when `price is
  None`. Confirmed: `reconcile({1:[('100',-30),('101',20)]}, {1:[('100',None),('101',None)]}) == []`.

The consequence is not a wrong total, it is wrong advice: the cockpit would recommend bidding $686
in a $200 league, and `max_bid` is the number this whole sprint exists to compute. This is the
charter's named failure mode — a plausible-looking number that has been wrong since 7:40pm — and
it is one keystroke away on the path the model docstring designates as primary.

#### MAJOR

**M1 — NEW DEFECT, this round's code: `FrozenDict` does not block `|=`. Derived state can be
mutated in place, and the class exists for no other reason.**

`models.py:36-66` overrides `__setitem__`, `__delitem__`, `clear`, `pop`, `popitem`, `update`,
`setdefault` — 7 of the 8 mutating `dict` methods. `__ior__` is inherited unblocked:

```python
s = fold([obs(1, 1, 'A', 1, 50)], slots=range(1, 11))
s.teams.__ior__({99: None})          # no exception at all
len(s.teams)  # 11   -- derived state silently corrupted

s2 = fold([obs(1, 1, 'A', 1, 50)], slots=range(1, 11))
s2.total_spent + s2.total_remaining          # 2000
try: s2.teams |= {11: TeamState(slot=11, budget=200, spent=0, roster=(), total_slots=16)}
except ValidationError: pass                 # pydantic refuses the REBINDING, after the fact
sorted(s2.teams)                             # [1..10, 11]
s2.total_spent + s2.total_remaining          # 2200  -- conservation broken in place
```

The `|=` form raises *after* the in-place mutation has already happened, so the model is left
corrupted either way; the direct `__ior__` call is entirely silent. The docstring says "A dict that
refuses mutation at runtime" and "Derived state is only ever changed by appending an event and
refolding." Coverage shows why it was missed: `models.py:51,57,60,66` (`__delitem__`, `pop`,
`popitem`, `setdefault`) are **uncovered**, and `test_derived_state_refuses_mutation` exercises only
`__setitem__`, `clear` and `update` — 3 of 8. This is the same species of finding as DI-041:
a guarantee described in prose that the code does not enforce.

**M2 — Criterion 8 / 16: a duplicate `pick_no` row loses its money on the production CLI path with
no reject, no orphan and no alert. Reproduced end to end.**

The orphan rule closed the phantom-team channel cleanly (verified below), but `parse_picks` keys its
result dict on `pick_no`, so a repeated `pick_no` silently drops one row and its dollars. Injected
into `fixtures/picks.json` in an isolated copy and run through `uv run python -m draft_intel.cli
replay`:

```
baseline : slot 9 Burt 16 picks $185 spent · total spent $1979 · 140 competitive · no REJECT/ORPHAN/ALERT
injected : slot 9 Burt 16 picks $166 spent · total spent $1960 · 140 competitive · no REJECT/ORPHAN/ALERT
```

$19 gone. Roster count still 16, `keepers seen 20/20`, `teams complete 10/10`, `spent + remaining ==
2000` — the loss is inferable **only** from a total that looks slightly wrong, which is verbatim
the failure DI-EVAL-2 minimum bar item 3 was written to close. The rejects channel is otherwise
excellent: the same harness with pick 30's `player_id` removed and pick 31 moved to slot 11 prints
`REJECT pick 30 is missing player_id` and `ORPHAN slot 11 is not one of the league's 10 slots ($34
of picks)` plus the matching ALERT. That path is genuinely wired. This one row shape bypasses it.

**M3 — Criterion 2: `rejects` is lost across a store round-trip. `orphans` survives.**

```
LIVE    : total_spent 1947  rejects ('pick 30 is missing player_id',)  orphans ('slot 11 ... $1 of picks',)
RESUMED : total_spent 1947  rejects ()                                 orphans ('slot 11 ... $1 of picks',)
model_dump() identical? False   (differs on: rejects)
```

`orphans` is re-derived from the event log so it survives; `rejects` is derived from the raw payload
and the store persists only events, so a crash-restart erases the record that a row took its dollars
with it. Criterion 2 says "identical state". `EventStore` is also called by nothing in `src/` — the
resume path exists only as a test — so nothing regenerates it either.

**M4 — Criterion 6 bit-identity still does not survive a pick-number shift. Third eval, unchanged.**

The renumbered Case A twin (competitive picks 1..140, keepers 141..160 — the arrangement
`ledger.py:242-250` names as the *reason* `competitive_seq` exists) gives `model_dump()` inequality,
because `competitive_seq` and `RosterEntry.pick_no` are keyed on `pick_no`. The semantics do hold:
per-team `(picks, spent)` identical, `keeper_spend` 549 both, `total_spent` 1979 both,
`player_id -> competitive index` map identical, no alerts either side. So the design is sound and
the literal criterion is not met. Reported by DI-EVAL-1 and DI-EVAL-2; still nothing in the suite
demonstrates it either way.

#### MINOR

- **m1 — Minimum bar item 4 is half delivered, and the board was not updated instead.** `reconcile()`
  is now wired into `cli.replay` (good, and its output is printed). **`armed` is still set `True` by
  no product code path** — `grep -rn armed src/` finds only the dataclass field, its docstring and
  its own `if`. The bar's alternative was "move them to Sprint 3 in the board and stop describing
  them in DI-042 as closed backstops." `git diff di-042-review-fixes..di-044-round2-fixes -- docs/`
  is **empty**: `docs/KANBAN.md` is byte-identical. There is no DI-044 card for the artifact under
  evaluation; the Status summary still reads "REJECTED again ... 3 blocking"; DI-042 still claims
  "CI green (82 tests, 97%)" against an actual 92 tests / 96%. Charter §7 makes this file the single
  source of truth for work state, updated at every state transition.
- **m2 — Minimum bar item 5 delivered 1 of 3, for the second consecutive round.** The gate max-bid
  test is fixed (criterion 15, PASS). `test_manual_keeper_counted_exactly_once`
  (`test_properties.py:161`) still passes **one** drawn `slot` to both the pick and the manual entry,
  so the mismatch case — DI-EVAL-1's B3, the defect that motivated the request — is still unexercised
  there. `test_ledger_reconciles_exactly_with_overrides` (`test_properties.py:104`) still draws
  `st.integers(1, 10)`, still exactly the in-league range, so it still cannot reach the orphan rule
  it would now be testing. The diff for this file this round adds only an `@example` and the
  `Fraction` rewrite — both good, neither requested.
- **m3 — The stale-manifest divergence is unchanged (DI-EVAL-2 M1).** A keeper whose `player_id`
  changed in the feed after the manifest was written: `manifest_keys(require=20)` is fully satisfied,
  and Case A gives `keeper_spend 549 / competitive 140 / alerts ()` while Case B gives
  `520 / 141 / ('slot 5 holds only 1 of 2 keepers',)`. Not bit-identical. Case B's single alert
  exists only because `expect_keepers=True`, which only `cli.replay` passes; **Case A raises no alert
  at all even with `expect_keepers=True`**, because `is_keeper` still marks all 20. The designed
  backstop for exactly this is `armed`, which is inert (m1).
- **m4 — Assorted.** Two `ManualKeeper`s for the same player on different slots with no pick still
  charge $60 for one $30 keeper (it alerts `player P is held by slots [3, 5]`, which is the right
  call, but the money is still double-counted). `cli.replay` passes `require=` but not `teams=` to
  `manifest_keys`, so the owners-collapsed-onto-one-slot guard is exercised only by `smoke`.
  `cli.smoke` prints `BLOCKER` for an unresolvable manifest and an incomplete identity but still
  returns exit 0. The orphan message labels `ManualKeeper` money as "of picks". `draft_slot: 1.5`
  is silently truncated to slot 1 by `int()`. `ledger.py:124-125,185,192,303` (four alert branches,
  including the manual-entry-on-an-orphan-slot path) are uncovered.

#### Minimum bar to re-submit

1. `ge=0` on `PickSnapshot.amount` and `ManualKeeper.amount`, **or** an alert in `fold` on any
   negative roster entry, plus a test that `max_bid` cannot exceed `budget`. (B1, third request)
2. Override `__ior__` on `FrozenDict` and test all eight mutating `dict` methods, not three. (M1)
3. Either persist `rejects` alongside the log, or state in the criterion-2 test that it is an
   ingestion artifact and not part of recovered state. (M3)
4. Deliver the two outstanding property-test changes from DI-EVAL-2 item 5 as written: two
   independent slots in `test_manual_keeper_counted_exactly_once`, and an out-of-league range in
   `test_ledger_reconciles_exactly_with_overrides`. (m2, second request)
5. Wire `armed`, or reclassify it on the board. Either way, write a card for this branch and correct
   the DI-042 numbers and the Status summary. (m1)
6. Detect a repeated `pick_no` in `parse_picks` and route it to `rejects`. (M2)

Criteria 1, 3, 4, 5, 7, 9, 10, 11, 12, 13, 14 and 15 are solid and independently confirmed; 2, 6, 8
and 16 pass on their main line and fail only on the edge named above. The suite is deterministic and
its regressions survive mutation. The gap is now narrow and almost entirely about finishing the
previous bar rather than about the design, which is why the escalation this board already called for
after DI-EVAL-2 should happen before a fourth pass.

---

### [DI-EVAL-2] Sprint 1 gate — adversarial re-evaluation of `di-042-review-fixes` @ `21a7617`

- **Verdict: REJECTED.** 3 blocking, 5 major, 6 minor. Every finding below was produced by
  running the artifact. Nothing here is inferred from reading.
- **This is the second eval rejection.** Per the board's own escalation rule the next step is
  orchestrator scope renegotiation, not a third pass at the same approach. The gap is narrow:
  the fix pass genuinely closed 11 of the 12 DI-040 blockers and all three DI-EVAL-1 blockers.
  What it did not close is a new defect it introduced, and one it declared closed but only
  half-built.
- **`make ci` is NOT reliably green.** Measured over 6 runs with a fresh `.hypothesis` each time:
  **2 failed, 4 passed.** DI-042 claims "CI green (82 tests, 97%)". That claim is luck.

#### Independently re-derived and PASSING

Golden numbers re-derived from `fixtures/picks.json` by a script importing none of the project
code: per-slot `(picks, spent)` = `{1:(16,199), 2:(16,200), 3:(16,195), 4:(16,200), 5:(16,200),
6:(16,200), 7:(16,200), 8:(16,200), 9:(16,185), 10:(16,200)}`, total 1979, keeper spend
(pick_no<=20) 549, `is_keeper` true on 0 of 160 rows. `uv run python -m draft_intel.cli replay`
reproduces all of it exactly, and does so identically over 8 consecutive runs.

| # | Criterion | Result |
|---|---|---|
| 1 | Replay reproduces every roster and budget to the dollar | **PASS** — matches the independent derivation exactly |
| 2 | Kill mid-replay, resume, identical state incl. overrides | **PASS** — real `SIGKILL` at pick 77 (exit 137), 80 events survived, byte-exact round-trip, resume to 240 events folds to 1979/6 with `override_delta -15` and the reverted `ManualKeeper` correctly absent |
| 3 | Correction decrements from the corrected baseline | **PASS** — slot 3 budget 185 / spent 195 / remaining -10; order-independent when spliced mid-log |
| 4 | Removing a pick restores budget and slot | **PASS** — and re-observing restores `model_dump()` equality |
| 5 | Amending an amount updates derived state | **PASS** — spend +11, `filled_slots` unchanged |
| 6 | Case A / Case B bit-identical | **PARTIAL** — the gate is no longer vacuous (see below), but breaks under a stale manifest and under a pick-number shift. See MAJOR-1, MAJOR-4 |
| 7 | Keeper counted exactly once under any interleaving | **PASS** — see the three-way audit below |
| 8 | Money conservation / exact reconciliation | **FAIL** — see BLOCKING-3 |
| 9 | `max_bid` never strands a team | **PASS** on behaviour — 0 violations across all 160 prefixes; the shipped *test* of it is still unsound (MAJOR-2) |
| 10 | Retention price is `floor(0.75*v)` | **PASS** — 0 divergences from `max(1, floor(Fraction(3,4)*v))` for v in 1..5000 |

**The regression tests are load-bearing.** Five mutations reverting individual fixes were injected
into an isolated copy of the tree; **all five were caught**: supersession back to `(slot,
player_id)`, removal of the unknown-slot alert, removal of the keeper under-count alert, folding by
list position, and perturbing the revert-of-revert branch. These tests encode the defects.

**DI-EVAL-1 B1, B2, B3 are genuinely closed in the production path**, not merely tested.
`build_identity(real_draft, rosters=..., users=...)` resolves 4 of 10 slots via
`slot_to_roster_id -> rosters.json -> users.json` (`{1:'MasonWAlpert', 2:'ajthebeard',
3:'mattchupiccu', 4:'steeveegee300'}`); `manifest_keys(..., require=20)` raises
`UnresolvedManifest` naming the six absent managers; `cli.replay` passes `require=20`. Unknown
slots alert. Supersession keys on `player_id`. Reviewer M1/M2 also verified empirically: retry
gaps 1.003s/1.002s, four concurrent calls gap 1.0/1.002/1.002s, a 400 is attempted once with 0
breaker credit, a 404 leaves `failures` at 4.

**Standing audit — 2QB: NOT AUDITABLE HERE, unchanged from DI-EVAL-1.** There is still no value
model. Inputs check out: `roster_positions` gives 2 QB x 10 = **20 starting QB slots**; the keeper
slate is `{'WR':7, 'QB':7, 'RB':6}`, so **13 QB slots remain to be bought**; `config/league.yaml`
and `LeagueConfig.starters` both say `QB: 2` and the mismatch is BLOCKING. **Re-run at DI-030.**

**Contamination audit — the filter is load-bearing.** Case B (`fixtures/picks.json`) against its
Case A twin: competitive count 140, by-position count `{K:10, QB:13, RB:47, TE:19, WR:51}`,
by-position spend `{K:10, QB:157, RB:553, TE:167, WR:543}`, keeper spend 549, and the full
`competitive_seq` map — **all identical**. Dropping one manifest key (pick 9, Lamar Jackson) is
detectable everywhere it should be: competitive 140 -> 141, keeper spend 549 -> 520, QB spend
**157 -> 186 (+18%, the position that matters most in 2QB)**, and all 140 `competitive_seq` indices
shift. `total_spent` is unchanged at 1979 — there is genuinely no keeper branch in the ledger. Same
result via a `Reclassify` event.

**Keeper double-count audit — passes.** The fixture on which a naive implementation double-counts
(manual entry and feed disagree about the slot) is handled once: `ManualKeeper(slot=3, P, $30)` +
pick `P` on slot 4 gives slot 3 $0, slot 4 $30, `total_spent` 30, one `superseded` entry and a
`SLOT MISMATCH` alert. Removing the pick correctly reinstates the manual entry.

---

#### BLOCKING

**B1 — Revert chains of odd depth >= 3 silently ignore the revert. Money is wrong; no alert.**

`_resolve_reverts` (`ledger.py:73-112`) builds `cancelled` as *every revert that is targeted by
another revert*, then skips those and `continue`s past any revert whose target is itself a revert.
The result: for a chain of length >= 2, **nothing is ever reverted**, which is correct only at even
depths. Undo -> redo -> undo, an entirely ordinary sequence in a live override UI, keeps the
override applied:

```python
from draft_intel.domain.ledger import fold
from draft_intel.models import BudgetAdjustment, Revert
ev = [BudgetAdjustment(seq=1, slot=1, delta=-40),
      Revert(seq=2, target_seq=1),   # undo the correction
      Revert(seq=3, target_seq=2),   # put it back
      Revert(seq=4, target_seq=3)]   # take it off again
s = fold(ev, slots=range(1, 11))
# override_delta -40   budget 160   alerts ()
# expected:     0             200
```

Measured parity table (`expected` = correct, `actual` = shipped):

| depth | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| expected `override_delta` | -40 | 0 | -40 | **0** | -40 | **0** | -40 |
| actual | -40 | 0 | -40 | **-40** | -40 | **-40** | -40 |
| alerts | 0 | 0 | 0 | **0** | 0 | **0** | 0 |

This is new code written for this review round, `ledger.py:101-102` is uncovered, and
`test_revert_of_a_revert_reinstates_the_override` stops at depth 2 — the exact depth at which the
bug is invisible. A silent money error in the module whose own docstring says "Every anomaly raises
an alert."

**B2 — `parse_amount` raises, taking `parse_picks` down. This is DI-040 B8's failure class,
reopened by B9's fix, and it makes the suite red 1 run in 3.**

`poller.py:60` calls `int(value)` on a float without a finiteness check:

```python
from draft_intel.sleeper.poller import parse_picks
parse_picks([{'pick_no':1,'draft_slot':1,'player_id':'A','metadata':{'amount':'inf'}}])
# OverflowError: cannot convert float infinity to integer
```

`'inf'`, `'INF'`, `'-inf'`, `'infinity'` and `'1e400'` raise `OverflowError`; `'nan'`/`'NaN'` raise
`ValueError`. The function's own docstring says "Never raises -- a malformed amount must not take
the poller down mid-draft", and `parse_picks` says it records "rather than swallowing every
malformed entry". Both are false. `poller.py:61` is the single uncovered line in that module.
Hypothesis finds it: **2 of 6 clean `uv run pytest -q` runs failed**
(`test_properties.py::test_amount_parsing_never_raises`). A gate cannot pass with a red suite, and
DI-042's "CI green (82 tests, 97%)" is a statement about which runs were observed.

**B3 — Criterion 8: the rejects channel is dead-ended. Money silently vanishes on the production
replay path while conservation still "holds".**

`ParseResult.rejects` is populated by `parse_picks` and **read by nothing in `src/`**.
`replay_events` (`harness.py:41`) does `parse_picks(ordered[:i]).picks` and discards the rest.
`DerivedState.rejects` (`models.py:222`) is declared and **never assigned anywhere in `src/` or
`tests/`**. `cli.replay` never prints rejects. So DI-042's "everything unreadable is surfaced
through a new `ParseResult.rejects` channel" is true of the parser and false of the system:

```
# fixture with pick 50 missing player_id and pick 51 amount 'fifty-two' (worth $20 and $1)
parse_picks(bad).rejects  -> ['pick 50 is missing player_id',
                              "pick 51 (Justin Herbert): amount 'fifty-two' is unparseable"]
fold(replay_all(bad), slots=range(1,11), classifier=cls, expect_keepers=True)
#   total_spent 1958   (clean fixture: 1979)      picks folded 159   (160)
#   state.rejects ()   state.alerts ()
#   spent + remaining == 2000  ->  True
```

This is also the direct answer to the standing "construct a case where conservation holds
arithmetically but the state is nonsense" audit. It holds because `remaining` is *defined* as
`budget - spent`; a team is $21 richer than reality and short a roster spot, and nothing says a
word. This is the failure mode the charter names as the only one that matters.

#### MAJOR

**M1 — Criterion 6 still breaks under a stale manifest, and both designed backstops are still
inert.** A last-minute keeper swap the manifest does not know about (one keeper's `player_id`
changed in the feed) diverges Case A from Case B while `manifest_keys(require=20)` is fully
satisfied — the eval-B1 guard does not catch this:

```
Case A: keeper_spend 549   competitive 140   alerts ()
Case B: keeper_spend 520   competitive 141   alerts ('slot 5 holds only 1 of 2 keepers',)
BIT-IDENTICAL: False        manifest_keys still resolves 20: True
```

Case B's alert exists only because `expect_keepers=True` is passed, which only `cli.replay` does.
The designed backstop is `KeeperClassifier.armed`, which restores the count to 140 and FLAGs the
pick — and **`grep -rn armed src/` still finds only the dataclass field, its docstring and its own
`if`. It is set `True` by no product code path.** Unchanged since DI-EVAL-1. Likewise
`classify.reconcile()`, the only function that detects a keeper under-count against the manifest,
**is still called by nothing outside `tests/test_reconciliation.py`.**

**M2 — Minimum-bar item 5 was not delivered.**
`test_replay_gate.py::test_max_bid_never_strands_a_team` (line 213) still asserts
`max_bid + (open_slots - 1) <= remaining` with no precondition. It is still false for a broke team
and still green only by fixture luck — changing exactly one amount in the fixture (pick 21 to $180)
makes it fail: `slot 5 spent=334 remaining=-134 open=9 max_bid=0`. Its property-test twin
(`test_properties.py:124`) has the guard, so the shape of the fix was known.
`test_manual_keeper_counted_exactly_once` still passes **one** drawn `slot` to both the pick and the
manual entry (line 158-168) — the mismatch case is still unexercised there.
`test_ledger_reconciles_exactly_with_overrides` still draws `st.integers(1, 10)` (line 101), still
exactly the in-league range. The underlying defects *are* covered elsewhere by named gate tests, so
this is a test-quality failure rather than a coverage hole — but three of three requested changes
were not made.

**M3 — Negative amounts still accepted with no complaint and no alert, and they poison
`max_bid`.** `parse_amount("-500") == (-500, None)`; `PickSnapshot.amount` and `ManualKeeper.amount`
still have no `ge=0`:

```
fold([obs(pick_no=1, player_id='A', slot=1, amount=-500)], slots=range(1,11))
# slot 1: spent -500  remaining 700  max_bid 686  alerts ()
```

The cockpit would advise bidding $686 in a $200 league. A $3000 fat-finger *does* alert twice; the
sign-flipped twin alerts zero times. Raised as m2 in DI-EVAL-1, not on the minimum bar, still open.

**M4 — Criterion 6 bit-identity does not survive a pick-number shift.** The renumbered Case A twin
(competitive picks 1..140, keepers 141..160 — the arrangement `ledger.py` names as the *reason*
`competitive_seq` exists) gives `model_dump()` inequality, because `competitive_seq` and
`RosterEntry.pick_no` are keyed on `pick_no`. The semantics do hold: per-team `(picks, spent)`
identical, `keeper_spend` 549 in both, `player_id -> competitive index` mapping identical, no alerts.
So the design is sound and the literal criterion is not met. DI-EVAL-1 reported this; nothing in the
suite demonstrates it either way.

**M5 — The roster/user fallback is reachable from no product entry point.** `cli.replay` calls
`build_identity(draft, aliases=...)` against `fixtures/draft.json` only — it never passes `rosters`
or `users`, and never touches `real_draft.json`. The fallback works when called directly, but on
draft night nothing in the shipped artifact calls it. Related: `load_league_config` is called only
from `tests/`; `cli._smoke` uses `LeagueConfig()` defaults (declared as deferred M5 in DI-042).

#### MINOR

- **m1** `_ordered` sorts unstamped events (`seq == 0`) **ahead of every stamped event**, which is
  the opposite of arrival order. A stamped `PickObserved(seq=5)` followed by an unstamped
  `PickRemoved` leaves the pick and its money in place. It does alert
  ("removal of pick 1, which is not in the log"), and every store-mediated path stamps first, so
  this is currently unreachable in production — but the comment at `ledger.py:68-69` asserts the
  ordering is deliberate without saying it inverts the intended sequence.
- **m2** `Revert(seq=2, target_seq=2)` (self-targeting) is a silent no-op with no alert.
- **m3** Two `ManualKeeper`s for the same player on different slots with no pick yet still charge
  $60 for one $30 keeper. It alerts (`player P is held by slots [3, 5]`), which is the right call
  since the fold cannot know which is correct, but the money is still double-counted.
- **m4** `test_the_equivalence_gate_is_not_vacuous` computes `broken_a` and `broken_b` with
  *character-identical* expressions (lines 136 and 142); the second assertion adds nothing.
- **m5** `test_pick_on_an_unknown_slot_alerts_rather_than_minting_a_silent_team` still mints the
  team — it asserts `state.teams[11].spent == 5`. The name overpromises; the fix is alert-only, and
  the criterion-8 identity in the sibling test is written as `2000 + override_delta + 200`, i.e.
  the pot is redefined per phantom team rather than the identity being preserved.
- **m6** `test_retention_price_floors_and_clamps` still restates
  `max(1, (value * 3) // 4)` character for character. Only `test_retention_price_boundaries` and the
  independent `Fraction(3,4)` sweep prove anything.

#### Minimum bar to re-submit

1. Fix `_resolve_reverts` to resolve chains by walking them (or by folding reverts in `seq` order
   and toggling), and add a test at depth 3, 4 and 5. Alert on any revert the fold cannot resolve.
2. Make `parse_amount` total. `math.isfinite` guard on the float branch; add `'inf'`, `'nan'`,
   `'1e400'` to `test_amount_parsing_surfaces_what_it_could_not_read` as named cases so the property
   test is not the only thing standing between this and a dead poll cycle.
3. Carry `ParseResult.rejects` through `replay_events`/`replay_all` into `DerivedState.rejects`,
   print them in `cli.replay`, and add a test asserting that a dropped row is visible in final
   state. A row that took money with it must not be inferable only from a total that looks slightly
   wrong.
4. Either wire `armed` and `reconcile()` into a product code path, or move them to Sprint 3 in the
   board and stop describing them in DI-042 as closed backstops.
5. Deliver minimum-bar item 5 from DI-EVAL-1 as written: guard `test_max_bid_never_strands_a_team`,
   draw two independent slots in `test_manual_keeper_counted_exactly_once`, and widen the override
   property test past the in-league range.
6. `ge=0` on `PickSnapshot.amount` and `ManualKeeper.amount`, or an alert on any negative roster
   entry.

Criteria 1, 2, 3, 4, 5, 7, 9 and 10 are solid and independently confirmed, the fixes to DI-EVAL-1
B1/B2/B3 and reviewer M1/M2/M3/M6 are real and survive mutation testing, and the Case A/B gate is
no longer vacuous. What remains is one new silent money bug in the revert code, one contract
violation that makes the suite red, and one fix that stops one function short of the operator.

---

### [DI-EVAL-1] Sprint 1 gate — adversarial evaluation

- **Verdict: REJECTED.** 3 blocking defects, 3 major, 3 minor. All reproduced by running the
  artifact, not by reading it. `make ci` is green (55 passed, ruff clean, mypy --strict clean);
  the suite is green because it does not go where the defects live.
- **Reproductions:** the exact snippets below were run against `HEAD`. Each is 5-10 lines and can
  be pasted into a test file as-is.

#### What was independently verified and PASSES

| # | Criterion | Result |
|---|---|---|
| 1 | Replay reproduces every roster and budget to the dollar | **PASS** |
| 2 | Kill mid-replay, resume, identical state incl. overrides | **PASS** |
| 3 | Correction decrements from the corrected baseline | **PASS** |
| 4 | Removing a pick restores budget and slot | **PASS** |
| 5 | Amending an amount in place updates derived state | **PASS** |
| 6 | Case A / Case B bit-identical | **FAIL — blocking, see B1** |
| 7 | Keeper counted exactly once under any interleaving | **FAIL — blocking, see B3** |
| 8 | Money conservation / exact reconciliation | **FAIL — blocking, see B2** |
| 9 | max_bid never strands a team | **PASS** (the shipped *test* of it is unsound, see M3) |
| 10 | Retention price is floor(0.75 * v), correct at boundaries | **PASS** |

**Golden file is NOT circular.** `EXPECTED` in `tests/test_replay_gate.py` was re-derived from
`fixtures/picks.json` with an independent script that never imports `draft_intel`: summing
`metadata.amount` per `draft_slot` yields exactly
`{1:(16,199), 2:(16,200), 3:(16,195), 4:(16,200), 5:(16,200), 6:(16,200), 7:(16,200), 8:(16,200),
9:(16,185), 10:(16,200)}`, total 1979, and `sum(amount for pick_no <= 20) == 549 ==
EXPECTED_KEEPER_SPEND`. `config/keepers.yaml` carries names only (`player_id: null`) and was not
back-fitted — it diffs against `keepers.original.yaml` on schema and comments, not on personnel.
The 20 manifest keys resolve to exactly pick_no 1..20. Criterion 1 is genuinely earned.

**Criterion 2 was tested with a real SIGKILL**, not by dropping an object as
`test_store_and_client.py` does. A child process appending one event per pick was `SIGKILL`ed at
pick 77 (exit 137); 80 events survived (77 picks + 3 overrides), and all seven event kinds
round-trip byte-exact through `EventStore.load()` (`model_dump()` equality on every one, including
`Revert.target_seq`). Resuming replays the full feed, duplicating 77 `PickObserved` events, and the
fold is idempotent so the final ledger is still correct. Criterion 2 is genuinely earned.

**Criterion 10 was verified against `Fraction(3,4)` for v in 1..5000** — zero divergence from
`max(1, floor(0.75*v))`. Note that `test_properties.py::test_retention_price_floors_and_clamps`
asserts `price == max(1, (value * 3) // 4)`, which is a character-for-character restatement of the
implementation line and proves nothing; only `test_retention_price_boundaries` is real. Criterion 10
passes on the independent check, not on that test.

**Standing audit — 2QB pricing: NOT APPLICABLE to this artifact.** There is no value model in
Sprint 1. The only 2QB surface is `LeagueConfig.starters = {"QB": 2, ...}` and the blocking
tripwire against `league.roster_positions`. The inputs it will need do check out:
`roster_positions` gives 2 QB x 10 teams = 20 QB starting slots, and the keeper slate is
`Counter({'WR': 7, 'QB': 7, 'RB': 6})`, so 13 QB slots remain to be bought. **This audit must be
re-run at the DI-030 gate and cannot be signed off here.**

---

#### BLOCKING

**B1 — Criterion 6 fails silently against the real league. `manifest_keys` resolves to ZERO on
`fixtures/real_draft.json`.**

`build_identity` derives owners *only* from `draft.metadata.slot_name_{n}`. The mock draft has all
ten. The real draft object has none — its metadata is
`{"description": "", "league_type": "1", "name": "GJFL 2026 Auction Draft", "scoring_type": "2qb"}`.
`manifest_keys` then drops every entry (by design: "unmapped owner means the manager has not joined
yet"), the classifier matches nothing, and in Case B all 20 ceremonial keepers become COMPETITIVE:

```
draft.json      : slot_to_owner has 10 entries -> manifest_keys = 20
real_draft.json : slot_to_owner = {}           -> manifest_keys = 0

Case A competitive: 140   keeper_spend: $549
Case B competitive: 160   keeper_spend: $0
BIT-IDENTICAL? False
state.alerts: ()          <-- silent
```

This is the exact Case B world the card exists to defend. Criterion 6 as tested is conditional on a
precondition that is **currently false in production** and is **never checked**. The two designed
backstops are both inert:

- `KeeperClassifier.armed` is never set `True` in any product code path (`grep armed src/` finds
  only the dataclass field and its docstring). And arming does not save criterion 6 anyway — with a
  partial manifest and `armed=True`, Case A/B still diverge (`keeper_spend` $549 vs $520) because
  rule 3 (`is_keeper`) fires in Case A while rule 4 (FLAGGED) fires in Case B.
- `classify.reconcile()` — the only function that detects an *under*-count — is called by nothing
  outside `tests/test_reconciliation.py`. `cli.replay` does not call it.

An alternative identity path exists and is unused: `slot_to_roster_id` is fully populated on the
real draft, and `rosters.json` + `users.json` resolve 4 of 10 owners. `Identity.slot_to_roster` is
built and then never read by `manifest_keys`.

**Required:** a hard alert (ideally blocking) when `len(manifest_keys) != teams * keepers_per_team`,
plus the roster/user fallback for slot-to-owner.

**B2 — Criterion 8 breaks two ways, both silent.**

*B2a — an override against a slot with no team is counted in `override_delta` but applied to no
budget.* `Slot` is validated `1 <= n <= 32`; nothing cross-checks it against the league's slot set.
A fat-fingered "11" instead of "1" in the override UI:

```python
ev = [PickObserved(seq=1, pick=PickSnapshot(pick_no=1, player_id='A', slot=1, amount=50, is_keeper=False)),
      BudgetAdjustment(seq=2, slot=11, delta=-40, reason="typo: meant slot 1")]
s = fold(ev, slots=range(1, 11))
# total_spent + total_remaining = 2000
# 2000 + override_delta        = 1960
# RECONCILES: False   alerts: ()
```

`ledger.py:161` sums `adjustments.values()` unconditionally, while `ledger.py:147` only applies
`adjustments.get(slot)` to slots that reached the `rosters` dict. The reconciliation identity that
criterion 8 *is* therefore breaks. `test_properties.py::test_ledger_reconciles_exactly_with_overrides`
cannot catch this: it draws `st.integers(1, 10)`, exactly the in-league range.

*B2b — a pick on an unknown slot mints a fresh $200 team.* `ledger.py:125`
`rosters.setdefault(pick.slot, [])` creates the slot; the team loop then hands it a full budget:

```python
s = fold([obs(1,'A',1,50,1), obs(2,'B',11,5,2)], slots=range(1, 11))
# teams = 11, total_spent + total_remaining = 2200 (expected 2000), alerts = ()
```

**B3 — Criterion 7: a keeper is double-counted when the manual slot and the feed slot disagree.**

Supersession keys on `(slot, player_id)` (`ledger.py:94`). If those differ, both records survive —
the player sits on two rosters and the money is counted twice, with no `superseded` entry and no
alert:

```python
ev = [ManualKeeper(seq=1, slot=3, player_id='P', amount=30),
      PickObserved(seq=2, pick=PickSnapshot(pick_no=5, player_id='P', slot=4, amount=30, is_keeper=False))]
s = fold(ev, slots=range(1, 11))
# slot3 spent=30 roster=['P']      slot4 spent=30 roster=['P']
# player P counted 2 times, $60 charged for one $30 keeper
# superseded=() alerts=()
```

This is not exotic. `identity.py` states in its own docstring that slot-to-owner "will keep changing
until draft day"; a `ManualKeeper` event stores a raw integer slot, so any re-seed of the draft order
between manual entry and the feed arriving produces exactly this. The guarding property test
`test_manual_keeper_counted_exactly_once` passes the *same* `slot` to both the pick and the manual
entry, so the mismatch case is entirely unexercised.

Underlying it: **there is no duplicate-player detection anywhere.**

```python
s = fold([obs(1,'X',1,50,1), obs(2,'X',2,60,2)], slots=range(1, 11))
# player X on slots [1, 2]   alerts=()
```

---

#### MAJOR

**M1 — Keeper *under*-count is never alerted.** `ledger.py:153` alerts only on
`len(keepers) > max_keepers`. A team showing 1 keeper, or 0, produces nothing. Combined with B1 this
is how the whole draft goes wrong quietly: with one manifest key dropped, slot 5 holds 1 keeper,
`keeper_spend` falls $549 -> $520, and `state.alerts == ()`. `reconcile()` would catch it and is
never called.

**M2 — Roster overflow past `total_slots` is silent.** 19 picks against a 16-slot team gives
`open_slots = -3`, `max_bid = 0`, `alerts = ()`. This is reachable today: the B3 double-count put
slot 7 at 17 filled slots and only the keeper-count alert fired, never a capacity alert.

**M3 — `test_replay_gate.py::test_max_bid_never_strands_a_team` asserts an invariant that is false,
and is green only by fixture luck.** It asserts `max_bid + (open_slots - 1) <= remaining` with no
precondition. On a broke team:

```python
s = fold([obs(1,'a',1,200,1)], slots=[1]); t = s.teams[1]
# spent=200 remaining=0 open_slots=15 max_bid=0
# assertion: 14 <= 0  ->  False
```

The property-test twin in `test_properties.py:87` guards with `if team.remaining >= team.open_slots`,
so the author knew. The gate version passes only because no team in `fixtures/picks.json` goes broke
before pick 90. The *behaviour* is fine (`max_bid=0` never makes things worse, so criterion 9 holds),
but a team that cannot afford $1 per open slot raises **no alert at all** — a state the cockpit will
absolutely need to surface.

---

#### MINOR

**m1 — `Revert(target_seq=0)` mass-neutralises every unstamped event.** `_Event.seq` defaults to `0`
and `ledger.py:67` matches on equality, so one revert wipes every event the store has not stamped.
The shipped gate test itself constructs `ManualKeeper(seq=0, ...)`, so mixed stamped/unstamped logs
are a real shape.
```python
fold([obs_unstamped_1, obs_unstamped_2, Revert(seq=99, target_seq=0)], slots=[1]).teams[1].spent  # 0, expected 30
```
Also: `Revert` is documented as neutralising "an earlier override event" but will happily neutralise
a `PickObserved`, silently deleting a money fact.

**m2 — Negative amounts accepted silently.** `PickSnapshot.amount` has no `ge=0`; `parse_amount("-500")`
returns `-500`. Result: `slot1 spent=-500 remaining=700 alerts=()`. Conservation still holds
arithmetically, so no test notices.

**m3 — `retention_price` property test is circular** (see above). Also worth a league ruling that is
already open in `DECISIONS_FOR_REVIEW.md`: the `max(1, ...)` clamp means `retention_price(1) == 1`,
which is deliberately *not* `floor(0.75 * 1) == 0`.

---

#### Contamination audit — result: the filter is load-bearing, not decorative

Deliberately leaving one ceremonial pick classified as competitive (dropping key `(5, '4881')`,
Lamar Jackson at pick 9) is **detectable**: competitive count 140 -> 141, every subsequent
`competitive_seq` index shifts by one (141 entries differ), `keeper_spend` $549 -> $520. Same result
via a `Reclassify` event. Criterion 6 is therefore *not* vacuous — the equality is testing something
real. Money is correctly unaffected (`total_spent` identical), confirming there is genuinely no
keeper branch in the ledger.

Two caveats on how it is tested:
- `to_case_a` flips exactly one field, `is_keeper`, on 20 picks. Verified by diffing the payloads.
  So `test_case_a_and_case_b_are_bit_identical` is a one-bit test.
- The scenario `ledger.py:115` names as the *reason* `competitive_seq` exists — "ceremonial keeper
  picks occupy the first 20 pick numbers in Case B and shift everything after them" — is never
  exercised, because the synthesised Case A keeps the same pick numbers. I built the renumbered twin
  (competitive picks 1..140, keepers 141..160). `model_dump()` equality fails, but only because the
  dict is *keyed* on `pick_no`; the `player_id -> competitive index` mapping is identical and
  `keeper_spend` is $549 in both. So the design does hold up under numbering shift — good — but
  nothing in the suite demonstrates that.

`test_misclassification_is_detectable` uses an **empty** manifest, i.e. it mislabels all 20 at once,
which is a much weaker probe than the single-pick case; it also happens to be the exact production
state B1 describes, which is worth noting: the suite contains a test whose setup *is* the bug.

---

#### Minimum bar to re-submit

1. Alert (blocking at boot) when `manifest_keys` does not resolve to `teams * keepers_per_team`, and
   add the `slot_to_roster_id` -> `rosters.json` -> `users.json` fallback for slot-to-owner. (B1)
2. Reject or alert on any event whose `slot` is not in the league's slot set; do not count such an
   adjustment in `override_delta`, and do not mint a team from an unknown pick slot. (B2)
3. Supersede/alert on `player_id` across teams, not only on `(slot, player_id)`. (B3)
4. Alert on keeper under-count, roster overflow, and `remaining < open_slots`. (M1, M2, M3)
5. Fix `test_max_bid_never_strands_a_team` to state the invariant it actually means, and extend
   `test_manual_keeper_counted_exactly_once` and the override property test to draw out-of-league
   slots and mismatched slots.

Criteria 1-5 and 10 are solid and independently confirmed. The defects are concentrated in the
"what happens when the input is not the mock fixture" boundary, and every one of them fails silently
— which is the failure mode this project's charter says is the only one that matters.

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
