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
| Sprint 1 — Data spine | 🟨 **Fixes applied, awaiting re-review** (PR #2, #4) | Replay exact ✅, CI green ✅, Case A/B bit-identical ❌ (holds only on the mock fixture) — see DI-EVAL-1 |
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
