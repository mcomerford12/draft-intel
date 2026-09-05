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
| Sprint 1 — Data spine | 🟨 **Findings closed, awaiting re-evaluation** (PR #2, #4, #17, #18) | Replay exact ✅, CI green ✅ (**6 of 6** clean runs, `.hypothesis` deleted each time), Case A/B holds on a stale manifest ✅ (DI-053 armed the classifier) — 0 blocking open |
| Sprint 2 — Intelligence core | 🟨 **Built; review and evaluation rounds closed** (PR #12–#16) | `make prep` renders all seven §4.9 sections against the real fixtures ✅, **not yet read by a human** ❌ |
| Sprint 3 — Cockpit | ⬜ Backlog | Playwright 160-pick replay, p99 ≤ 2s |
| Sprint 4 — Hardening | ⬜ Backlog | 60-minute rehearsal ×2 |


**On the two 🟨 rows.** Neither is a self-granted pass. Sprint 1's three DI-EVAL-2 blockers are
closed and its gate now measures green — but the verdict on that belongs to an independent
evaluator under §6, and round 3 has not been commissioned, so the row says what was measured and
not what it earns. Sprint 2's gate is *"`make prep` priced board, **reviewed by a human**"*, and
that has not happened: every section renders, the arithmetic reconciles, two review rounds and two
evaluation rounds are closed, and none of that is a human reading their own board and arguing with
it. §4.9 exists precisely because a model you first see three minutes before the auction is one
you cannot sanity-check. The draft is 2026-09-05 19:00 MDT.

---

## Blocked

### [DI-043] Three managers have not joined the league — manifest cannot fully resolve
- **Sprint:** 1 · **Owner:** user/commissioner · **Size:** S · **Surfaced by:** DI-EVAL-1 B1
- **Live check 2026-09-02: 5 of 10 have now joined.** `jswilliams5` holds roster 5, up from the
  four this card was written against. Still 8 of 20 keeper keys resolved, because a joined
  manager is only useful once their Sleeper name is mapped to a manifest owner.
- **✅ Resolved 2026-09-02: `jswilliams5` is Jake**, confirmed by the commissioner rather than
  inferred. The account carries no `team_name` and the display name resembles more than one
  manifest owner, so there was nothing in the API to read it off — and a wrong mapping here
  classifies that team's two keepers as competitive bids, poisoning skew, inflation and every
  tendency profile for the whole draft. Asked rather than guessed; the reasoning is recorded in
  `config/owners.yaml` so the next mapping is confirmed the same way.
- **Live check 2026-09-04: 7 of 10 have now joined.** `keenankid17` holds draft slot 6 and
  `willdeann` slot 7. Both were joined but *unmapped* — the alias table did not know their
  display names — so their four keepers were still counted as unresolved while the managers
  themselves were sitting in the draft room. Confirmed by the user, not inferred, and recorded
  in `config/owners.yaml` with who confirmed and when, per the rule the `jswilliams5` episode
  established.
- **Keeper resolution 8/20 → 10/20 → 14/20.** Verified against the live league, not the fixture.
- Mapped: `mattchupiccu`→Me, `ajthebeard`→AJ, `MasonWAlpert`→Mason, `steeveegee300`→Steve,
  `jswilliams5`→Jake, `keenankid17`→Keenan, `willdeann`→Willie.
- Still unjoined, blocking the remaining 6 keys: **Connor, Burt, TD** — draft slots 8, 9, 10.
  `manifest_keys(require=20)` raises loudly rather than silently classifying their keepers as
  competitive bids; the cockpit (DI-064) instead runs and raises a persistent blocker naming
  them, per ADR-0002's D4.
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

### [DI-EVAL-4] Sprint 2 gate — adversarial evaluation of DI-045 and DI-027

- **Artifact:** `di-027-market-value-provider` @ `c9eb210`, exported read-only with
  `git archive` and run in isolation. **Verdict: REJECTED.** 2 blocking, 4 major, 6 minor.
- **Environment note, recorded because it bounds this verdict.** The working tree was being
  edited by another agent throughout the evaluation. `HEAD` was `di-046-review-round1-fixes`
  @ `fac83c2`, not the branch named in the brief; `src/draft_intel/config.py`,
  `src/draft_intel/quant/market.py` and `config/league.yaml` all changed under the evaluation,
  and the suite grew from 216 to 265 tests mid-run. Everything below was therefore re-derived
  against a pinned export of `c9eb210` (216 passed, matching the author's figure). Findings
  B1/B2/M1/M2/M4 substantially match code review round 1's B1/M2/M4/M5/M6, reached
  independently and without reading that review; that convergence is corroboration, not a
  duplicate. DI-046 claims to close them and was not evaluated.
- Every finding was produced by running the artifact. `docs/PLAN.md`, `docs/HANDOFF.md`,
  `docs/DECISIONS_FOR_REVIEW.md` and commit messages were not read.

#### Mutation verification, re-run independently — 14 escapes, not 15/15

`PYTHONPATH` precedence over the editable install was proved first: `site-packages/draft_intel`
holds only `py.typed` (a namespace-package portion), so a regular package earlier on the path
wins. A control mutation (`CsvMarketValues.name = "ZZZ"`) killed 4 tests, confirming the harness
is load-bearing before any result was trusted. 23 mutations the author did not try were then run
against the **full** suite. Escapes:

| Mutation | Effect |
|---|---|
| `ADP_SENTINEL = 900.0` → `100.0` | any ADP in 100–900 becomes "no opinion"; the tests only ever use 999 |
| `adp >= ADP_SENTINEL` → `>` | boundary untested |
| `MIN_COVERAGE_FRACTION = 0.5` → `0.9` | the gate constant is untested at its own value |
| `max(1, int(...))` → `max(0, ...)`, and `int` → `round` | threshold arithmetic untested |
| `coverage >= threshold` → `>` | off-by-one on the coverage gate |
| `if dollars < 0` → `<= 0` | a legitimate $0 auction row would be rejected as "negative" |
| **`sorted(ladder, reverse=True)` → `list(ladder)`** | **the ladder sort is entirely untested — see M4** |
| `.strip().upper()` on the position cell → `.strip()` | a lowercase `qb` in the user's CSV stops resolving |
| `round(sum, 2)` → `round(sum, 0)` | `MarketValues.total` precision untested |
| `blocking("teams", ...)` → `pass` | **nothing asserts a team-count mismatch blocks**, though `teams` scales the whole pool |
| `roster_size < config.draft_rounds` → `< config.roster_size` | equivalent only because the two happen to be 16 today |
| `starting_slots: sum(...)` → `max(...)` | `LeagueConfig.starting_slots` is referenced by no code and no test |

#### B1 — DI-045's grading boots a league whose every price is wrong (BLOCKING)

Criterion "`draft_rounds` cannot be silently wrong" does not hold. `validate()` emits BLOCKING
for `starters.*`, `teams`, `budget` and `roster_size < draft_rounds` only; `draft.rounds`
disagreement is WARNING. Two reproducible payloads:

- **S1** `draft.settings.rounds = 14`, `roster_positions` unchanged at 16. Legal under ADR-0005's
  own model (14 drafted, 2 waiver spots). Boots with `draft.rounds=14` among four routine
  warnings, indistinguishable from today's known-stale 15.
- **S2** roster grown to 18 *and* rounds to 18. Boots with `roster_size=18`, `bench=8`,
  `draft.rounds=18`.

Priced three ways off the same fixtures:

| rounds | pool_full | $/VORP | QB replacement pts | CeeDee Lamb LIVE $ | Drake Maye LIVE $ |
|---|---|---|---|---|---|
| 14 (S1 truth) | 140 | 0.2835 | 247.8 | **34.64** | **22.37** |
| 16 (what ships) | 160 | 0.1883 | 227.8 | 26.60 | 17.74 |
| 18 (S2 truth) | 180 | 0.1409 | 212.2 | 22.01 | 14.94 |

All three boards pass all three §4.3 invariants and none raises, because the invariants are
self-consistent against whatever pool they are given. The user bids $27 on a $35 player all night
with no error anywhere.

`draft_rounds` is documented as BLOCKING in three places — `config/league.yaml`'s header, the
`config.py` module docstring, and ADR-0005's decision table — and blocks against nothing. ADR-0005
contradicts itself: its Consequences section admits "`draft_rounds` cannot block against anything
at boot". Both compensating controls it offers instead are false:

- *"`make prep` prints the pool size at the top of the board."* There is no `prep` target. The
  Makefile has `install lint types test ci replay smoke`. `value` is not a target either; the
  board is reachable only via `python -m draft_intel.cli value`. The string `prep` appears
  nowhere in the artifact except in ADR-0005 and twice more in `auction_values.csv.example`.
- *"the ledger already rejects a team exceeding its draftable spots, so a wrong `draft_rounds`
  surfaces as rejects within the first round of live picks."* `ledger.py:362` alerts only on
  `filled_slots > total_slots`. That fires on a team's 17th pick — the *end* of the draft, not the
  first round — and in the S1 direction (configured 16, real 14) it never fires at all.

#### B2 — DI-027's primary use case is defeated by its own coverage gate (BLOCKING)

The module exists because `floor(0.75 × auction_value)` "is NOT computable from the API". End to
end: a `config/auction_values.csv` was written holding real dollars for exactly the 20 keepers and
nothing else — the stated purpose. `resolve_market_values` takes the first provider clearing
`max(1, int(160 × 0.5)) = 80` and discards the rest, so the file is thrown away whole:

```
source     adp_rank_transfer   [ESTIMATE]
note       skipped csv: covered 20 of 160 (needs 80) -- read 20 rows from .../auction_values.csv
!! ... Drop real values in .../auction_values.csv to fix this;
```

The banner instructs the user to do the thing they have already done. Josh Allen was supplied at
$48 (correct retention $36); the table printed market $36 / rule $26, computed from our own
model's ladder reshuffled by ADP — precisely the circularity the module docstring warns against,
under a column header naming the league's actual rule. `auction_values.csv.example` contradicts
itself on the same page: "The 20 keepers matter most — they are what the 75% rule prices" and
"coverage of at least half the 160-player pool is needed before the file is preferred".

#### M1 — a legal CSV crashes the `value` command (MAJOR)

`market.py:232` zips physical file lines against `csv.DictReader` records with `strict=True`. Any
quoted field containing a newline — routine from a spreadsheet — makes the counts differ:

```
File ".../quant/market.py", line 232, in market_values
    rows = list(zip([number for number, _line in kept[1:]], reader, strict=True))
ValueError: zip() argument 2 is shorter than argument 1
```

Uncaught, straight out through `resolve_market_values` and `cli.value`. The class docstring
promises the opposite ("read tolerantly … a row it cannot resolve goes to `unmatched` with the
reason") and `test_a_missing_file_is_a_note_not_an_exception` establishes that intent.

#### M2 — an Excel-exported CSV silently resolves nothing (MAJOR)

`open(newline="")` uses the default encoding, so a UTF-8 BOM — what Excel's "CSV UTF-8" writes —
survives into the first header name. `_column` lowercases and strips whitespace but not `\ufeff`,
so `name` is not found and the file is rejected with `needs either a player_id column or both a
name and a position column; found \ufeffname, pos, value`. Coverage 0, silent fall-through to the
estimate. `encoding="utf-8-sig"` is the whole fix. **Still present in the current working tree.**

#### M3 — the printed retention table fails its own stated arithmetic on 5 of 20 rows (MAJOR)

Header: `KEEPER RETENTION CHECK  floor(0.75 * market value), clamped to $1`. The display rounds
(`f"{value:>9.0f}"`) while the computation truncates (`retention_price(int(value))`), so the two
columns do not satisfy the relationship the header asserts:

| player | market $ | printed rule $ | floor(0.75 × market $) |
|---|---|---|---|
| Christian McCaffrey | 30 | 21 | 22 |
| George Pickens | 20 | 14 | 15 |
| Lamar Jackson | 28 | 20 | 21 |
| Josh Allen | 36 | 26 | 27 |
| Puka Nacua | 32 | 23 | 24 |

A user checking the tool by hand on draft morning concludes its arithmetic is broken.

#### M4 — the headline ADP claim is false, and the test named for it is a tautology (MAJOR)

Docstring: *"The ladder's shape and its total are preserved exactly, so the sum invariant holds by
construction."* False whenever fewer players carry a usable ADP than the ladder has rungs — the
cheapest rungs go unused and the total silently shrinks. Ladder `[50, 30, 20, 10]` (total 110)
with two of four players at the undrafted sentinel yields total **80**. Today's fixtures hide it
(400 ranked against 160 rungs) but 196 of 596 projected players already carry no usable
`adp_2qb`, and `market.total` is printed as if it reconciled.

`test_rank_transfer_preserves_the_ladder_exactly` cannot catch it: with 4 players and a 4-rung
ladder, `sorted(values, reverse=True) == ladder` and `total == sum(ladder)` are true for *any*
implementation that hands each of `ladder[0..3]` to a distinct player. Verified by running both
assertions against a deliberately unsorted ladder — both hold while the mapping is wrong. This is
also why the `sorted(ladder, reverse=True)` mutant escapes the full suite, and the sort is
load-bearing: `cli.value` passes the ladder ordered by `baseline_value`, which puts every keeper
(baseline 0, market value high) at the bottom.

#### Tests that pass for the wrong reason

- **`test_a_thin_file_falls_through…`:** `assert pid not in result.notes` tests membership against
  a tuple of whole strings, not substrings. A note reading `"...LEAKED PLAYER ID 1"` still
  satisfies it (verified). The assertion its comment describes — "the reason, not the data, is
  what carries over" — is not being made.
- **`test_two_extra_bench_spots_warn_but_do_not_block`:** `assert config.auction_pool == 160, "the
  priced pool is unmoved by bench depth"`. `config` is loaded from the repo YAML and never
  re-derived from the mutated `grown` payload, and `validate()` cannot mutate a frozen dataclass,
  so bench depth has no path to `auction_pool`. It passes under `auction_pool = teams *
  roster_size` too (both 16). Worse, the assertion's framing is wrong for its own S2 case: with
  the draft also grown to 18 rounds the pool *should* move to 180, and this test presents the
  failure as the feature. (`test_draft_rounds_and_roster_size_are_not_the_same_knob` does the real
  work here and kills that mutant.)
- **`test_the_equivalence_gate_is_not_vacuous`:** `broken_b` and `const` are the identical
  expression `state_for(case_a_payload, lambda _p: PickClass.COMPETITIVE)`, compared against
  `good_a` and `good_b`. Since the test immediately above asserts `good_a == good_b`, the third
  arm is implied by the second and adds nothing — the same "both arms were the identical
  expression" defect its own docstring claims to have fixed.

#### Standing audits — all four run, three PASS

- **Numerical sanity: PASS.** Re-derived by hand from the printed baselines. CeeDee Lamb, WR,
  270.5 pts, WR replacement 128.4 → VORP 142.1 (printed 142.1); market $ = 1 + 142.1 × 0.1883 =
  27.76 (printed 27.76); live $ = 1 + 142.1 × 0.1802 = 26.60 (printed 26.60). No divergence.
- **2QB: PASS.** QB base 2 × 10 = 20; 7 QB keepers seated in base slots (no team keeps two, so no
  FLEX or bench spill); remaining 13. `full_last_drafted` rosters 25 QBs, `live_last_drafted`
  rosters 18 — difference exactly 7. Replacement points are identical across the two universes
  (227.8), which is correct rather than suspicious: all 7 QB keepers sit above the cut, so the
  18th available QB *is* the 25th QB overall.
- **Keeper double-count: PASS, and the two-sided adjustment is load-bearing.** 20 unique ids out
  of supply; `keeper_base` sums to 20 with `keeper_flex = keeper_bench = 0`; full-minus-live
  rostered is `{QB: 7, RB: 6, WR: 7}` summing to exactly 20. Each naive variant was built and
  produces a materially different QB replacement: supply-only 212.2, demand-only 262.7,
  double-counted spots (140−20) 247.8, spots-not-reduced 212.2, against the correct 227.8.
- **Ceremonial-pick contamination: PASS.** Case A (`is_keeper: true`, empty manifest) and Case B
  (`is_keeper: false`, full manifest) agree on every auction statistic — totals, per-team
  `(filled_slots, spent, keepers)`, `keeper_spend` 549, and the full 140-entry `competitive_seq`
  map. Misclassifying **exactly one** ceremonial pick (dropping key `(4, '7564')` from a
  20-key manifest) is detectable: `keeper_spend` 549 → 513 and `competitive_seq` 140 → 141 entries
  with a different mapping, while `total_spent` is unchanged. The filter is load-bearing.

#### Claims checked against the code

- **True:** draft start. `real_draft.start_time = 1788656400000` = `2026-09-06T01:00:00Z` =
  2026-09-05 19:00 at UTC−06:00, and 5 September is MDT. `config.draft_start` matches exactly and
  warns rather than blocks on drift.
- **True:** `auction_pool == 160` under both roster readings, and market values do not replace
  `PlayerValue.market_value` — `board.players[*].market_value` is never written from `market`.
- **True:** Finding 10's API table. `taxi_slots = 0`, `reserve_slots = 0`, `roster_positions` = 16
  (10 starters + 6 BN), `draft.settings.rounds` = 15, `total_rosters` = 10.
- **False:** ADR-0005's decision table (`draft_rounds | BLOCKING`), its `make prep` control, and
  its ledger control — B1.
- **False:** the rank transfer "preserves … its total exactly" — M4.

#### Minor

- `LeagueConfig.starting_slots` is referenced by no code and no test.
- `cli.value()` has no identity-completeness guard, unlike `cli.smoke()`. If an owner fails to
  resolve to a draft slot their keepers leave **supply** (via `keeper_ids`) but not **demand**
  (`positions_by_slot` skips `slot is None`) — the exact asymmetry §4.2 singles out. Dropping one
  owner moves remaining QB slots 13 → 14 and Lamb $26.60 → $27.13, invariants still passing.
- The retention table prints `loaded: unset` for all 20 keepers while the same run reports
  `keeper spend $549`; the two read different sources (`keepers.yaml` prices vs `picks.json`).
- `MIN_COVERAGE_FRACTION`, `ADP_SENTINEL` and the threshold arithmetic have no test pinning their
  values or boundaries (see the mutation table).
- No test asserts that a `teams` mismatch blocks, though `teams` scales the entire pool.
- A lowercase position cell (`qb`) in the user's CSV is unhandled by any test.

#### Minimum bar to re-submit

1. `draft_rounds` must block when the API corroborates a value against the config, and ADR-0005's
   two false compensating controls must be struck, not quietly dropped. A test must build the S1
   payload (`rounds=14`, roster 16) and assert the boot is refused.
2. Real auction values must survive regardless of how many there are — the 20 keepers are the
   stated use case. If providers layer, provenance must remain answerable per player.
3. The CSV reader must not raise on any input; the newline case and the BOM case both need tests.
4. Fix the docstring or the code on ladder-total preservation, and replace
   `test_rank_transfer_preserves_the_ladder_exactly` with one that can fail — unequal ladder and
   field lengths, and an unsorted ladder in.
5. Make the printed `rule $` equal `floor(0.75 × printed market $)` for every row.
6. Replace the three assertions listed under "tests that pass for the wrong reason" with
   assertions that can fail.


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
s = fold([obs(1, 1, "A", 1, 50)], slots=range(1, 11))
s.teams.__ior__({99: None})  # no exception at all
len(s.teams)  # 11   -- derived state silently corrupted

s2 = fold([obs(1, 1, "A", 1, 50)], slots=range(1, 11))
s2.total_spent + s2.total_remaining  # 2000
try:
    s2.teams |= {11: TeamState(slot=11, budget=200, spent=0, roster=(), total_slots=16)}
except ValidationError:
    pass  # pydantic refuses the REBINDING, after the fact
sorted(s2.teams)  # [1..10, 11]
s2.total_spent + s2.total_remaining  # 2200  -- conservation broken in place
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

ev = [
    BudgetAdjustment(seq=1, slot=1, delta=-40),
    Revert(seq=2, target_seq=1),  # undo the correction
    Revert(seq=3, target_seq=2),  # put it back
    Revert(seq=4, target_seq=3),
]  # take it off again
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

parse_picks([{"pick_no": 1, "draft_slot": 1, "player_id": "A", "metadata": {"amount": "inf"}}])
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
ev = [
    PickObserved(
        seq=1, pick=PickSnapshot(pick_no=1, player_id="A", slot=1, amount=50, is_keeper=False)
    ),
    BudgetAdjustment(seq=2, slot=11, delta=-40, reason="typo: meant slot 1"),
]
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
s = fold([obs(1, "A", 1, 50, 1), obs(2, "B", 11, 5, 2)], slots=range(1, 11))
# teams = 11, total_spent + total_remaining = 2200 (expected 2000), alerts = ()
```

**B3 — Criterion 7: a keeper is double-counted when the manual slot and the feed slot disagree.**

Supersession keys on `(slot, player_id)` (`ledger.py:94`). If those differ, both records survive —
the player sits on two rosters and the money is counted twice, with no `superseded` entry and no
alert:

```python
ev = [
    ManualKeeper(seq=1, slot=3, player_id="P", amount=30),
    PickObserved(
        seq=2, pick=PickSnapshot(pick_no=5, player_id="P", slot=4, amount=30, is_keeper=False)
    ),
]
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
s = fold([obs(1, "X", 1, 50, 1), obs(2, "X", 2, 60, 2)], slots=range(1, 11))
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
s = fold([obs(1, "a", 1, 200, 1)], slots=[1])
t = s.teams[1]
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
fold([obs_unstamped_1, obs_unstamped_2, Revert(seq=99, target_seq=0)], slots=[1]).teams[
    1
].spent  # 0, expected 30
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

## In Progress — Sprint 2 cards to schema

The reviewer's process blocker on round 1 was correct: DI-045 had no card at all and DI-027
existed only as a row in the table below, with no acceptance criteria and no verdict fields. §6.3
requires the verdict to be a written artifact appended to the card, and there was no card to
append to. Written to schema here, retroactively for the cards already built.

### [DI-045] Separate `draft_rounds` from `roster_size`

- **Sprint:** 2 · **Owner:** architect · **Size:** S · **Branch:** `di-045-rounds-vs-roster-size`
  · **PR:** #7
- **Why:** `total_slots` did triple duty — roster-size tripwire, priced-pool multiplier, per-team
  slot cap — and was right only because this league happens to draft every roster spot. The
  commissioner then reported 18 roster positions against 16 draft rounds, which the single field
  cannot represent.
- **Acceptance criteria:**
  - [x] `auction_pool = teams * draft_rounds` is the sole feed to the priced pool
  - [x] roster capacity above `draft_rounds` moves no price and does not refuse the boot
  - [x] `roster_size < draft_rounds` still blocks; a self-contradictory config file is caught at load
  - [x] `draft_rounds` cannot be silently wrong — see DI-046 B1
  - [x] `draft_start` tripwire, warning-only, matching Sleeper's `start_time` exactly
  - [x] ADR-0005; the 18-vs-16 contradiction flagged as Finding 10 rather than resolved silently
- **Reviewer verdict:** REJECT (round 1) — B1, `draft_rounds` documented as blocking in three
  places and blocking against nothing. Closed in DI-046.
- **Evaluator verdict: REJECTED** (DI-EVAL-4, artifact `di-027-market-value-provider` @ `c9eb210`).
  Criteria 1, 2, 3, 5 and 6 independently confirmed by running the artifact; criterion 4
  (`draft_rounds` cannot be silently wrong) is **false in the artifact**. Two payloads were built
  that boot clean and price the board wrongly: `draft.settings.rounds = 14` with an unchanged
  16-slot roster (a legal ADR-0005 league: 14 drafted, 2 from waivers) boots with a WARNING and
  prices CeeDee Lamb at $26.60 against a correct $34.64 — a 23% under-price on the top asset,
  with all three §4.3 invariants passing because they are self-consistent against whatever pool
  they are handed. ADR-0005's two compensating controls are both false: `make prep` is not a
  Makefile target anywhere in the repo, and the ledger's slot cap (`filled_slots > total_slots`)
  fires only at the *end* of a draft and never at all when the configured figure exceeds reality.
  Full detail in DI-EVAL-4.

### [DI-027] `MarketValueProvider` + the auction-value ingest path

- **Sprint:** 2 · **Owner:** quant · **Size:** M · **Branch:** `di-027-market-value-provider`
  · **PR:** #8
- **Why:** Sleeper publishes no auction value (Finding 3), and the commissioner has confirmed the
  `floor(0.75 × sleeper_auction_value)` keeper rule *will* be applied on draft day. Without a
  route for those values in, the league's own rule is not computable and every keeper price is a
  guess. Also §4.4: market value must be a pluggable interface with at least three
  implementations, and no feature may hard-depend on an undocumented endpoint.
- **Acceptance criteria:**
  - [x] three implementations: CSV, ADP rank transfer, internal model
  - [x] CSV resolves by name **and** position, with `player_id` as the escape hatch
  - [x] unresolvable rows reported with true file line numbers, never dropped
  - [x] `inf`/`nan` rejected at the cell that carried them
  - [x] provenance inseparable from the numbers; estimates badged
  - [x] the app functions with `api.sleeper.com` dead (CSV and internal both work)
  - [x] supplying only the 20 keeper values is useful — see DI-046 M6
- **Reviewer verdict:** REJECT (round 1) — M2 crash on a legal CSV, M3 diagnostics discarded,
  M4 false docstring claim, M5 unreproducible arithmetic, M6 gate defeats the primary use case.
  All closed in DI-046.
- **Evaluator verdict: REJECTED** (DI-EVAL-4, artifact `di-027-market-value-provider` @ `c9eb210`).
  Criteria 1-5 confirmed by running the artifact. Criterion 7 (supplying only the 20 keeper
  values is useful) is **false**: a `config/auction_values.csv` holding real dollars for exactly
  the 20 keepers is discarded whole (`skipped csv: covered 20 of 160 (needs 80)`), the board keeps
  its `[ESTIMATE]` badge, and the retention table prints prices derived from our own model's
  ladder — Josh Allen supplied at $48 (rule $36) printed as $36 / rule $26. Criterion 6 was not
  reachable as stated: a legal RFC-4180 CSV with a quoted embedded newline raises an uncaught
  `ValueError: zip() argument 2 is shorter than argument 1` out of `market.py:232` and takes the
  whole `value` command down. The module docstring's central claim — the rank transfer "preserves
  the ladder's shape and its total exactly, so the sum invariant holds by construction" — is false
  whenever fewer players carry a usable ADP than the ladder has rungs (demonstrated: $110 ladder
  in, $80 out), and the test named for that property cannot detect it. Full detail in DI-EVAL-4.

### [DI-031] Keeper surplus board + structural `keeper_inflation`

- **Sprint:** 2 · **Owner:** quant · **Size:** M · **Branch:** `di-031-keeper-surplus` · **PR:** #9
- **Why:** §1.1 calls the structural inflation figure "the single most actionable pre-draft output
  of the whole system", and §8 says it should land early in the sprint rather than last.
- **Acceptance criteria:**
  - [x] per-keeper book vs paid; league-wide surplus
  - [x] `keeper_inflation = total_live_money / available_book_value`, never a ratio of money pools
  - [x] both scenarios carried: prices as loaded, and prices under the 75% rule
  - [x] a partial keeper spend refuses to produce derived figures rather than approximating
  - [x] §2 reconciliation alerts on loaded price vs rule-implied price
- **Reviewer verdict:** not yet reviewed (built after round 1 was commissioned).
- **Evaluator verdict:** pending.

### [DI-032] Live `market_inflation`, overall and per position

- **Sprint:** 2 · **Owner:** quant · **Size:** M · **Branch:** `di-032-live-inflation`
- **Why:** §4.5. The live figure the user bids against, kept permanently distinct from the
  structural one.
- **Acceptance criteria:**
  - [x] §4.5 formula exactly; inflation is exactly 1.0000 at pick 0, tested as an identity
        against the real board
  - [x] every input filtered to `COMPETITIVE`, through one function
  - [x] time series keyed on `competitive_seq`; Case A/B curve equivalence asserted
  - [x] positional figure carries real positional signal — see the deviation note below
- **Deviation from the charter, deliberate:** §4.5's *forward* positional formula is degenerate.
  Allocating remaining money in proportion to remaining positional model value makes the value
  term cancel, so every position reports the overall figure. What ships is the *realized* ratio,
  which is what §4.5's own example sentence ("RB is inflating at 1.18×") describes.
  `forward_positional_inflation` exists only to pin the degeneracy under test.
- **Reviewer verdict:** pending.
- **Evaluator verdict:** pending.

### [DI-033] Skew: market and edge, all aggregations

- **Sprint:** 2 · **Owner:** quant · **Size:** M · **Branch:** `di-033-skew` · **PR:** #12
- **Acceptance criteria:**
  - [x] the two §4.6 measures kept separate and unambiguously labelled
  - [x] market skew uses the *consensus* value from `quant.market`, never our own model's field
  - [x] each pick judged against the inflation the room faced **before** it
  - [x] aggregated per pick, per team, per position, with `$ spent per projected point`
  - [x] `COMPETITIVE` only; a pick with no consensus value excluded rather than counted as zero
- **Mutation-verified:** 12/12, including both directions of the before/after choice.
- **Reviewer verdict:** REJECTED (round 1, `di-039-make-prep` @ `29fab99`) — M3: §4.6 requires
  five aggregations; per-price-bucket and league-wide median + per-pick z-score were absent with
  no stated deviation, on a card titled "all aggregations" with every criterion ticked. The rest
  verified clean: consensus value sourced from `quant.market` and not our own field; the
  before-inflation choice confirmed; the `COMPETITIVE` filter confirmed; unpriced picks excluded
  rather than zeroed. **Closed in DI-048** — `Distribution`, `PriceBucket`, `PickSkew.edge_z`,
  `SkewBoard.by_price_bucket`, `SkewBoard.distribution`, `SkewBoard.outliers()`.
- **Evaluator verdict: APPROVED** (DI-EVAL-5, adversarial round 2; artifact `di-039-make-prep`
  @ `bf93f1d`, escapes re-confirmed at `e21fb32`). Ran, did not read. Six mutants applied to
  `skew.py` under `PYTHONPATH` precedence (proved first with a control mutant): judging each pick
  against `step.after` instead of `step.before`; sourcing `market_value` from
  `PlayerValue.market_value` instead of `quant.market`; counting an off-board pick instead of
  skipping it; `stdev` 0.0 on a single pick; `MIN_VALUE_FOR_PCT` 1.0 → 0.0; edge-skew sign flip.
  **All six killed.** The two headline claims are load-bearing, not decorative. The §4.6
  aggregation gap the reviewer found independently (per-price-bucket, median, per-pick z-score)
  was present in the artifact and is confirmed closed at `e21fb32`, so it is not re-litigated
  here. Ceremonial-pick contamination audit passes: on the real 160-pick fixture, Case A
  (`is_keeper` only, empty manifest) and Case B (manifest only, `is_keeper` false) produce
  **bit-identical** `SkewBoard.model_dump()`; leaving one ceremonial pick `COMPETITIVE` moves
  overall mean edge skew 4.01 → 4.21 and pick count 140 → 141, so the filter is detectable.

### [DI-034] Opponent max-bid and affordability engine

- **Sprint:** 2 · **Owner:** quant · **Size:** S · **Branch:** `di-034-affordability` · **PR:** #12
- **Acceptance criteria:**
  - [x] max bid read from `TeamState`, never recomputed
  - [x] FLEX overflow counted collectively across RB/WR/TE, not once per position
  - [x] aggression keyed on `draft_slot`, `None` below three picks, and `None` is not zero
  - [x] `my_max_bid` returns the binding constraint alongside the number (§4.7a)
  - [x] the user is never on their own threat list; an unmapped slot is labelled, not dropped
- **Mutation-verified:** 16/17. The survivor is provably equivalent (the neutral multiplier
  equals the formula at zero skew); the tempting wrong version — a zero *threat* rather than a
  zero *skew* — is pinned by a test.
- **Reviewer verdict:** APPROVED (round 1, `di-039-make-prep` @ `29fab99`). Max bid read from
  `TeamState`, FLEX overflow collective, slot-keyed aggression, `None` distinct from zero, and the
  user excluded from their own threat list — all verified independently. One MINOR (m4): the
  `drops_out_above` docstring said "one dollar under its max bid" and the function returns
  `max_bid`. **Closed in DI-048** — the docstring now states what the code does and why.
- **Evaluator verdict: APPROVED, with one verification claim disproved** (DI-EVAL-5). Seven
  mutants applied; five killed (collective FLEX overflow, slot-keyed aggression, `None` ≠ zero
  threat, binding-constraint label, `price_that_clears` off-by-one). **Two escaped the full
  suite, at `bf93f1d` and still at `e21fb32`:**
  - **e1 (criterion 1 is unenforced).** Replacing `max_bid=team.max_bid` with
    `team.remaining - (team.open_slots - 1)` — the exact recomputation the docstring says must
    never happen — passes every test. It is *not* an equivalent mutant: a team with a full roster
    reports `max_bid` 1 instead of 0 and `can_afford` flips to True, putting a team that cannot
    bid on the threat list; a team with $5 left and 11 open slots reports −$5 instead of $0.
    Neither state is constructed anywhere in `tests/test_affordability.py`.
  - **e2.** `MIN_AGGRESSION_SAMPLE` 3 → 1 escapes; the tests pass `min_sample` explicitly, so the
    "three picks" in criterion 3 is pinned nowhere.
  The **"16/17 mutation-verified"** line is therefore materially overstated. No wrong output was
  produced from the shipped code, so this is APPROVED — but the two escapes should be closed
  before the cockpit reads `Opponent.max_bid`.

### [DI-035] DP roster optimizer + CBC oracle equivalence test

- **Sprint:** 2 · **Owner:** quant · **Size:** L · **Branch:** `di-035-optimizer` · **PR:** #13
- **Acceptance criteria:**
  - [x] exact DP as the production engine, per ADR-0003
  - [x] PuLP/CBC retained as a test oracle, written from the §4.7b ILP independently
  - [x] ADR-0004's objective in both engines, λ included
  - [x] never returns an illegal lineup; never proposes a keeper (keepers are not candidates)
  - [x] **13/13 mutation-verified** (DI-049). Aimed at the round 2 fixes: all three call sites
        where starter ordering can revert to `points`, each of dominance's three comparison
        dimensions, the slot-aware rule, the cap's reserved tranche in both directions, the
        capped-infeasibility note, and the FLEX enumeration. Two escaped on the first pass —
        disabling the slot-aware rule, and letting the cap overrun by one — and both are
        invisible from outside by construction, because a correct prune never changes the
        answer. Pinned directly on `_prune`, which is the only place they are observable.
- **Three defects found during the card**, all of the "right number, wrong answer" shape:
  dominance pruning unsound with a fixed slot count; forced players reserving a starting slot so
  the DP optimised an objective it did not report; back-pointer reconstruction rebuilding rosters
  holding the same player twice.
- **The oracle was wrong before the DP was** — it emitted no starting-slot constraint for
  positions absent from `starters`, so CBC scored lineups with two starting tight ends in a
  league with no TE slot and called the DP wrong for refusing.
- **Performance against §4.7b's 200ms budget, measured not claimed:** 14 slots ~450ms (over),
  8 slots ~156ms, 4 slots ~45ms. The 14-slot case is the only state that cannot occur during
  live bidding. Was 4.4s before the inner loop was vectorised.
- **Reviewer verdict:** REJECTED (round 1, `di-039-make-prep` @ `29fab99`) — M1: the exactness
  argument was false. Starters must be chosen on `points - λ x vorp`, not on `points`, and the
  CBC oracle set `vorp = points`, so it explored a two-dimensional space along its diagonal and
  was structurally incapable of seeing the defect. Two-player repro: DP 100.0, CBC and brute
  force 119.0. Safe in production only via an unstated invariant from `replacement.py` that
  DI-038's overrides are positioned to break. m3: the cap path emitted a flat falsehood — ten $50
  wideouts and ten $1 wideouts capped at five reported no legal roster on a board that was
  plainly buyable — and `prep.py` branched on the objective alone, dropping the `CAPPED` note.
  **NOT rejected:** 7,400 independently brute-forced states found the DP exact and legal
  throughout the vorp-monotone regime; `_prune`, `_reconstruct`, `_unwind`, the mandatory path and
  the FLEX enumeration are all sound, and measured latency beats the docstring's claim (240ms
  against 450ms). **Closed in DI-048** — `starter_priority`, dominance on both dimensions, an
  independently-drawn VORP in `random_pool`, the seed sweep 12 → 30, a reserved cheapest tranche
  in the cap, and the notes carried to the page.
- **Evaluator verdict: REJECTED** (DI-EVAL-5; artifact `bf93f1d`, all findings re-confirmed
  present at `e21fb32`).
  **What holds.** I wrote an *independent* brute-force enumerator (not CBC: the card records the
  oracle was itself wrong once) that enumerates every legal roster and every legal lineup
  assignment by permutation. Across **1,200 random states** — 1–6 slots, 5–14 candidates, λ ∈
  {0, 0.2, 0.5, 1.0}, including forced arms, multi-forced arms and excluded arms — the DP matched
  on objective **and** on legality (exact slot fill, no duplicates, no over-budget, forced
  present, excluded absent, FLEX never over-issued, `starting_points` equal to the reported
  starters). The DP is exact under its real precondition. Criterion 1 is met.
  **B1 — the latency section measures the wrong thing, and the deliverable is 20–1000× over
  budget.** The docstring times `best_roster` only. §4.7b budgets the *walk-away curve* at 200ms
  and ADR-0003 budgets a per-pick precompute. Measured on the real 140-player pool at `e21fb32`:
  one curve, 14 slots / $145, $1–$60 = **12.5 s**; `walkaway_board(top=3)` mid-draft (8 slots /
  $120) over the full legal range = **26.3 s**, i.e. **~219 s per settled pick** at ADR-0003's own
  `top=25`. The card's claim that the over-budget 14-slot state "is the only state that cannot
  occur during live bidding" is backwards: 14 open slots is the state at the *first nomination*,
  which is precisely when a walk-away number is needed.
  **B2 — `_prune`'s exactness claim is false as written.** "Dominance pruning is exact, not a
  heuristic. A player who costs at least as much as another at the same position and scores no
  better can never appear in an optimal roster" — they can, as a bench player with higher VORP,
  because `_prune` compares only `(price, points)` and the bench term is `λ × vorp`.
  Reproducer: `RB a(100pts,100vorp,$5)`, `b(90,0,$5)`, `d(10,10,$5)`, `budget=10, slots=2,
  starters={RB:1}, λ=1.0` → DP returns `{a,b}` at 100.0; the true optimum is `{a,d}` at 110.0.
  It is exact only under the unstated extra precondition that VORP is non-decreasing in points
  *within* a position, which holds today solely because `vorp = max(0, points − replacement[pos])`.
  Nothing validates it on `Candidate`, and DI-038's per-player `points` override breaks it the
  moment Sprint 3 wires overrides into the optimizer.
  **B3 — the regression the module says it fixed is untested.** Reverting `_reconstruct`'s
  `step = index` to `step = step - 1` — the back-pointer bug the docstring calls "the worse of the
  two failures" — **escapes the entire suite**, at `bf93f1d` and still after DI-049's claimed
  "13/13". It is not equivalent: seed 757 of my generator (14 candidates, 6 slots, $25, λ=0.5)
  returns a roster containing `p5` **twice**. No test asserts that `Roster.players` holds distinct
  ids.
  **B4 — the safety cap is unobservable end to end.** `MAX_CANDIDATES_PER_POSITION` 60 → 8 leaves
  the suite green; nothing asserts `is_exact` on any real-board solve.
  **m1 — the CBC oracle never exercises `forced` or `excluded`**, which is where two of the card's
  own three "defects found" lived. `random_pool` also sets `vorp == points`, so no oracle state can
  distinguish the two terms of ADR-0004's objective.

### [DI-036] Walk-away curves, precomputed per player

- **Sprint:** 2 · **Owner:** quant · **Size:** M · **Branch:** `di-036-walkaway` · **PR:** #13
- **Acceptance criteria:**
  - [x] Δ objective and Δ starting points per price point (§4.7b's y-axis)
  - [x] the excluded arm solved once for the whole curve
  - [x] monotonicity checked, not assumed; infeasible points excluded from the check
  - [x] walk-away price is the *highest* price still worth paying
  - [x] the precompute ranks by VORP, not raw points
  - [x] **4/4 mutation-verified** (DI-049). The off-by-one in the binary search does not fail,
        it *hangs* — `(low + high) // 2` with `low == high - 1` sets `low = low` forever — which
        is the worst failure mode this module has, because the curve runs in the draft-night hot
        path and a hang gives the operator nothing at all. The loop now carries the bound its own
        halving argument justifies and says so loudly instead. Two further escapes closed: the
        monotonicity flag was hardcodeable to `True` without any test noticing (every real curve
        is monotone, so nothing could tell a computed `True` from a literal one) and
        `max_legal_bid` lost its $1 floor, which makes `worth_it_at_any_legal_price` trivially
        true exactly when the budget is the binding constraint.
- **Reviewer verdict:** REJECTED (round 1, `di-039-make-prep` @ `29fab99`) — M5:
  `walk_away_price = max(positive)` cannot distinguish a genuine zero crossing from the top of
  the sampled grid; repro reported $58 against a true $117. Inherits DI-035's M1. The
  excluded-arm-solved-once optimisation, the monotonicity check and the VORP ranking all verified
  correct; no double-buy, and the baseline arm confirmed to genuinely exclude the player.
  **Closed in DI-048** — binary search over the delta, plus `max_legal_bid` and
  `worth_it_at_any_legal_price`.
- **Evaluator verdict: REJECTED** (DI-EVAL-5; artifact `bf93f1d`, re-confirmed at `e21fb32`).
  **B1 — criterion 3 ("monotonicity checked, not assumed") is not verified, and the two tests
  named for it cannot fail.** Replacing `_is_monotone`'s body with `return True` **escapes the
  full suite**. `test_the_curve_falls_as_the_price_rises` builds a board whose deltas are
  `[100.0] × 10` — a perfectly flat line — so it demonstrates nothing about the curve *falling*;
  `test_at_lambda_zero_the_walk_away_price_is_just_the_budget_ceiling` asserts that same flatness
  two screens later. `test_no_walk_away_curve_on_the_real_board_is_broken` is
  `assert "BROKEN" not in report`, which also passes for a report containing zero curves.
  **B2 — `test_the_forced_arm_never_buys_the_player_twice` names a protection that does not
  exist.** Deleting `excluded=frozenset({player.player_id})` from `walkaway._forced` changes
  nothing in **500/500** random solves, because `best_roster` already skips `forced_ids`. The test
  passes for the wrong reason.
  **B3 — latency.** Shared with DI-035 B1: 12.5 s for one 60-point curve at 14 slots against a
  200 ms budget, and ADR-0003's "precomputed after each settled pick" costs ~219 s per pick at
  `top=25`. Neither `walkaway.py` nor the card reports a curve timing at all.
  **m1 — the walk-away price is taken off the wrong axis.** §4.7b and this module's own docstring
  put Δ *starting points* on the y-axis, but `walk_away_price` is selected from `delta` (the
  ADR-0004 objective). `starting_points_delta` is computed, displayed and never used for the
  crossing, and its monotonicity is never checked.

### [DI-037] Manager tendency profiles (keyed on `competitive_seq`)

- **Sprint:** 2 · **Owner:** quant · **Size:** M · **Branch:** `di-037-038-tendencies-overrides`
  · **PR:** #14
- **Acceptance criteria:**
  - [x] positional bias, aggression slope, run-chasing, spend Gini
  - [x] every figure fitted on `competitive_seq`; the whole profile identical under a 20-pick
        `pick_no` offset, which is what Case A and Case B differ by
  - [x] sample floors, with `None` distinguished from zero throughout
  - [x] **7/8 mutation-verified** (DI-049); the survivor is provably equivalent (`len(points)
        < 1` still returns `None` at the zero-denominator guard one line later). Three real
        escapes closed, all "no information rendered as a measurement" or its mirror: `_slope`
        returning 0.0 where it is undefined, a run occupying the *final* three picks going
        unseen because the last window was never opened, and run-chasing measured absolutely
        rather than against the manager's own average — which turns every habitual overpayer
        into a chaser.
- **Charter item not built:** nomination behaviour. Sleeper's picks endpoint records who *won*
  each player and carries no field anywhere for who nominated them, so any figure would be
  invented. Reported through `Profile.unavailable` rather than omitted silently.
- **Reviewer verdict:** APPROVED (round 1, `di-039-make-prep` @ `29fab99`). `competitive_seq`
  throughout, `None` distinct from zero, sample floors honoured. The nomination-behaviour
  deviation is judged SOUND — verified against the actual pick payload keys and corroborated by
  charter §2 — and is correctly surfaced through `Profile.unavailable` rather than left in a
  docstring.
- **Evaluator verdict: REJECTED** (DI-EVAL-5; artifact `bf93f1d`, B1 and B3 still present at
  `e21fb32`).
  **B1 — the card's headline criterion is untestable as written, and its test is a tautology.**
  `test_the_aggression_slope_is_fitted_on_competitive_seq_not_pick_no` gives one manager eight
  *consecutive* picks, so `competitive_seq` and `enumerate(picks)` are the same sequence up to a
  shift and both are offset-invariant. Fitting on `enumerate(picks)` instead of `competitive_seq`
  **escapes the full suite**. It is not equivalent: in a three-manager interleaved draft (manager
  2 holding seqs 2, 5, 8, 11, 14, 17) the true slope is **0.6897/pick** and the mutant's is
  **2.0691/pick** — exactly 3×; in the real ten-team draft it would be ~10×. `aggression_slope` is
  documented as "dollars of edge skew per competitive pick" and could silently be per *own* pick.
  **B2 — the least-squares formula's magnitude was unpinned** at `bf93f1d`: replacing
  `numerator/denominator` with `numerator/len(xs)` (covariance, not slope) escaped, turning 0.6897
  into 18.105 with only the sign preserved. Confirmed closed at `e21fb32`.
  **B3 — the "nomination behaviour is unavailable" claim is factually false, and is contradicted
  by a fixture committed in this repository.** `fixtures/draft.json` `metadata` carries
  `nominated_player_id: '4227'`, **`nominating_slot: '5'`**, `offering_slot: '5'`,
  `offering_user_id`, `highest_offer: '1'` and `last_action_at` — real values from the real draft
  endpoint the app already fetches. The shipped string, which reaches the user through
  `Profile.unavailable` and `describe()`, asserts "no field anywhere in the payload carries it".
  Two consequences beyond this card: (a) `docs/api-findings.md` never records these fields despite
  Sprint 0's mandate to map and fixture the response shapes; (b) they also contradict §2's hard
  constraint ("no documented endpoint for the player currently on the block / the current high bid
  / who is currently bidding"). Per the charter's standing instruction this contradiction must be
  **flagged to the orchestrator, not silently resolved**. Building nomination history needs
  polling and is a scope call — declaring it impossible on a false premise is not.
  **What holds.** `_gini` matches an independent reference implementation
  (`Σ|xi−xj| / (2n²·x̄)`) to four decimals on five distributions including the degenerate ones.
  The `par_skew` helper genuinely does hold inflation at exactly 1.0000 for at-value bids (I
  suspected it did not; it does), so no spurious trend is injected. Run detection, sample floors
  and `None`-vs-zero are all mutation-covered.

### [DI-038] Value override plumbing

- **Sprint:** 2 · **Owner:** quant · **Size:** M · **Branch:** `di-037-038-tendencies-overrides`
  · **PR:** #14
- **Acceptance criteria:**
  - [x] per-player, positional multiplier, blacklist — §4.8's three kinds
  - [x] the model's number retained alongside the user's, permanently
  - [x] no implicit renormalisation; the deviation shown; `renormalise()` is a preview only
  - [x] an override naming nobody raises; a non-positive multiplier is refused
  - [x] **5/5 mutation-verified** (DI-049), first pass, no escapes: precedence order in both
        directions, the blacklist reaching both value fields, provenance recorded, and the
        unknown-player raise.
- **Reviewer verdict:** APPROVED (round 1, `di-039-make-prep` @ `29fab99`). No derived-state
  mutation, precedence order correct (multiplier, then manual, then blacklist), the deviation
  exposed rather than buried, `renormalise()` preview-only, and both a non-positive multiplier and
  an unknown player raise. Carried forward to Sprint 3: `OverriddenValue` carries no `vorp`, so
  overriding `points` decouples the two — which is precisely the invariant DI-035's M1 depended
  on, and the reason that fix could not be deferred.
- **Evaluator verdict: APPROVED** (DI-EVAL-5; artifact `bf93f1d`). Six mutants applied to
  `overrides.py`, **all six killed**: scaling a manual override by the positional multiplier
  (precedence backwards); blacklisting zeroing `baseline_value` but not `market_value`; silently
  renormalising `sum_baseline_after` to `total_live_money`; dropping the model's number out of
  `deltas()`; swallowing an override that names nobody; accepting a non-positive multiplier. Both
  claims verified by running: no implicit renormalisation (`renormalise()` returns a preview and
  applies nothing, and returns `None` rather than a factor of 1.0 when the board reconciles), and
  the model's figures are structurally inseparable from the user's on `OverriddenValue`.
  **One forward-looking note, not blocking here:** `apply_overrides` can lower a player's `points`
  while leaving `vorp` untouched, which breaks the unstated precondition the DP relies on (see
  DI-035 B2). Harmless today because nothing feeds overridden values to the optimizer; it becomes
  reachable the moment Sprint 3's inline value editing does.

### [DI-039] `make prep` — the priced board and printable report

- **Sprint:** 2 · **Owner:** quant · **Size:** L · **Branch:** `di-039-make-prep` · **PR:** #14
- **Acceptance criteria:**
  - [x] all seven §4.9 sections render against the real fixtures
  - [x] tiers found from the board, never declared (§1 CRITICAL DATA RULE)
  - [x] the config tripwire runs above the board
  - [x] written to `reports/prep.txt`; `make prep` runs in ~90s
  - [x] **11/11 mutation-verified** (DI-049) across `tiers.py`, `skew.py` and `inflation.py`,
        the modules the report renders from. One escape closed: the tier sheet's `min_sample`
        floor could be removed entirely without a test noticing, because the thin board it was
        pinned on had gaps under the threshold anyway — the floor was never the thing being
        measured.
- **Two deviations, both stated in the report itself** rather than only in a docstring: §4.9
  item 1's p25/p50/p75 labels are refused in favour of a sourced two-point band (the Monte Carlo
  that would make percentiles real is Sprint 3), and item 6's interactive planner renders as
  fixed allocations because a printed page cannot be interactive.
- **A defect the report surfaced:** the walk-away precompute ranked by raw projected points, so
  in a 2QB league the target list came out as twelve quarterbacks and nothing else.
- **Sprint 2 gate:** `make prep` produces the full board. **A human has not yet reviewed it** —
  that half of the gate is the user's, and it is why the report exists.
- **Reviewer verdict:** REJECTED (round 1, `di-039-make-prep` @ `29fab99`) — B1: mock-draft
  keeper prices were rendered as this league's, and `config/keepers.yaml` was ignored entirely;
  setting a manifest price to commissioner authority changed nothing and the report still printed
  the mock's figure. M2: the priced-board band arithmetic discarded direction, so with keepers
  loaded below the 75% rule the printed band excluded the true price on the wrong side. M4:
  hardcoded `aliases={"Me": "Matt"}` duplicating `config/owners.yaml`, `my_slot=3`, and
  `config.budget - 55` where the fixture's figure for that seat is $62 — the $55 was another
  manager's spend. m1: effective buying power divided by teams-with-keepers, +$22/team the moment
  one team keeps nobody. m2: the FLEX split was uniform rather than proportional, so the need
  column summed to 78 against the 80 printed two lines below. Deviation (c) judged sound in
  principle but broken in execution; deviation (d) sound on interactivity, partly rationalising on
  content. **Closed in DI-048** — `_retention_prices` with a provenance section, a signed
  scenario-named band, everything derived from config, league-wide divisor, and a shared
  largest-remainder `allocate_flex`.
- **Evaluator verdict: REJECTED** (DI-EVAL-5; artifact `bf93f1d`. B2 and B4 confirmed closed at
  `e21fb32`; B1, B3, B5, B6, B7, m1 and m2 all still present).
  **B1 — `prep.py` has 97% line coverage and ~8% mutation coverage, and the keeper double-count
  audit does not reach it.** Eleven of twelve mutations to `prep.py` escaped the full 444-test
  suite at `bf93f1d`; ten of twelve still escape at `e21fb32` after DI-049's claimed "39/41".
  Both halves of the §10-Critical keeper double-count are among them, and both produce a
  materially wrong printed board with a green suite:
  - `roster_live = roster_full` (keepers not removed from **supply**) → the report prints
    "**160** roster spots remain", QB/RB/WR/TE startable counts all shift, and the top asset
    re-prices **$26.60 → $22.01**, a 17% under-price.
  - `seat_keepers({})` (keeper slots not removed from **demand**) → "**100** starting slots
    remain" and QB need 20 instead of 13.
  The underlying functions *are* asserted (`tests/test_quant.py` pins 80 and 140 on the real
  fixture), but `prep.py` re-wires the pipeline by hand in ~55 lines and that wiring is asserted
  nowhere. Also escaping: `price=1` for every optimizer candidate (destroying sections 6 and 7),
  and printing `board.available()[-30:]` — the **worst** 30 players — as "THE PRICED BOARD".
  **B2 — arithmetic defect in the `_priced_board` band (closed at `e21fb32`).** At `bf93f1d` the
  band was `[base, base × (high_ratio/low_ratio)]` irrespective of which scenario the board was
  priced under, so it ran the wrong way whenever loaded keeper prices come in *below* the 75%
  rule — the charter's expected case. Reproduced by scaling the fixture's keeper amounts to 40%:
  as-loaded 1.1839×, under-rule 1.0747×, top player LIVE $33.18, correct band **$29.96–$33.18**,
  printed band **$33–$37** — both ends too high and the top corresponding to no scenario the model
  computed.
  **B3 — section 3 mixes two different market-value bases inside one block, and a human cannot
  reconcile it by hand.** `KeeperLine.book_value` comes from `PlayerValue.market_value` (our
  model) while `rule_price` comes from the `MarketValues` provider. The user's own row prints
  "Allen, London book **50**" — built from a $26.17 model value — directly above
  "ALERT Me: Josh Allen loaded at $39, **rule implies $27**", which requires a $36 book value. The
  same split moves the headline under-rule keeper surplus from **+$113** (model book − provider
  rule prices) to **+$135** (provider on both sides), a 20% swing on the number §1.1 calls "the
  single most actionable pre-draft output of the whole system". §4.9 exists so the user can argue
  with the board; these two numbers cannot be reconciled from the page.
  **B4 — section 4's own arithmetic contradicted itself (closed at `e21fb32`).** Needs printed as
  QB 13 / RB 20 / WR 19 / TE 16 / K 10 = **78**, three lines above "**80** starting slots …
  remain", because `demand.remaining_flex // len(FLEX_ELIGIBLE)` dropped two FLEX slots to
  integer division.
  **B5 — §4.9 item 1 is not fully rendered.** It requires tier and positional rank *per player*
  and the board "sorted and sliced by position". The report prints one unsegmented top-30 with
  neither column. Criterion 1 ("all seven sections render") is met only at heading granularity —
  which is also all `test_every_charter_section_is_present` checks.
  **B6 — the `low` column is degenerate.** On all 30 rows of the shipped report `low ==
  round(LIVE)`, so a three-column "range" carries two identical numbers on every line.
  **B7 — target walk-away prices are sampled on a $3 grid and presented as exact.** Section 7 says
  "the MOST you should pay" with no disclosure of the grid; six of twelve targets land on the same
  $22 rung, and the top target reads **$25** against **$26** at $1 resolution.
  **m1 — prose contradicts the data directly beneath it:** "surplus by position (§4.6:
  concentration at QB confirms the scarcity thesis)" prints immediately above `QB $-51`, the most
  negative of the three positions.
  **m2 — section 4 prints K supply 6 against demand 10 (ratio 0.60) with no flag**, in a report
  whose §4.2 mandate is to hard-error when supply falls below demand without prices responding.
  **What holds, verified by running.** All seven headings render; tiers are genuinely derived from
  the board rather than declared; the config tripwire prints above the board; the report is
  written to `reports/prep.txt`; `make prep` completes in **46 s** (the ~90 s claim is
  conservative); `ruff`, `ruff format --check` and `mypy --strict` are clean. The **2QB check
  passes on substance**: base QB 20, keeper-occupied 7, remaining 13, live rostered QB 18 (inside
  §4.2's 17–21 band), and a 1QB counterfactual on the same fixture moves QB replacement 227.8 →
  262.7 and the top available QB $17.74 → $11.98, a 48% 2QB premium. Every §4.3 invariant
  reconciles by hand: `Σ market = 1999.93`, `Σ baseline = 1451 = total_live_money`, `549 + 1451 =
  2000`; `keeper_inflation = 1451/1510.24 = 0.9608`; `1623/1510.24 = 1.0747`; surplus `489.69 −
  377 = +113` and `489.69 − 549 = −59`; and `SK $377` reproduces exactly as
  `Σ floor(0.75 × round(provider market value))` over the 20 keepers.
  **Cross-cutting (not this card's, raised here because the report renders it):** the tier
  thresholds are unpinned — `BREAK_MULTIPLE` 2.5 → 1.2, `MIN_TIER_SAMPLE` 6 → 2, `>=` → `>`, and
  dropping the first gap from the median all escape the suite — so the printed tier sheet's actual
  content is unverified even though the mechanism is well tested on synthetic gaps.

---

### [DI-047] Close adversarial evaluation round 1 findings

- **Sprint:** 2 · **Owner:** orchestrator · **Size:** M · **Branch:** `di-047-eval-round1-fixes`
- **Context:** DI-EVAL-4 evaluated `c9eb210`, which predates DI-046, so its B1/B2/M1/M3/M4
  substantially match code review's B1/M2/M4/M5/M6 and were already closed. Reached
  independently, which is corroboration rather than duplication. What follows is what DI-046
  did **not** close.
- **Acceptance criteria:**
  - [x] **M2 (new)** Excel writes a byte-order mark on every CSV it exports. Read as plain
        utf-8 it arrives glued to the first header name, so `name` becomes `\ufeffname`, the
        column lookup finds nothing, and a file with every value correct resolves zero rows
        under a message blaming the columns. `encoding="utf-8-sig"`.
  - [x] **B1 survivor (new)** DI-046's rule blocked only when the two API fields *agreed*. The
        evaluator's payload — `draft.settings.rounds = 14` against a 16-slot roster, a legal
        ADR-0005 league — still only warned, and that warning is indistinguishable from the
        known-stale 15 among three other routine ones. `draft_rounds_api_known_stale` records
        the *one* value we have diagnosed; any other value blocks, because "probably stale too"
        is a guess about the field that scales every price.
  - [x] **Four tests that passed for the wrong reason**, all of the shape this project keeps
        producing:
        - `test_rank_transfer_preserves_the_ladder_exactly` — 4 players against 4 rungs holds
          for any implementation assigning the rungs to distinct players. Every ladder in the
          suite was already sorted descending, so removing `sorted(..., reverse=True)` changed
          nothing — and that sort is load-bearing, because `cli.value` hands in a list ordered
          by `baseline_value`, which puts every keeper at the bottom at $0.
        - `test_a_thin_file_falls_through…` — `assert pid not in result.notes` is whole-element
          membership on a tuple of strings; a note reading `"...LEAKED <pid>"` satisfies it.
          (Already replaced in DI-046 when the gate was removed.)
        - `test_two_extra_bench_spots_warn_but_do_not_block` — `config.auction_pool == 160` read
          a config the mutated payload never touched, so it passed under `teams * roster_size`
          too. Now compares two configs that actually differ in roster capacity.
        - `test_the_equivalence_gate_is_not_vacuous` — `broken_b` and `const` were the identical
          expression, under a comment claiming the duplication had been fixed. Since
          `good_a == good_b` is asserted elsewhere, the third arm was implied by the second. The
          third arm now finds the *right number* of keepers and the *wrong ones*, which is the
          failure a count-based check cannot see.
  - [x] **Mutation escapes** closed with tests that pin the boundary rather than a value far
        from it: `ADP_SENTINEL` 900→100 and `>=`→`>` (parametrised at 499 / 899 / 900);
        `dollars < 0`→`<= 0` ($0 is a legal price, a negative one is a typo); the position
        cell's `.upper()`; `blocking("teams", …)`; `starting_slots` `sum`→`max`.
  - [x] **20/20 mutation-verified**, including the corroboration branch, which a first pass
        showed to be unreachable — every existing test reached its block through the
        undiagnosed branch instead, so deleting the corroboration check left the suite green.
- **Evaluator's three standing audits: PASS**, independently re-derived — numerical sanity
  (Lamb 270.5 − 128.4 = 142.1 VORP, 1 + 142.1×0.1802 = 26.60, matching the printed board), the
  2QB keeper adjustment (full 25 QBs rostered, live 18, difference exactly 7), and keeper
  double-counting (all four naive variants built and shown to diverge: 212.2 / 262.7 / 247.8 /
  212.2 against the correct 227.8).
- **Not reproduced:** the evaluator read `int`→`round` and `MIN_COVERAGE_FRACTION` 0.5→0.9 and
  `max(1,…)`→`max(0,…)` as escapes. All three concern the coverage gate, which DI-046 removed
  when it made providers layer; the constant is now reported rather than enforced.

---

### [DI-046] Close review round 1 findings

- **Sprint:** 2 · **Owner:** orchestrator · **Size:** M · **Branch:** `di-046-review-round1-fixes`
- **Acceptance criteria:**
  - [x] **B1** `draft_rounds` blocks when `draft.settings.rounds` and `len(roster_positions)`
        agree against the config, and warns while the API disagrees with itself. Two-sided.
        ADR-0005's self-contradiction struck, and both of its false compensating controls
        removed rather than quietly dropped.
  - [x] **B1b** `validate()` runs on the pricing path, not only on `smoke`. The auction pool,
        budget and draft start print above the board.
  - [x] **M2** CSV comments and blanks are dropped *after* parsing, so a quoted field containing
        a newline no longer crashes the pricing run. True file line numbers via `reader.line_num`.
  - [x] **M3** every provider's unresolvable rows reach the user, prefixed with their source.
  - [x] **M4** the ADP ladder's total is preserved only when the ranked list covers it; the
        docstring said otherwise and the shortfall is now reported in dollars.
  - [x] **M5** the retention table's arithmetic reproduces by hand: the value is rounded to
        dollars once and both the display and the rule use that figure.
  - [x] **M6** providers are **layered**, not winner-take-all. Twenty real keeper values are
        twenty real values. Provenance recorded per player.
  - [x] **m1** the `pid not in result.notes` tautology replaced.
  - [x] **m2** ADP's uncovered count measured against the priced players, not the payload.
  - [x] **m3** every spelling of the draft start collapses to one; a non-numeric `start_time`
        warns rather than raising.
  - [x] **m4** the blocking roster message names the configured value.
  - [x] **m5/m7** the CSV template's description of comment handling corrected; player names
        removed from source prose.
  - [x] **m6** the blank-`player_id` branch covered.
  - [x] 18/18 mutation-verified across `market.py`, `config.py`, `keeper_board.py`
- **Open question for the orchestrator (m7):** §1's CRITICAL DATA RULE reads literally as "any
  player name appearing in source outside of a clearly-labeled test fixture is a review-blocking
  defect", but `domain/keepers.py` has named two players in prose since Sprint 1 to explain the
  collision hazard. New code avoids names entirely; the existing precedent is untouched. Whether
  prose exceptions are allowed needs settling before a future reviewer rejects them.

### [DI-048] Close code review round 2 findings (DI-033 → DI-039)

- **Sprint:** 2 · **Owner:** orchestrator · **Size:** L · **Branch:** `di-048-review-round2-fixes`
  · **PR:** #15
- **Review artefact:** `di-039-make-prep` @ `29fab99`. Reviewer independent of the author per §6:
  three of the seven cards APPROVED, four REJECTED. 1 blocking, 5 major, 3 minor, and one of my
  own recorded deviations judged not sound.
- **Acceptance criteria:**
  - [x] **B1** `make prep` no longer prints a *different draft's* money as this league's keeper
        prices. `_retention_prices()` consults `config/keepers.yaml` first and falls back to the
        mock only as a labelled fallback; a new `KEEPER PRICE PROVENANCE` section states on the
        page whose numbers the reader is looking at. A manifest price set to commissioner
        authority now wins, pinned end to end.
  - [x] **M1** the DP chooses starters on `points - λ x vorp`, the objective it is optimising,
        not on `points`. `RosterCandidate.starter_priority()` is used by both `_position_table`
        and `_split_lineup`; dominance pruning compares both dimensions.
  - [x] **M1 (oracle)** `random_pool` draws VORP independently of points, so the CBC oracle can
        see the axis the defect lived on; seed sweep 12 → 30. That surfaced a *second* oracle
        bug — the ILP permitted empty starting slots while eligible players benched. Brute force
        confirmed the DP was right (a legal lineup is maximal) and the ILP was rewritten with
        big-M maximality constraints. Second oracle defect found this project; both were the
        oracle's, not the DP's.
  - [x] **M2** the priced board's band carries its sign, and each column is named for the
        scenario it prices.
  - [x] **M3** §4.6's two missing aggregations built: per-price-bucket and league-wide
        distribution with a per-pick z-score.
  - [x] **M4** the user's seat and keeper spend are derived from `config/owners.yaml` and the
        ledger. The hardcoded $55 was another manager's figure and the report contradicted its
        own surplus board by $7; the derived figure is $62 and the two now agree.
  - [x] **M5** the walk-away price is found by binary search over the delta rather than by
        `max(positive)` over a sampled grid, which could not distinguish a real crossing from the
        top of the grid — $58 reported against a true $117.
  - [x] **m1** effective buying power divides by the league, not by the teams that happen to hold
        keepers, which inflated every other team by $22 the moment one team kept nobody.
  - [x] **m2** shared largest-remainder `quant/slots.py::allocate_flex`, used by both `prep.py`
        and `inflation.py`. The need column summed to 78 against the 80 printed two lines below.
  - [x] **m3** the candidate cap reserves its bottom `slots` places for the cheapest survivors,
        so it can no longer turn a buyable board infeasible; where it does bite, the note says
        the search covered only the capped list, and `prep.py` carries the optimizer's notes to
        the page instead of printing a bare `infeasible`.
  - [x] **m4** the `drops_out_above` docstring states what the function does.
- **Deviation (a) WITHDRAWN.** I recorded §4.5's forward positional inflation as degenerate. The
  reviewer showed the argument attacked a *value*-proportional allocation; §4.5 allocates by
  need. Slot-proportional allocation gives genuinely distinct per-position figures (QB 0.78x,
  RB 0.42x on the real board), so the deviation is withdrawn and
  `inflation.py::forward_positional_inflation` implements the charter's formula.
- **Reviewer verdict:** pending (round 2 not yet commissioned).
- **Evaluator verdict:** pending.

### [DI-049] Mutation-verify DI-035 through DI-039

- **Sprint:** 2 · **Owner:** test-engineer · **Size:** M · **Branch:** `di-048-review-round2-fixes`
  · **PR:** #15
- **Why the card exists:** the round 2 reviewer flagged that DI-035 through DI-039 were never
  mutation-verified, and the cards said so honestly rather than hiding it. That is the largest
  verification gap in Sprint 2 and it sits under the optimizer, which every price on the page
  eventually routes through.
- **41 mutations across seven modules. 39 caught; 1 provably equivalent; 1 escape survives as
  documented-equivalent.** Ten escaped on the first pass and nine were real gaps.
- **Acceptance criteria:**
  - [x] `optimizer.py` 13/13 — starter ordering at all three call sites, dominance in each of
        its three dimensions, the slot-aware rule, the cap's reserve, the capped-infeasibility
        note, FLEX enumeration
  - [x] `walkaway.py` 4/4 · `tiers.py` 4/4 · `skew.py` 3/3 · `inflation.py` 4/4
  - [x] `tendencies.py` 7/8 (one equivalent) · `overrides.py` 5/5
  - [x] every escape either closed by a test or shown equivalent in writing; none waved through
- **Two production changes came out of it**, both about failure modes rather than wrong answers:
  - `_prune`'s cap reserves its bottom `slots` places for the cheapest survivors. Truncating a
    points-sorted list keeps the players you cannot afford and discards the ones you can, so the
    cap could turn a buyable board infeasible — and then say so flatly. Feasibility after the cap
    now holds whenever it held before it.
  - `_find_crossing` carries the iteration bound its own halving argument justifies. The
    off-by-one mutant did not fail, it **hung**: `(low + high) // 2` with `low == high - 1` sets
    `low = low` forever. It span at 100% CPU for eleven minutes and wedged the first batch, which
    is precisely what it would do on draft night — the walk-away curve is in the hot path, and a
    hang gives the operator nothing at all while the clock runs.
- **A note on testing private helpers.** Six of the nine closed escapes are pinned directly on
  `_prune`, `_slope` and `_find_crossing`. That is deliberate, not laziness: a correct prune
  never changes the answer, so no assertion about `best_roster`'s output can observe it working,
  and the two escapes there both *keep more candidates* — they cannot produce a wrong roster,
  which is exactly why nothing saw them. `_gini` was already pinned this way in Sprint 2 for the
  same reason; this follows that precedent rather than inventing a public surface to reach
  through.
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

### [DI-050] Close adversarial evaluation round 2 findings (DI-033 → DI-039)

- **Sprint:** 2 · **Owner:** orchestrator · **Size:** L · **Branch:** `di-050-eval-round2-fixes`
- **Evaluation artefact:** `di-039-make-prep` @ `bf93f1d`, evaluated in an isolated worktree
  while DI-048/DI-049 were in flight; the evaluator re-ran every finding against `e21fb32` and
  marked which persisted. Three cards APPROVED (DI-033, DI-034, DI-038), four REJECTED.
- **It also disproved my own withdrawn deviation independently**, reaching the same conclusion
  about §4.5's forward positional inflation that DI-048 had already reversed — from a different
  direction, which is worth more than agreement would have been.
- **Acceptance criteria:**
  - [x] **E1 — the DP returned lineups that field nobody.** The evaluator's reproducer no longer
        fired at HEAD, so I wrote my own adversarial sweep with VORP decoupled from points:
        **66 mismatches in 1,500 states, with the DP scoring HIGHER than brute force.** It was
        returning an objective of 202 on a two-player roster with **no starters at all**, while a
        FLEX slot sat open and both eligible players sat benched. The FLEX split is committed
        before the players are known, so it can hand a slot to a position the roster then buys
        nobody at; a benched player is worth `λ x vorp`, so that fiction can outscore every legal
        lineup, and the DP maximises over splits. `_split_lineup` now reassigns spare FLEX room,
        and the objective is scored from the reported lineup rather than the table cell that
        found it.
  - [x] **E1b — the precondition, stated and checked.** `λ x vorp <= points` for every candidate
        is what makes the search exact: **0 mismatches in 1,500 states** inside it. It holds here
        by construction but `Candidate` does not enforce it and DI-038 overrides `points` without
        `vorp` — the same shape as the M1 precondition that was a defect — so `best_roster`
        checks it per call and reports `NON-DOMINANT BENCH` rather than assuming it.
  - [x] **E2 — the latency table timed the wrong thing.** §4.7b budgets the *curve*; the
        docstring reported one `best_roster` solve, understating the real cost ~40x. Measured:
        one 14-slot curve was **39.3s**, and ADR-0003's `top=25` precompute **16 minutes** per
        settled pick. A shaped display grid cut the curve to **11.1s** and the precompute to
        4m26s, with no loss of accuracy in the walk-away price, which comes from a binary search
        over the full range — the M5 fix is what made a coarse grid safe. The real figures are
        now in the table, including that **none of them meets 200ms** and why that is a question
        about the precompute window rather than the lookup. Profiling says 91% is in
        `_solve_split`'s combine, not `_position_table`, so the obvious next optimisation would
        buy nothing; the real fix is DI-051.
  - [x] **E3 — `prep.py` was 97% line-covered and ~8% mutation-covered.** Deleting the keeper
        subtraction, ignoring which positions keepers occupy, and zeroing keeper spend all passed
        the suite. The last re-priced all 140 players by 40% — top asset $26.60 → $37.32 — with
        nothing failing. The board now prints its own money identity ($1,451 of talent against
        $1,451 of live money) and all three are pinned against config and the picks feed instead
        of against the report's own output.
  - [x] **E4 — `test_the_curve_falls_as_the_price_rises` asserted on a flat line.** Every
        alternative on its board cost $1, so all ten deltas came out at 100.0, and a constant
        list is `sorted(reverse=True)`. Repriced onto a real quality ladder. Separately
        `_is_monotone` had no test at all — replacing its body with `return True` survived, and
        that flag is the tripwire `make prep` prints BROKEN off.
  - [x] **E6 — DI-037's headline claim was untestable as written.** Its fixture gave one manager
        eight *consecutive* picks, so `competitive_seq` was the list index plus a constant, and a
        least-squares slope is invariant under shifting x — fitting on `enumerate()` produced the
        identical number. An interleaved fixture separates them by exactly the interleave factor.
  - [x] **E7 — my shipped string was false.** It said no field anywhere in the payload carries
        nomination behaviour; `draft.metadata` carries five. Corrected, and recorded as
        **api-findings Finding 11** — see below.
  - [x] **E8 — section 3 mixed two value bases silently.** `book` is this model's full-market
        valuation (what §4.3 measures surplus against); the 75% rule is written against Sleeper's
        auction value, so `rule implies` is applied to the market *provider's* consensus. Both
        are right in their own terms and neither was derivable from the other on the page. Both
        columns are now shown and labelled.
- **⚠️ ESCALATED — api-findings Finding 11. ✅ ANSWERED 2026-09-02.** The public draft object
  carries `nominating_slot`, `nominated_player_id`, `offering_slot`, `offering_user_id` and
  `highest_offer`. Three of those are things charter §2's ⛔ Hard Constraint states have no
  public feed, and the entire hybrid manual-entry architecture is derived from that claim. No
  code was added and no architecture changed here; it was put to the orchestrator, whose answer
  is **the manual layer is retained and §2's hybrid architecture stands**. The observation value
  is carded separately and non-load-bearing as **DI-052**.
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending (round 3 not commissioned).

### [DI-051] Solve the walk-away curve as one DP read at many budgets

- **Sprint:** 3 · **Owner:** quant · **Size:** L · **Dep:** DI-050
- **Why:** a curve is dozens of independent solves, and the whole knapsack is repeated for each
  of the six FLEX splits at each of ~46 price points. Forcing a player at price X only shifts
  that player's own position table along the budget axis; everything else is identical across
  the curve. Solving once and reading the combined table at many budgets is the difference
  between a 4m26s precompute and one that fits between picks.
- **Measured starting point** (real 140-player pool, 14 slots / $185, after DI-050's grid fix):
  curve 11.1s, of which **91% is inside `_solve_split`'s combine** and 8% in `_position_table`.
  Caching position tables across price points — the obvious first move — is therefore not the
  fix, and this card exists so nobody spends a day discovering that.
- **Acceptance criteria:**
  - [ ] the curve is exact against the current implementation on the real board, every point
  - [ ] `top=25` precompute fits inside a 30s between-picks window at 8 open slots
  - [ ] the 14-slot case is stated honestly if it still does not fit, rather than tuned around

### [DI-052] Log the live nomination feed as observation only

- **Sprint:** 3 · **Owner:** data-engineer · **Size:** S · **Dep:** DI-050
- **Decision that produced this card (2026-09-02):** api-findings Finding 11 established that the
  public draft object carries `nominating_slot`, `nominated_player_id`, `offering_slot`,
  `offering_user_id` and `highest_offer` — three of them things charter §2's ⛔ Hard Constraint
  states have no public feed. Escalated rather than resolved, per §1. **The orchestrator's answer
  is that §2's hybrid architecture stands: the manual entry layer is retained as the live
  nomination path.** This card is the residue — the observation value, with none of the
  dependency.
- **The distinction this card exists to hold.** Logged, never read back on the night. Nothing in
  the cockpit, the optimizer, or the ledger may consume these fields, so a shape change, a
  rename, or a missed sample degrades a Sprint 3 analysis and cannot touch live bidding. That is
  what makes building on an undocumented field acceptable here and unacceptable in §2's sense:
  the risk §2 was written against is *dependency*, not *observation*.
- **Why it is small.** `SleeperClient.draft()` already fetches this object and the poller already
  runs on a 1s floor. The work is a second call beside the picks poll, an event type, and a
  dedupe on `(nominating_slot, nominated_player_id)` so an unchanged nomination is not re-logged
  every second.
- **⏳ The deadline is the draft itself.** These fields are a single live slot, overwritten by the
  next nomination, and the picks feed carries no nominator — confirmed across all 160 mock picks.
  So the history exists only if it is recorded as it happens. Not done before the first
  nomination on 9/5 means §4.6's fifth manager tendency stays unavailable for this draft, which
  is the status quo and an acceptable outcome; it is stated here so that is a choice rather than
  a discovery.
- **Acceptance criteria:**
  - [ ] nomination samples appended to the event log, keyed on `draft_slot` per D1
  - [ ] deduped: one event per distinct nomination, not one per poll
  - [ ] **no read path** — a test asserts the ledger, optimizer and cockpit are unchanged when
        the feed is absent, malformed, or renamed
  - [ ] a missing or reshaped field logs a warning and is otherwise inert; never raises
  - [ ] DI-037's `Profile.unavailable` string updated only once real samples exist, never before
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

### [DI-053] Close the last three open Sprint 1 blockers

- **Sprint:** 1 · **Owner:** data-engineer · **Size:** M · **Branch:** `di-053-payload-cross-checks`
- **Why now:** the status summary still reads 🟥 REJECTED for Sprint 1 on DI-EVAL-2, and all of
  Sprint 2 is built on it. Re-ran every finding at HEAD before touching anything: **B2 (poller
  raising on `inf`/`nan`) and B3 (the dead-ended rejects channel) are genuinely closed** —
  `parse_amount` complains instead of raising, `replay_rejects` reaches `state.rejects`, and
  `cli.replay` prints them. What was still open is below. One reported symptom did not
  reproduce and is recorded as such rather than "fixed".
- **Acceptance criteria:**
  - [x] **The duplicated payload fields are cross-checked, not merely fallen back on.** The
        Sprint 1 design said `metadata.slot` "duplicates `draft_slot` and is used as a
        cross-check"; what shipped was `a or b`, which takes the primary and never looks at the
        duplicate again. Neither `draft_slot` nor `player_id` was ever compared, so a payload
        where the two disagree parsed clean and silent. **Neither disagreement shows up in money
        conservation**, which is what makes this the charter's named failure mode: a wrong slot
        debits the wrong team while the total still reconciles to $2,000, and a wrong
        `player_id` leaves the player actually bought sitting on our available board, so the
        tool keeps recommending bids for somebody already rostered.
  - [x] the pick is **kept** on a conflict, primary wins, complaint surfaced — dropping loses a
        roster spot and its dollars *as well as* being wrong, and `state.rejects` is printed
  - [x] the legitimate fallback (primary absent, duplicate present) stays silent, or all 160
        mock picks would report a conflict they do not have
  - [x] **`max_bid` can no longer exceed the team's budget.** A sign-flipped amount makes `spent`
        negative and `remaining` larger than the budget, and this returned **$686 in a $200
        league**. An earlier round added an alert and *deliberately* left the figure, on the
        principle that masking corruption is how it survives to draft night. That principle is
        right for `spent` and `remaining`, which are facts and are still exact — and wrong for
        `max_bid`, which is a *recommendation* read by the optimizer and the affordability
        ladder, neither of which reads `state.alerts`. The alert was necessary and not
        sufficient. The superseded assertion is documented at the point of change.
  - [x] **`KeeperClassifier.armed` is wired into the product path.** It is the charter's
        classification mechanism #4 — an unmatched pick inside the ceremonial window is FLAGGED
        for confirmation rather than silently treated as a competitive bid — and it was set
        `True` by nothing outside `tests/`. The backstop existed and never ran. The manifest is a
        file typed in August; the ceremonial picks land in the first twenty on the night; a
        keeper swapped afterwards matches nothing. On the real fixture with one manifest key
        dropped: unarmed **141 competitive**, armed **140 competitive + 1 FLAGGED** — exactly the
        restoration DI-EVAL-2 M1 said the backstop should produce.
  - [x] arming changes **nothing** on a fully-resolving manifest, pinned by comparing whole
        folded states, so the replay gate's exact reproduction cannot move with the switch
  - [x] FLAGGED picks are **printed** by `cli.replay`, naming slot, pick, player and price. A
        classification nobody sees is not a backstop; the thing that has to happen is a human
        confirming or denying it, and they cannot do that from a count.
- **Did not reproduce.** DI-EVAL-2's "pick 50 is missing player_id" reject no longer fires,
  which looked at first like a regression in the rejects channel. It is not: the parser falls
  back to `metadata.player_id`, which the fixture also carries, so clearing only the top-level
  field is not actually a malformed pick. Clearing both still rejects correctly and loses the
  pick's $20 loudly. My first probe was wrong, not the code — recorded because the next person
  to read that finding will construct the same wrong probe.
- **Still open from DI-EVAL-2 M2** (test-quality, not defects): `test_max_bid_never_strands_a_team`
  lacks the precondition its property-test twin has, `test_manual_keeper_counted_exactly_once`
  passes one drawn slot to both sides, and `test_ledger_reconciles_exactly_with_overrides` draws
  exactly the in-league range. The underlying behaviours are covered by named gate tests, so
  these are weak tests rather than holes. Not closed here; carried as **DI-054**.
- **Reviewer verdict:** pending. · **Evaluator verdict: REJECTED** (DI-EVAL-6; artifact
  `di-054-weak-tests` @ `26c8a12`, evaluated in an isolated worktree). All three headline
  behaviours were reproduced and are pinned by named tests — disabling the cross-check, dropping
  the `str()` normalisation, removing the `max_bid` clamp and disarming the product classifier
  are each CAUGHT. The dropped-key figures reproduce exactly (unarmed 19 KEEPER / **141**
  COMPETITIVE; armed 19 / 140 / **1 FLAGGED**), armed ≡ unarmed byte-for-byte on the full
  manifest, `$686 → $186` with `spent -500` / `remaining 700` still exact, and a corrupted
  `draft_slot` on the real fixture debits slot 4 instead of slot 3 while the room still totals
  $1,979 — reported as `REJECT pick 30 (A.J. Brown): draft_slot is 4 but metadata says '3'`.
  Rejected on two items.
  - **E1 (blocking, still open at `ed8b66a` after DI-055).** The identity guard tests `is None`,
    not falsiness, and Sleeper's empty value for a string field is `""` — `team_abbr` and
    `team_changed_at` are `""` on all 160 real rows, `picked_by` on all 160, `injury_status` on
    122. With top-level `player_id: null` and `metadata.player_id: ""`, `parse_pick` returns
    `PickSnapshot(player_id='')` **with no complaint at all**. Folding the real fixture with
    pick 30 in that shape: `total_spent 1979`, `rejects ()`, `alerts ()`, `orphans ()` — and
    A.J. Brown, bought for $32, is on nobody's roster and stays on the available board all
    night. Money conservation holds exactly while the ledger is nonsense, on the four lines this
    card rewrote, in the field this card added a cross-check for. The `slot` twin of the same
    shape is caught only incidentally, because `int("")` happens to raise. DI-055 m2 fixed the
    *primary*-empty direction; the metadata-empty direction is untouched. Fix: treat `""` as
    absent in the fallbacks, the `missing` guard and the conflict predicate.
  - **E2 (criterion disproved).** "Arming changes **nothing** on a fully-resolving manifest" is
    a property of `fixtures/picks.json`, whose 20 ceremonial picks occupy exactly `pick_no`
    1..20 — not of the code. Two reproductions with a 20/20-resolving manifest where arming
    moves the ledger: swap `pick_no` 20↔21 and a genuine $37 competitive bid (slot 5, player
    8138) is FLAGGED, competitive 140→139; and the realistic one — the commissioner pre-loads
    only 19 keepers, so the **first real nomination of the night** lands at `pick_no` 20, is
    FLAGGED, and every one of the 139 remaining `competitive_seq` indices shifts. Independently
    found; DI-055 reaches the same conclusion and reverses the default, so E2 is closed there.
  - **Non-blocking.** (a) `min(self.remaining, self.budget)` clamps against a bound a mistyped
    override controls: `BudgetAdjustment(slot=1, delta=10000)` yields budget $10,200 and
    **`max_bid` $10,185 with zero alerts**, `override_delta` exactly accountable, every property
    test green — also found by DI-055 M2. (b) The arming boundary `pick_no <= 20` survives being
    changed to `<` across all 517 tests (DI-055 M4). (c) `competitive_seq`'s
    `is PickClass.COMPETITIVE` filter survived at `26c8a12` when weakened to `is not KEEPER` —
    the mechanism this card armed, with nothing asserting its consequence; now CAUGHT at
    `ed8b66a`. (d) Conflicts are discarded whenever the row also carries an amount complaint
    (`grumbles = [] if complaint else [...]` survives all 517) and whenever validation fails.
  - **Standing audits, all passed at `26c8a12`.** *2QB:* 10 × 2 = 20 QB starting slots, 7 QB
    keepers, **13 remaining** — verified from the resolved manifest. *Keeper double-count:*
    supply drops the 20 ids once (`roster_live` 160−20=140) and demand seats each keeper into
    exactly one bucket (3 WR → 2 base + 1 FLEX; 3 QB → 2 base + 1 bench, remaining QB 18 not 17;
    2 teams × 2 QB → remaining 16), and full-vs-live rostered counts differ by exactly the
    per-position keeper counts (QB 25→18, RB 41→35, WR 59→52, TE 25→25, K 10→10). *Ceremonial
    contamination:* the Case A twin (`is_keeper` only, empty manifest) equals Case B (full
    manifest, `is_keeper` false) on the ledger, the competitive count, skew overall/by-position/
    by-team, positional inflation, the whole 140-point inflation curve and all ten tendency
    profiles; misclassifying one ceremonial pick moves mean edge skew $4.01→$4.90, RB inflation
    1.3585→1.4371 and the entire curve, so the filter is load-bearing. *Numerical sanity:*
    re-derived on paper, `dpv` 1840/9770.98 = 0.188313 (code 0.1883), `dpv_live` 0.180166 (code
    0.1802), CeeDee Lamb $27.76/$26.60, Nico Collins $26.16/$25.07, Brock Bowers $24.56/$23.54 —
    exact to the cent; ΣMV $1,999.93, ΣBV $1,451.00 = live money exactly.
  - **Two findings outside both cards, for new cards.** (i) The *mirror* of the double-count is
    unguarded: if two owners list the same player, demand removes 20 starting slots while supply
    removes 19 players (`roster_live` 141) and `manifest_keys(require=20)` still passes because
    the `(slot, player_id)` keys differ — every price shifts, nothing alerts. (ii) The priced
    pool (top-160 by VORP) and the pool the replacement fixed point solved for are not the same
    160: 31 QB / 6 K priced against 25 QB / 10 K rostered, so four kickers the league must buy
    carry `market_value 0.0` and render as `--`. All affected players sit at VORP 0, so the
    dollar effect is $6 of $2,000 and no real price moves — but the two halves of the model
    disagree about who is in the pool.

### [DI-054] Close DI-EVAL-2 M2 — three tests that could not fail

- **Sprint:** 1 · **Owner:** test-engineer · **Size:** S · **Branch:** `di-054-weak-tests`
- **Why it is a card and not a footnote:** DI-EVAL-2 filed these as "a test-quality failure
  rather than a coverage hole", which is right and is also exactly how a weak test survives —
  the behaviour is correct today, so nothing is red, and the test stays blind until the day the
  behaviour changes. Each one below is now mutation-verified against the defect it was supposed
  to be watching for.
- **Acceptance criteria:**
  - [x] **Item 1 was already closed and is recorded as such, not claimed.**
        `test_max_bid_never_strands_a_team` has carried its precondition
        (`elif team.remaining >= team.open_slots`) plus a companion
        `test_broke_team_reports_zero_max_bid_and_alerts` since an earlier round. Re-verified at
        HEAD rather than taken from the finding.
  - [x] **`test_manual_keeper_counted_exactly_once` drew one slot and passed it to both sides.**
        So the case the property most needs — the operator types a keeper against the wrong team
        — was never generated. The two slots are drawn independently now, the count is asserted
        across the *whole league* rather than on the one team we happened to look at, and the
        `SLOT MISMATCH` alert is required. Behaviour was already correct: supersession keys on
        the player, the pick wins at its own price, and it is commutative.
  - [x] **`test_ledger_reconciles_exactly_with_overrides` drew `st.integers(1, 10)`** — exactly
        the in-league range, so a mistyped correction for a team that does not exist was never
        drawn. `Slot` validates 1..32 while this league has 10, so slot 11 is a well-formed event
        naming nobody; it is alerted and deliberately not applied. Drawing 1..13 now, and the
        accounting distinguishes applied from stranded.
- **Mutation-verified 3/3**, each against the specific blindness:
  - supersession keyed on `(slot, player_id)` again → **CAUGHT** (was the double-count that
    put a player on two rosters and charged the money twice)
  - orphan slots stop being reported → **CAUGHT**
  - `override_delta` counts adjustments for teams that do not exist → **CAUGHT**
- **Reviewer verdict:** **APPROVED with findings (round 1)** — 0 blocking, 0 major. All three
  claimed mutations independently re-run and confirmed, each caught by the strengthened test
  itself rather than by a neighbour. Item 1's "already closed" claim verified as accurate.
  Findings, all minor and all still closed by the wider suite: the same-named property twin at
  `test_properties.py:138` has no lower bound (`max_bid → 0` survives that file, caught only by
  the gate twin); `test_manual_keeper_counted_exactly_once` hardcodes `is_keeper=True`, the one
  value api-findings Finding 5 says never appears on a real ceremonial keeper; and
  `test_ledger_reconciles_exactly_with_overrides` asserts only aggregates, so crediting every
  correction to the wrong team survives it. **Carried to DI-056**, not folded in silently.
- **Evaluator verdict: APPROVED, with one residual blindness in the same test** (DI-EVAL-6;
  artifact `di-054-weak-tests` @ `26c8a12`). Every claim on this card is independently
  confirmed, and the counterfactual the card only asserts was verified rather than taken: each
  of the three defects **SURVIVES** the pre-strengthening form of its own test and is **CAUGHT**
  by the current form. Supersession re-keyed on `(slot, player_id)` → caught by
  `test_manual_keeper_counted_exactly_once`, survives once `pick_slot` is forced equal to
  `manual_slot`. Orphan slots no longer alerted, and `override_delta` counting adjustments for
  teams that do not exist → both caught by `test_ledger_reconciles_exactly_with_overrides`, both
  survive once the draw is narrowed back to `st.integers(1, 10)`. The strengthening is
  load-bearing, not decorative. Item 1 re-verified at HEAD: the precondition and the companion
  test are both present; note the property genuinely cannot exercise the clamp, since
  `event_logs` draws amounts ≥ 0 so `remaining ≤ budget` always — which is what the card says,
  the clamp being pinned by the named money-safety test instead.
  - **Six clean runs CONFIRMED.** `rm -rf .hypothesis && uv run pytest -q`, six times: **517
    passed** every time, 39.6–42.5s. No hypothesis profile is registered in `pyproject.toml` and
    there is no `conftest.py`, so the runs are genuinely re-randomised rather than derandomised —
    the claim means what it reads as. `ruff check`, `ruff format --check` and `mypy --strict`
    also clean.
  - **Residual blindness (not a claim this card made, and still open at `ed8b66a`).**
    `test_manual_keeper_counted_exactly_once` still cannot fail for an *un-superseded* manual
    keeper. It always constructs a pick carrying the drawn `player_id`, so supersession always
    fires and the `for entry in manual.values()` roster branch is never reached in the state it
    asserts on — the test never actually counts a manual keeper, only the pick that replaced
    one. Mutation: book manual keepers as `pick_class=PickClass.COMPETITIVE` → **SURVIVES all
    517** at `26c8a12` and all **527** at `ed8b66a`. The ledger's own docstring calls
    `ManualKeeper` "the *primary* route by which real keeper prices enter"; that entry's class
    drives `keeper_spend()`, the N/20 readout, the `expect_keepers` under-count alert,
    `reconcile()` and the competitive filter, and nothing pins it. Worth folding into DI-056.

### [DI-055] Close code review round 1 on DI-053 — arming reversed

- **Sprint:** 1 · **Owner:** orchestrator · **Size:** M · **Branch:** `di-055-eval-round3-fixes`
- **The blocking finding reversed a decision I made one card earlier, and it was right to.**
  DI-053 armed `KeeperClassifier` on the product path and asserted "arming changes nothing on a
  fully-resolving manifest", pinned by comparing whole folded states. The comparison was real;
  the generalisation was not. `arming_window` is a hardcoded 20, so the claim held only for
  `fixtures/picks.json`, where the ceremonial round happens to occupy exactly picks 1-20.
  Reproduced: strip keeper status from the same 160 picks and arming removes **20 of 160
  competitive picks** — the most expensive of the night — from `competitive_seq`, and so from
  skew, inflation, run detection and every tendency profile. That is precisely the poisoning
  `pick_class` exists to prevent, arriving from the mechanism meant to prevent it.
- **And FLAGGED is terminal today.** `Reclassify` is consumed by the ledger and produced by no
  product path; charter §2's prominent pre-draft toggle is Sprint 3 and unbuilt. Arming a
  backstop before its confirmation loop exists converts a recoverable mistake into a one-way
  trap, three days out. **Deferred to Sprint 3 as DI-057**, to land with the toggle and the
  `Reclassify` producer — and keyed on manifest incompleteness rather than a pick-number count.
- **Acceptance criteria:**
  - [x] **B1** the product classifier ships disarmed; the reversal, and the evidence for it, are
        written where the next reader will look rather than in a commit message
  - [x] **M1** `TeamState.figures_suspect` and `Opponent.figures_suspect`. The clamp only binds
        when the negative amount dominates the whole roster sum — with $100 of real spend and a
        -$40 entry it is inert and the figure is $127 against a true $47, because the information
        was destroyed at ingestion. The bound is a floor on the damage, not a repair; what makes
        the figure safe to publish is that it arrives labelled, and the affordability ladder now
        prints `⚠ FIGURES SUSPECT` *before* the dollar figure it undermines.
  - [x] **M2** the clamp is parametrised over the budget, and a `BudgetAdjustment` is shown to
        raise the ceiling it clamps against. `min(self.remaining, 200)` had survived all 517.
  - [x] **M3** payload conflicts ride on `PickSnapshot.conflicts` and the fold raises them as
        `PAYLOAD CONFLICT` alerts automatically. They were in `rejects` — documented as "this row
        was dropped and took its dollars with it" — reaching the fold only when a caller
        remembered `rejects=`, which defaults to None. Travelling on the pick also means they
        survive the event log, crash-restart and replay.
  - [x] **M4** the arming window's own boundary (pick 20) is pinned; the existing pair asserted
        7 and 21 and never touched the edge
  - [x] **m1** the reversal was argued on a consumer that does not exist — `best_roster` takes a
        plain `budget: int` and never sees a `TeamState`. Corrected in both places it was stated.
  - [x] **m2** the conflict test uses the same truthiness rule as the fallback. `player_id: ""`
        falls through to metadata, so calling it a conflict *and* reporting "the primary field
        wins" was both spurious and backwards — and Sleeper does send `""` on some rows.
  - [x] **m3** `affordability.py`'s module docstring no longer states an identity the clamp broke
- **Mutation-verified 5/5** against the exact escapes the reviewer demonstrated: budget hardcoded
  to 200, arming window off by one, falsy primary reporting a conflict, payload conflicts no
  longer alerting, `figures_suspect` always False. All five **CAUGHT**; all five escaped before.
- **§6 process note (m7), accepted.** DI-053 was owned by `data-engineer` and rewrote an
  assertion in `tests/test_money_safety.py` authored by an earlier round, which §6 forbids
  without routing through `test-engineer`. The reversal was documented and directionally right,
  and it was still self-adjudicated inside the implementing card. Recorded rather than argued.
- **Reviewer verdict:** pending (round 2 not commissioned). · **Evaluator verdict:** pending.

### [DI-056] The next layer of DI-054's finding

- **Sprint:** 1 · **Owner:** test-engineer · **Size:** S · **Dep:** DI-054 · **Branch:**
  `di-056-property-blind-spots`
- Three minors from DI-054's review, each an escape the *file* allows and the wider suite still
  closes — so none was a hole, and all three are the same shape as the finding DI-054 fixed. All
  three re-confirmed as escaping before being closed:
  - [x] `test_properties.py::test_max_bid_never_strands_a_team` bounded `max_bid` from above and
        never from below, so `return 0` satisfied it for every team in every generated log. A max
        bid of zero says "this team is out", and saying that about a team with money in hand
        takes them off the affordability ladder — the display whose whole job is telling the user
        who they are actually bidding against.
  - [x] `test_manual_keeper_counted_exactly_once` hardcoded `is_keeper=True` — the one value
        api-findings Finding 5 says never appears on a real ceremonial keeper, since all twenty
        in the fixture carry `false`. The branch that fires on this league's data was the branch
        the property never generated, and supersession firing *only* for `is_keeper` picks
        survived the file.
  - [x] `test_ledger_reconciles_exactly_with_overrides` asserted only aggregates, so crediting
        every correction to the wrong team satisfied all of them — the sums are identical
        whichever team holds the money. Now asserted per team. Same wrong-team-but-reconciling
        class DI-053's cross-check exists to catch, sitting inside the test written to guard
        corrections.
- **A real defect fell out of the second one.** Drawing `is_keeper` surfaced the third way a
  manual entry and its pick can disagree, and the only one that was silent: entering a keeper
  says "this is a retention, not a bid", and a pick arriving with `is_keeper` false says the
  opposite. The pick wins — correctly, the feed is authoritative — but that quietly moves the
  money out of `keeper_spend()`, drops the N/20 readout by one, and lets a retention price into
  the competitive series as though somebody had bid it. `SLOT MISMATCH` and `AMOUNT MISMATCH`
  have alerted since Sprint 1; `KEEPER MISMATCH` now joins them.
- **Mutation-verified 4/4 against `test_properties.py` alone**, which is the point: each was
  previously caught only by `test_replay_gate.py`, a different file testing a different thing.
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

### [DI-057] Arm the keeper classifier, with its toggle and confirmation loop

- **Sprint:** 3 · **Owner:** data-engineer · **Size:** M · **Dep:** DI-055
- Deferred from DI-053/DI-055. The backstop is genuinely wanted — an unmatched pick inside the
  ceremonial window should be FLAGGED for confirmation, not silently counted as a competitive
  bid — but it cannot ship before the things that make FLAGGED recoverable.
- **Update, DI-073:** the first criterion is **done**. `Reclassify` now has a producer — the
  cockpit's reclassification form, keyed on `pick_no`, reverting cleanly. The reason this card
  was blocked ("arming a backstop before its confirmation loop exists turns a recoverable
  mistake into a one-way trap") no longer holds. What remains is the toggle and the window.
- **Acceptance criteria:**
  - [x] a product path constructs `Reclassify`, so a flagged pick can be confirmed or denied
        — DI-073
  - [ ] charter §2's prominent pre-draft arming toggle exists and is reachable from the CLI
  - [ ] the window keys on **manifest incompleteness** — a slot that still owes keepers — rather
        than a hardcoded `pick_no <= 20`, so a room that holds no ceremonial round is unaffected
  - [ ] FLAGGED picks are surfaced everywhere they matter, not only in `cli.replay`
  - [ ] pinned on a payload where the ceremonial round is *not* at picks 1-20
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

### [DI-058] Close adversarial evaluation round 6 on DI-053/DI-054

- **Sprint:** 1 · **Owner:** orchestrator · **Size:** M · **Branch:** `di-058-eval-round6-fixes`
- **DI-EVAL-6 verdicts:** DI-053 **REJECTED** (one blocking, still open at HEAD after DI-055),
  DI-054 **APPROVED with one residual blindness**. The evaluator independently confirmed the
  6-of-6 clean-run claim, re-derived the valuation arithmetic to the cent, and reproduced the
  Case A/B equivalence and 2QB checks — all of which hold.
- **Acceptance criteria:**
  - [x] **E1 (BLOCKING) — Sleeper's empty value for a string field is `""`, not `null`.** It uses
        it liberally: `picked_by`, `team_abbr` and `team_changed_at` are empty on all 160 fixture
        rows, `injury_status` on 122. The missing-field guard tested `is None`, so with
        `player_id: null` on top and `metadata.player_id: ""` beneath, the fallback selected `""`
        and a `PickSnapshot` with **no player** entered the ledger complaint-free. On the real
        fixture: total spend $1,979 — identical to clean — zero rejects, zero alerts, and the
        $32 player on **nobody's** roster. So the board still shows a rostered player as
        available and the tool recommends bidding on him. DI-055's m2 closed the primary-empty
        direction; this closes the class. Presence is now decided in one place, `_present`.
  - [x] **E1b** zero counts as absent too, and that is a judgement recorded rather than assumed:
        all three guarded fields are 1-based identifiers (`Slot` validates `ge=1`), so `0` is a
        sentinel. Reading it as present would refuse a `draft_slot: 0` row outright and take its
        dollars with it, when `metadata.slot` beside it names the team. Falling back keeps the
        pick, the money and the roster spot; both sources empty still fires the missing guard.
  - [x] **DI-054 residual** — `test_manual_keeper_counted_exactly_once` always builds a pick
        carrying the drawn `player_id`, so supersession always fires and the manual entry never
        survives into the asserted state. It counts the pick that *replaced* a manual keeper,
        never a manual keeper. Classifying manual entries COMPETITIVE survived all 527 tests —
        and `ManualKeeper` is, in `ledger.py`'s own words, "the *primary* route by which real
        keeper prices enter the system". That class drives `keeper_spend()`, the N/20 readout,
        the `expect_keepers` alert, `reconcile()` and the competitive filter.
  - [x] **Attacker-controlled clamp bound** — `max_bid` is bounded by `budget`, and `budget` is
        whatever the corrections made it, so `BudgetAdjustment(delta=10000)` advised a **$10,185
        bid in a $200 league** with the ledger reconciling exactly and nothing looking unusual.
        §4.8 says the correction wins and the next poll must not fight it, so it is still applied
        as entered and still exactly accountable in `override_delta`; what changes is that it
        stops being silent. Ordinary corrections stay quiet, or the alert is tuned out by 7pm.
  - [x] **Surviving mutation** — the competitive filter widened to `is not KEEPER` passed all 517
        at the evaluated commit. Now caught.
- **Mutation-verified 4/4**, each against the exact escape demonstrated. Replay gate still exact:
  $1,979 / 20-of-20 / 140 competitive.
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending (round 7 not commissioned).

### [DI-059] Two findings from DI-EVAL-6 outside both cards

- **Sprint:** 2 · **Owner:** quant · **Size:** M
- Found while evaluating DI-053/054, correctly reported as out of scope rather than folded in.
  Neither is a regression; both are real.
- **Branch:** `di-059-pool-consistency` · **Both closed.**
- **Acceptance criteria:**
  - [x] **The mirror of the keeper double-count is unguarded.** Two owners listing the same
        player removes 20 slots from demand but only 19 players from supply (`roster_live` 141),
        `manifest_keys(require=20)` still passes, every price on the board shifts, and nothing
        alerts. The manifest currently has no duplicates — verified — so this was latent, and
        the manifest is a hand-typed file that changes before draft day. `resolve_manifest` now
        raises `DuplicateKeeper`: a player on two rosters is impossible, and continuing produces
        a board that is wrong everywhere and looks right.
  - [x] **The priced pool and the replacement fixed point disagree about who is in the pool.**
        Top-160 by VORP is 31 QB / 6 K; the fixed point solved for 25 QB / 10 K. Four kickers the
        league must buy render as `--`. The effect is $6 of $2,000 and every affected player sits
        at VORP 0, so it is small — but two halves of the valuation disagreeing about pool
        membership is the kind of thing that stops being small when a setting changes. The pool
        is now derived from the baseline's own `rostered` counts, position by position, so the
        two are one set by construction rather than by coincidence: both read 25 QB / 10 K, and
        the map's K row goes from 6 startable against 10 needed to **10 against 10**.
  - [x] the divergence cannot be quietly reintroduced — a pool whose size disagrees with the
        roster spots being priced raises `InvariantViolation` rather than pricing two different
        auctions against each other. `compute_baselines` guarantees the sum; nothing in the type
        system did, and this card exists because of exactly that gap.
  - [x] the money identity is unmoved: $1,451 of talent against $1,451 of live money, and the
        top-of-board prices are unchanged, because every player this adds sits at VORP 0
- **Mutation-verified 4/4**: pool reverts to a flat top-N, the disagreement guard removed,
  duplicate keepers stop raising, and the live pool reading the *full* baseline's roster.
- **Fixture note.** `hand_baselines` filled in `rostered={position: 1}` because nothing read it.
  Making the pool follow it turned three tests red — correctly: they were passing roster spots
  that their own baselines did not describe. Each now states the roster it means.
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

### [DI-061] The price table route, and manual price overrides

- **Sprint:** 3 (pulled forward at the user's request) · **Owner:** backend-engineer · **Size:** M
  · **Branch:** `di-061-price-route`
- **Why now, out of order:** the user read the board, disagreed with the QB pricing — the top QB
  prices at $17.74, 25th overall, in a league that starts twenty of them — and asked for a way to
  change prices themselves. Charter §4.8 has required per-player overrides since Sprint 0 and
  `quant/overrides.py` has implemented them since DI-038; nothing ever called it. This is the
  surface, and the disagreement it exists to capture is the Sprint 2 gate working as designed.
- **Acceptance criteria:**
  - [x] `GET /prices` renders every available player, sorted by live value, editable in place
  - [x] `GET /api/prices`, `POST /api/prices/{player_id}`, `DELETE /api/prices/{player_id}`
  - [x] **the model's number is retained beside the user's, permanently** (§4.8). "The model said
        $17.74 and I said $40" is a different fact from "$40", and on the night the difference is
        what makes the figure trustworthy or not
  - [x] clearing an override falls back to the model, never to zero — a zero price is a bid
        recommendation
  - [x] an override naming nobody is refused, the same rule `apply_overrides` already enforces;
        a negative price is refused by validation
  - [x] only the named player moves; nothing is renormalised behind the user's back (§4.8)
  - [x] keepers are absent from the page — they are off the board, and pricing them invites a bid
        on somebody already held
  - [x] edits persist to `config/value_overrides.yaml` and survive a restart, verified through a
        *new* store on the same file rather than the one that wrote it
  - [x] the file is a first-class interface: header documenting every field, stable sort order so
        a diff shows the edit rather than a reshuffle, and every read goes to disk so a hand edit
        is never silently ignored
- **`build_pipeline` extracted from `prep.py`** so the page and the printed report are built from
  one chain. Two surfaces computing the same board separately is how they start quoting different
  numbers for the same player — which this project has already done once, in the two value bases
  section 3 was mixing. All 30 prep tests pass unchanged, which is what says the extraction moved
  nothing.
- **Deliberately not the cockpit.** No draft state: no picks, no budgets, no bidding, no
  websocket. Sprint 3 owns those, and this route holds none of them.
- **Storage is a file, not an event.** Overrides are standing corrections to a projection, not
  things that happen during a draft, so they get no seq and no revert. Money and picks stay in
  the event log where reversal is free. Recorded here because it is a real asymmetry.
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.
- **Superseded in part by DI-062.** Two acceptance criteria above are now *wrong* and are struck
  rather than quietly rewritten: "renders every available player" was 140 of 160, and "keepers are
  absent from the page" turned out to hide the one auction value the league's retention rule
  actually reads. See DI-062.

---

### [DI-062] Override every value, for every player

- **Sprint:** 3 (pulled forward) · **Owner:** backend-engineer · **Size:** M
  · **Branch:** `di-062-override-every-value`
- **Why:** the user asked whether DI-061 was "the ability to override all of the project auction
  values." It was not, and three of the four ways it fell short were invisible from the page:
  1. **20 of 160 players were missing.** Keepers were excluded deliberately — you cannot bid on
     one — but their *market* value is the input to `floor(0.75 × auction_value)`, the league's
     actual retention rule. The single most consequential auction value in the league was
     unreachable.
  2. **A points override did nothing.** It was stored, displayed, and applied downstream of the
     valuation, so VORP and every dollar figure kept following the model's projection. The store's
     own header claimed it "moves VORP and every price derived from it." That claim was false.
  3. **A market override did nothing.** It was written beside `PlayerValue.market_value`, the
     model's book value, while the keeper rule reads the *provider* market value from
     `quant/market.py`. The user could type a keeper's auction value and watch the rule price
     not move.
  4. **`overridden` and `delta` never reached the JSON.** Both were plain `@property`, which
     pydantic does not serialise, so `/api/prices` omitted the two fields carrying §4.8's whole
     point — that a typed number is distinguishable from a measured one.
- **Acceptance criteria:**
  - [x] all 160 priced players on the page, keepers included and marked, keepers sorted last
  - [x] four editable fields per row — live $, market $, pts, blacklist — with a name/position
        filter, because 160 rows is past the point of scrolling
  - [x] **a points override is applied upstream of `compute_baselines`**, so it re-derives VORP,
        the replacement baseline and every dollar figure, including other players' by a little
  - [x] **a market override enters as `ManualMarketValues`**, the top-priority provider, so it
        reaches the 75% keeper rule and moves rule price and surplus
  - [x] a market override clears the ESTIMATE badge *for that player* — a number a person
        asserted is an observation; `OBSERVED_SOURCES` names which sources count
  - [x] a keeper cannot be given a live price: 422, not a silently stored bid recommendation for
        somebody already rostered
  - [x] the blacklist zeroes the bid but **not** the valuation — "never bid" is not "worthless",
        and zeroing book value would move keeper surplus and inflation on a personal read
  - [x] omitting a field means "leave it"; sending it as `null` means "clear it" — read from
        `model_fields_set`, since `None` alone cannot express the difference
  - [x] `make prep` reads the same file the page writes, by default rather than by discipline
  - [x] the report prints a **YOUR OVERRIDES** section naming every changed figure with the
        model's own beside it, the §4.8 deviation, and any override matching nobody
  - [x] a stored override naming nobody is *reported, not raised* — the API refuses to create
        one, but the hand-editable file is read by `make prep` at 8am on draft day and a player
        who left the projection feed overnight must not take the report down
- **`OverrideStore` moved `api/store.py` → `store/overrides.py`.** Overrides are a pipeline
  input, not a web concern: `prep.py` reads them, and `api/` importing into `prep/` was backwards.
- **The model's whole board is retained, not per-player originals.** A points override moves
  replacement level, so it changes dollars for players the user never touched; only a second full
  run can say by how much. Hence `Pipeline.model_board` and `Pipeline.model_market`.
- **What is still not covered, stated rather than implied:** `config/auction_values.csv` remains
  the bulk path for provider auction values and is still absent, so the board-level ESTIMATE badge
  stays lit until it exists or every player is overridden by hand. Positional multipliers
  (`quant/overrides.py` implements them; §4.8 calls them the highest-leverage live knob) have no
  surface yet — carded separately.
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

---

### [DI-064] The draft-night cockpit

- **Sprint:** 3 · **Owner:** backend-engineer · **Size:** L
  · **Branch:** `di-064-live-cockpit`
- **Why:** everything in Sprints 1 and 2 was built, tested, and had no surface that runs
  *during* the auction. The poller parses picks, the ledger folds them, the valuation prices the
  board and the affordability engine ranks who can outbid you — and the only way to see any of it
  was a report printed before the draft started.
- **What it answers**, at a glance, mid-nomination: what is this player worth to me, what should
  they cost at tonight's inflation, what is my max bid, who else can still bid, and above what
  price does each of them drop out.
- **The nomination is typed by hand.** Sleeper publishes completed picks over REST and nothing
  else; the live nomination and bid clock exist only on the internal websocket that charter §2
  forbids reverse-engineering. This is Finding 11's manual layer, which the user decided to keep.
- **Acceptance criteria:**
  - [x] `GET /live`, `GET /api/live`, `GET /api/live/search`, `POST /api/live/nominate`
  - [x] reproduces the Sprint 1 golden ledger through its own polling path — $199/$200/$195/
        $200/$200/$200/$200/$200/$185/$200, 140 competitive picks, zero alerts
  - [x] **staleness is a first-class failure**: every snapshot carries its age, a failed poll
        keeps the last reading *and* says the connection broke, and a reading that merely ages
        out is marked NOT LIVE even while the connection string still reads healthy
  - [x] **blockers are separate from alerts** — an alert is something that happened; a blocker
        is something wrong now that makes the numbers beside it untrustworthy
  - [x] a player already bought says so instead of quoting a max bid for them
  - [x] the block uses the user's overridden price, and the pipeline rebuilds when
        `value_overrides.yaml` changes, so a 7:40pm retune on `/prices` reaches the cockpit
  - [x] `poll=False` by default: importing or testing the app never opens a socket to Sleeper
- **The defect this card found, and the reason it was nearly invisible.** The first working
  build showed slot 1 as AJ. The live league has slot 1 as Mason. `Pipeline.identity` is built
  from `fixtures/draft.json` — the **mock** draft — which is right for `make prep` (a report
  about the mock) and catastrophic for the cockpit. The keeper classifier keys on
  `(slot, player_id)`, so the mock's seating would have checked all twenty keepers against the
  wrong seats, matched none, and read them as competitive bids: the most expensive picks of the
  night, silently poisoning inflation, skew, tendencies and every threat read — while the page
  looked completely healthy.

  | slot | mock (`fixtures/draft.json`) | live league |
  |---|---|---|
  | 1 | AJ | Mason |
  | 2 | Jake | AJ |
  | **3** | **Matt** | **Matt** |
  | 4 | Mason | Steve |
  | 5 | Connor | Jake |

  **The user is slot 3 in both.** The one seat anybody would check by eye is the one seat that
  agrees. Fixed by resolving `slot → owner` from the live league on a 60s timer through the
  `slot_to_roster_id` → `/rosters` → `/users` join (the real draft object carries no
  `slot_name_*` keys at all — Sprint 0, Finding 9), rebuilding the classifier whenever seating
  changes, and **refusing to fall back to the mock**: before the join succeeds, `identity` is
  `None`, slots are labelled by number, and a blocker says so.
- **Verified against the live league**, not just the fixture: seating resolves to Mason/AJ/Matt/
  Steve/Jake/Keenan/Willie, slots 8–10 are numbered rather than guessed, and the blocker reads
  *"6 of 20 keepers cannot be placed (Burt, Connor, TD have not joined)"*.
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

---

### [DI-065] The 160-pick draft-night rehearsal

- **Sprint:** 4 · **Owner:** test-engineer · **Size:** M · **Branch:** `di-064-live-cockpit`
- **Why:** every other test feeds the ledger a finished array and checks the total. Nothing fed
  it a draft *as it happens*. That is the only shape in which a whole class of defect appears:
  state correct at pick 160 and wrong at pick 40, a figure that drifts rather than breaks, a poll
  that fits its budget early and not late.
- **What it does:** `make rehearsal` serves `fixtures/picks.json` one pick at a time through the
  real `LiveDraft.poll_once`, nominates the player about to be bought at each step, and checks
  **13 invariants after every one of the 160 picks** — money conservation, no negative budget,
  max bid within budget, roster capacity, keeper cap, every pick lands on somebody, feed read
  fully, freshness, no alerts, no blockers, block max bid honest. Then four chaos cases. Exits
  non-zero on any violation, so it can gate a release.
- **Result: PASSED.** 160 picks, every invariant at every pick, final ledger identical to the
  Sprint 1 golden file — reached by a second independent route.
- **Chaos, run on a live instance rather than a fresh one** (the transition is the thing that
  happens on the night, not the end state):
  - restart mid-draft → a new process at pick 100 rebuilds the identical ledger
  - pick removed → slot 9 went $170 → $165, 10 → 9 picks, refunded exactly $5
  - pick amended → $170 → $177 in one cycle, money still conserves
  - connection drops → kept $93 on screen, marked stale, named the failure
  - **not rehearsed, and named rather than skipped:** a mid-draft budget correction. Override
    events exist in the ledger; the cockpit has no surface that emits one. A cockpit gap.
- **The defect it found — a false comment and a 78x cost, in one place.** `_fold` called
  `replay_all`, justified by a comment claiming it "drives the snapshot diff, so a commissioner
  reversing or amending a pick produces the PickRemoved and PickAmended the ledger knows how to
  fold." **It does not.** `replay_events` diffs *within a single payload*, where the array only
  grows and no pick changes — verified: 160 of 160 events were `pick_observed`, zero removals,
  zero amendments, on a full feed and on one with a pick deleted.

  Corrections were handled, but by ADR-0001's actual mechanism: **there is no incremental state
  to correct.** Every poll refolds the whole log, so a reversed pick is just a shorter feed.

  Meanwhile `replay_all` re-parsed `payload[:i]` for every `i`. Proven identical output —
  same events *and* same `DerivedState` across a full feed, a removal, an amendment, an
  unsorted feed, and one carrying an unparseable row — for **101ms against 1.3ms** at 160
  picks, inside every poll cycle.

  | | before | after |
  |---|---|---|
  | poll p50 | 26.4 ms | **1.5 ms** |
  | poll p95 | 95.8 ms | **2.5 ms** |
  | poll max | 106.3 ms | **15.1 ms** |
  | growth pick 20 → 160 | 3 ms → 98 ms | 1 ms → 2 ms |

  Never near the 1,500 ms cycle budget either way — this is not a near miss that was rescued.
  It is a quadratic on the live path with a false justification attached, and both are gone.
- **Acceptance criteria:**
  - [x] 160 picks through the real poll path, invariants checked after every one
  - [x] the four chaos cases, on a running instance
  - [x] final ledger matches the Sprint 1 golden file
  - [x] latency reported per phase, against the stated cycle budget
  - [x] non-zero exit on violation, so it gates
  - [x] **the checker is proven able to fail** — 15 tests doctor a snapshot per invariant
        (`tests/test_rehearsal.py`). A gate that cannot fail is not a gate; DI-054 found three
        tests in exactly that state.
- **Also:** `tools/` is now a package, under `mypy --strict` and ruff like everything else.
  `mutation_harness.py` was never type-checked before and is now annotated.
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

---

### [DI-066] Walk-away curves on the cockpit

- **Sprint:** 3 · **Owner:** backend-engineer · **Size:** M · **Branch:** `di-064-live-cockpit`
- **Why:** the curves have existed since DI-036 and were computed by nothing on the live path.
  ADR-0006 clause 4 is the constraint that shapes the whole design: *the live walk-away lookup
  is O(1) against a board precomputed between settled picks; the precompute completes inside 30
  seconds at 8 or fewer open slots, and its cost at more open slots is stated on the page.*
- **Design:** the board is precomputed in a worker thread after any poll where the user's
  budget, open slots or the available pool changed. The block does a dictionary lookup and
  **there is deliberately no fallback that solves a missing curve**, because that fallback would
  fire exactly when the room is bidding — the 11-second stall the amended gate exists to forbid.
- **Measured cost**, full pre-draft pool, `top=12`:

  | open slots | 14 | 10 | 8 | 6 | 4 | 2 |
  |---|---|---|---|---|---|---|
  | seconds | 152 | 66 | 39 | 20 | 8.6 | 1.9 |

  On the **live** path the pool has already shrunk, so the same states are far cheaper:
  10 slots → 27.5s, and **8 slots → 16.6s. ADR-0006 clause 4 is met** (gate: inside 30s).
  At 16 open slots — the state the cockpit boots into at 6:55pm — it is ~190s, which is why the
  status line says "computing" and states the last cost rather than showing an empty chart.
- **Verified on the live league in the worst case.** Booted against the real draft with 16 open
  slots: `walkaway: computing`, the ledger answering throughout (`room $2000 over 160 slots`),
  the page rendering at 200, and **poll age holding 0.1–2.4s across a minute of CPU-bound
  precompute** — the event loop is not starved by the worker thread.
- **Every absence is explained rather than blank.** "No curve" and "not worth bidding on" are
  opposite conclusions and a missing number cannot tell them apart, so an uncovered player reads
  *"outside the precomputed top 12 by VORP — which is not the same as not worth bidding on"*, a
  curve that never turns positive says so, a non-monotone curve says its deltas are unusable,
  and a board computed for a budget the user no longer has is marked **STALE** with the pick
  count since.
- **The curve is drawn**, inline SVG, §4.7b's axes: price on x, Δ starting points on y, zero
  line, and the crossing marked — the crossing *is* the answer, so everything else on the chart
  exists to make that one x-position readable. Theme tokens, so it holds in both.
- **The defect this card introduced, and caught.** Wiring the precompute into `poll_once`
  unconditionally turned `tests/test_live.py` from 3.6 seconds into **597 seconds** — a test
  polling at zero picks was paying for a 16-slot, 190-second board. Fixed by making
  `precompute` off unless asked, exactly as `poll` already is: both are expensive, and neither
  should start because something called a method. `create_app` passes `precompute=poll`, so
  they arm together. **597s → 4.1s.**
- **Acceptance criteria:**
  - [x] O(1) lookup on the live path, no solve, no on-demand fallback
  - [x] precompute in a worker thread, off the poll path, one at a time
  - [x] priced against who is *still available* — `ValueBoard.available()` drops keepers only
  - [x] cost stated on the page, per ADR-0006 clause 4
  - [x] staleness surfaced with the pick count since, not assumed
  - [x] a failed precompute is reported and the ledger keeps answering
  - [x] no precompute for a full roster — the question no longer exists
  - [x] 11 tests, including one that holds a fake open to observe "computing", and one that
        asserts on the *candidates handed to the solver* rather than the curves that come back,
        because a `top`-limited output could hide a drafted player by ranking them low
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

---

### [DI-067] The seating-refresh test depended on the wall clock

- **Sprint:** 3 · **Owner:** test-engineer · **Size:** S · **Surfaced by:** a single failing run
  on `main` immediately after merging PR #27
- **Symptom:** `test_seating_that_changes_rebuilds_the_keeper_classifier` failed once, then
  passed 6/6 in isolation and 5/5 on the full suite. Rare, order-independent, and guarding the
  logic that stops all twenty keepers being misfiled.
- **Root cause, reproduced deterministically.** The test forced an identity refresh with
  `live._identity_at = 0.0`, and the refresh guard is
  `now - self._identity_at < IDENTITY_REFRESH_SECONDS`. **`time.monotonic()`'s epoch is
  arbitrary** — on a container it starts near zero at boot, so `0.0` reads as "over a minute
  ago" only once the process has been alive a minute. Inside that window the refresh silently
  did not happen: seating never changed, keeper keys stayed at 14 of 20, and the assertion
  failed. Pinned the clock and confirmed both directions:

  | `time.monotonic()` | keeper keys | outcome |
  |---|---|---|
  | 733 | 14 → 20 | passes |
  | 30 | 14 → 14 | **fails** |
- **Fix:** `float("-inf")` in both the test and `LiveDraft.__init__`, which is epoch-independent
  and says what it means. **Production was never affected** — the `_identity is not None` guard
  already forced the first refresh, so the `0.0` there was inert. It was load-bearing only in
  the test. Changed anyway so the same literal cannot become load-bearing later.
- **Regression test** pins `monotonic()` at 30 and runs the seating change. Verified by
  reintroducing `0.0` and watching it fail on `assert 14 != 14`; nothing else in the suite tells
  the difference.
- **A second defect fixed in passing.** The precompute test held its fake open with an
  `asyncio.Event` awaited from inside `asyncio.to_thread` — the wrong primitive twice over: the
  event belongs to a loop that thread is not running, and the fake was never released, leaking
  a non-daemon worker thread out of every run. Now a `threading.Event` released in a `finally`,
  with the task awaited so the thread is drained rather than orphaned.
- **⚠️ Honest limit on this card.** The proven defect fires only when the container is under
  60 seconds old. The observed failure was at roughly 130 seconds of container uptime, so
  **this fix does not explain the failure that surfaced it.** One real, deterministic defect
  found and closed; the original remains unreproduced across 14 full-suite runs. The suite
  stays under observation rather than being declared clean.
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

---

### [DI-068] Live seat assignment — the fix for a manager the alias table has never seen

- **Sprint:** 3 · **Owner:** backend-engineer · **Size:** M · **Branch:** `di-068-live-seats`
- **Why, and it is not hypothetical.** `keenankid17` and `willdeann` sat in the draft room,
  drafting, **for days** — and were invisible to the tool, because `config/owners.yaml` maps
  manifest owners to Sleeper *display names* and nobody had told it those two. Four keepers
  stayed unresolved the whole time while the page looked healthy.
- **It is guaranteed to repeat on the night.** Burt, Connor and TD have **no alias at all**.
  Whatever display names they pick when they join at 6:55pm, the alias table will not know
  them, six keepers will classify as competitive bids, and inflation, skew and every threat
  read inherits it. Before this card the only remedy was editing YAML and restarting the
  process, mid-auction.
- **What it does:** a seat assignment is a direct statement — *slot 9 is Burt* — applied after
  `build_identity` and winning over it, because a person looking at the draft room knows who is
  in seat 9 and the API demonstrably may not. Persisted to `config/seats.yaml`, hand-editable,
  every read to disk.
- **Verified against the exact Saturday scenario** (three managers under names `owners.yaml` has
  never seen):

  ```
  BEFORE  keepers 14/20   unplaced: Burt, Connor, TD   slot 9 shows: bigburt2011
  AFTER   keepers 20/20   blockers: NONE               slot 9 shows: Burt
          competitive picks 140 — the keepers classify correctly again
  ```
- **A seat lands on the next poll, not up to 60 seconds later.** Identity refreshes on a timer,
  which is right for managers drifting in over a week and wrong for a seat typed while staring
  at the blocker naming that manager. The seats file's mtime bypasses the timer, the same trick
  the priced board uses for `value_overrides.yaml`.
- **Two counts are reported, and neither substitutes for the other.** `keepers_resolved` is
  what the ledger is classifying against *right now*; `keepers_if_seated` is what the seats on
  disk would give once the next poll picks them up. Report only the first and a correct
  assignment looks like it failed — the count cannot move until the classifier is rebuilt.
  Report only the second and the blocker clears a poll before the classifier agrees, which is
  the optimistic direction and the one that lies.
- **The defect the tests caught.** The first `apply_seats` asserted an owner into a new seat
  without vacating the old one, so `slot_to_owner` had Connor in **two** slots while
  `owner_to_slot` had one — precisely the disagreement the docstring said must not happen. The
  keeper classifier reads one map and the threat ladder the other, so they would have described
  different drafts: two rows on the ladder under one manager's name. A vacated seat now becomes
  *unknown* rather than inheriting anybody, because if the assertion is right then whatever the
  API said about that seat was wrong and there is no second source.
- **Acceptance criteria:**
  - [x] `GET/POST/DELETE /api/live/seats`, and a panel on `/live` directly under the blocker
  - [x] a seat naming nobody in the manifest is refused (404), a slot outside 1..teams is 422
  - [x] assignments survive a restart
  - [x] an owner can only occupy one seat; the vacated one reads as unknown
  - [x] `apply_seats` with no seats is the identity function, not a rebuild that happens to agree
  - [x] 9 tests, driven by the real fixture under display names the alias table does not know
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

---

### [DI-069] The budget correction surface

- **Sprint:** 3 · **Owner:** backend-engineer · **Size:** M · **Branch:** `di-069-corrections`
- **Why:** the ledger has taken `BudgetAdjustment`, `ManualKeeper` and `Revert` since Sprint 1
  and **nothing on the live path emitted any of them.** When the tool says AJ has $47 and the
  room says $42, there was no way to say so. Charter §2 makes manual entry the *primary* price
  path rather than a fallback, because Sleeper publishes no auction value at all (Finding 3).
- **A correction is a delta, never a pin** (§4.8), and the distinction is the whole card. Pin
  slot 1 to $81 and the moment they buy somebody for $79 the pin drags them back to $81 while
  the room sees $2. Measured on the fixture: correction applied at pick 60, twenty more picks
  land, slot 1 spends $79 — reads **$2**, exactly right. A pin would read $81.

  The *interface* still asks for the absolute, because "AJ has $42" is what a person says at a
  table. The delta is computed once, at that moment, and never recomputed.
- **Sequence numbers are stable across folds.** Feed picks are numbered 1..N and N grows with
  every pick, so a correction numbered after them would change identity every poll and a
  `Revert` aimed at one would silently drift onto whatever event now holds that number.
  Corrections are numbered from `CORRECTION_SEQ_BASE = 1_000_000`, from an id assigned once and
  never reused — which also puts them after every pick in fold order, which is right: a
  correction is the user's last word on a team.
- **What the user said is kept beside what the system derived.** §4.8 applied to the money
  column: `observed: 81` sits next to `delta: -5`, so "I told it AJ had $81" stays recoverable
  an hour later from "-$5". A stored delta alone cannot answer that.
- **A revert emits a real `Revert` rather than deleting the row**, so *"corrected then undone"*
  stays legible at 9pm when somebody asks why a number moved twice. Verified: money restored,
  record retained reading `slot 1: -5, you said $81 (reverted)`.
- **The ledger's own guards still fire through this path**, which matters because it is a new
  route into the same ledger and must not be a way around them. A -$400 fat finger produces
  `IMPLAUSIBLE CORRECTION slot 3: -400 takes this team's budget to $-200 in a $200 league;
  applied as entered, but check it` — applied as entered rather than silently clamped, because
  a bounded-but-wrong figure is more dangerous than an absurd one.
- **A corrected budget must never look like an uncorrected one.** The panel is always present
  once anything is in force, listing what you said alongside what was derived from it. The
  moment a $5 adjustment stops being visible it is indistinguishable from a bug.
- **Acceptance criteria:**
  - [x] `GET/POST/DELETE /api/live/corrections`, budget and keeper, and a panel on `/live`
  - [x] absolute in, delta stored; both or neither is 422, a no-op correction is 422, a slot
        outside the league is 422, a keeper naming nobody is 404
  - [x] survives a restart
  - [x] correction seqs do not drift as the feed grows — asserted directly, not inferred
  - [x] 9 tests including the baseline that no corrections changes nothing, without which the
        rest prove only that *something* moved
- **Not built, and stated rather than implied:** the keeper form is API-only on the page; the
  budget form is the one with a UI. `Reclassify` still has no producer (DI-057).
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

---

### [DI-070] The keeper form — and the defect that adding it exposed

- **Sprint:** 3 · **Owner:** frontend-engineer · **Size:** S · **Branch:** `di-070-keeper-form`
- **The ask:** put the manual-keeper path on the page. DI-069 shipped it API-only.
- **What building it found, before writing a line of it.** `repaint()` replaces `#app`'s
  innerHTML **every two seconds**, and both the seats form (DI-068) and the budget form
  (DI-069) were inside it. **Anything you typed into them was wiped on a two-second timer** —
  mid-auction, while the room waits. Shipped twice, in two cards, and neither card's tests
  caught it, because they assert on rendered markup and never on interaction.
- **Fix:** every form moves below `#app` into the stable shell; `#app` keeps only what *should*
  refresh — blockers, the corrections-in-force list, seat assignments, the block, the ledger.
  The dropdowns are populated from `/api/live` and `/api/live/seats` rather than rendered
  server-side, so they sit outside the repaint and still follow the draft: a manager who joins
  changes both the team list and the unplaced list.
- **The keeper form itself:** pick a team, search a player (same endpoint the nomination box
  uses), type what they were kept for. The button starts **disabled** and only enables once a
  player is picked from the search — an enabled button with nothing selected posts a keeper for
  nobody. A refusal from the API is flashed on the button rather than swallowed.
- **Tests pin the boundary, which is the actual property.** A form in `#app` is unusable however
  it behaves in isolation, so the assertions are on *where the markup is*: every control must be
  absent from the repainted region and present in the shell, and the corrections list must be
  the other way round. Plus a test that the two string literals `repaint()` slices on still
  split the page — move either and the cockpit silently stops updating while the connection
  line keeps saying `live`.
- **A second defect, self-inflicted while writing the tests for the first.** The new test helper
  built a `LiveDraft` against the repo root without passing scratch stores for seats and
  corrections, so a POST wrote a **-$36 budget correction into the project's own
  `config/corrections.yaml`**. Six later tests and `make rehearsal` then folded it and failed —
  none of them near the culprit, and the rehearsal reporting *"first failure at pick 1 of 160"*
  for a reason with nothing to do with pick 1.

  The individual fix is to pass the stores. The general fix is `tests/conftest.py`: an autouse
  guard that fingerprints `config/` before and after **every** test and fails the one that
  dirtied it, naming the file and the remedy. Every writable store takes an injectable path
  precisely so tests can point it somewhere harmless; this turns that from a convention into a
  rule. Verified by reintroducing the bug — the guard fires on the offending test rather than on
  six innocent ones.
- **Acceptance criteria:**
  - [x] keeper form on the page: team, player search, price, disabled until a player is picked
  - [x] every form outside the repainted region; every live list inside it
  - [x] the repaint split literals are asserted, not assumed
  - [x] pickers refresh from the live snapshot without a page reload
  - [x] no test can modify the real `config/` — enforced, not documented
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

---

### [DI-071] The rehearsal against the live league

- **Sprint:** 4 · **Owner:** test-engineer · **Size:** M · **Branch:** `di-071-live-rehearsal`
- **The ask:** run the 160-pick rehearsal against the league that is actually going to draft,
  not the mock it was built on.
- **Why it is not the same run.** The mock and the live league seat people differently — mock
  slot 1 is AJ, live slot 1 is Mason. Replaying raw `draft_slot` numbers against live identity
  would test a draft nobody is going to play. What has to carry over is *who paid*, so
  `--live` re-attributes each pick from the seat its owner held in the mock to the seat they
  hold now, and the final ledger is compared to the golden file **by owner** rather than by
  slot. Identity comes from Sleeper's own `/rosters` and `/users` through the real
  `config/owners.yaml` — the production path, start to finish, with nothing stubbed below the
  client.
- **What it found, which is the point of running it.** As the league is configured right now
  the run **FAILS**: 6 of 20 keepers cannot be placed on a draft slot, and 146 picks classify
  competitive instead of 140. Not a code defect — Burt, Connor and TD have no confirmed seat,
  so their keepers have nowhere to land and become bids. With those three seats assigned
  (`--seats=`, a scratch file, nothing written to `config/`) the same 160 picks **PASS**: every
  invariant at every pick, the ledger matching the golden file by owner for all ten managers,
  poll p50 1.5ms against a 1500ms budget. **The tool is ready; the league is not.**
- **Three harness defects, all found by the tool refusing to agree with the harness:**
  - matched the mock's *display* names against live identity, so the user themselves came out
    as "has not joined" — the mock seats them as `Matt` and the manifest calls them `Me`. They
    landed in a leftover seat that happened to be correct, by luck. Now keyed on manifest owner
    names on both sides.
  - rewrote `draft_slot` without `metadata.slot`, and the poller's cross-check (DI-053) reported
    **224 PAYLOAD CONFLICTs**. The tool was right: that is a payload Sleeper would never emit.
  - `--seats` reached the re-attribution but not the cockpit's own `SeatStore`, so the rehearsal
    measured one seating while the ledger classified against another — the mock-vs-live confusion
    DI-064 exists to prevent, reintroduced inside the harness meant to catch it.
- **The chaos list is now complete.** Case 5, a mid-draft budget correction, had been printed as
  *"not rehearsed — a cockpit gap, not a ledger gap"* since DI-065. DI-069 shipped the surface,
  so it is rehearsed: the corrected team moves by exactly the delta, **the other nine do not
  move**, and the revert restores it to the dollar. Money conservation is deliberately not
  asserted there — a budget correction means the room no longer totals 10 × $200, and
  reconciling to `2000 + Σ deltas` is the Sprint 1 property instead. Case 6 covers the same
  surface used wrong: a correction that overdraws a team is taken **as typed** (refusing it
  means arguing with the person who can see the room), the max bid clamps to $0, and the
  cockpit says so out loud rather than computing off money that does not exist.
- **Still open, and none of it is code:** `ConnorRice102` has joined at slot 8 and is unmapped —
  `config/owners.yaml`'s own rule is that mappings are confirmed by a human, never inferred from
  a resemblance, so it stays unmapped until the user confirms it. Two seats remain empty.
  `draft.settings` still reports `rounds: 15` against `roster_positions`' 16 (the known ADR-0002
  D4 mismatch) and carries no `max_keepers`.
- **Acceptance criteria:**
  - [x] `make rehearsal-live` drives the real `LiveDraft` over live identity, `--seats=` for a
        seating not yet in `config/`
  - [x] picks re-attributed by owner; golden file compared by owner; assumed seats printed, not buried
  - [x] re-attribution unit-tested away from the network, and mutation-verified — dropping the
        `metadata.slot` rewrite or the leftover-seat fill fails a named test
  - [x] the chaos list has no unrehearsed entries left
  - [x] the rehearsal reads no user-editable file it does not have to; `config/` verified clean after
  - [x] `make ci` green — 660 tests, 95% coverage
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

---

### [DI-072] Connor mapped to `ConnorRice102`

- **Sprint:** 4 · **Owner:** data-engineer · **Size:** XS · **Branch:** `di-072-connor-seat`
- **The ask:** the user confirmed that the account which joined at slot 8 is Connor. Map it.
- **Why a card for one line.** Because it is the line that decides whether two keepers are
  keepers. `config/owners.yaml`'s standing rule — every mapping confirmed by a human, never
  inferred from a resemblance — exists because a wrong one files that manager's keepers as
  competitive bids, which poisons market inflation, skew and every tendency profile for the
  whole draft, and simultaneously moves another seat's positional demand and surplus. The
  resemblance here was obvious from the moment the account appeared and was deliberately not
  acted on until asked. An obvious resemblance is exactly the kind that turns out to be
  somebody else.
- **Measured effect,** `make rehearsal-live` before and after: unplaceable keepers **6 → 4**,
  competitive picks **146 → 144**. Slot 8 now resolves to Connor rather than being backfilled by
  the leftover-seat assumption. The run still fails, correctly — Burt and TD have not joined,
  and their four keepers still have nowhere to land.
- **Acceptance criteria:**
  - [x] mapping recorded with who confirmed it and when, per the file's own rule
  - [x] the header's count of joined managers updated with it (seven → eight)
  - [x] `make ci` green — 660 tests
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

---

### [DI-073] The reclassification surface — the last event type with no producer

- **Sprint:** 3 · **Owner:** backend-engineer · **Size:** M · **Branch:** `di-073-reclassify`
- **The ask:** close the last hole. `Reclassify` has been consumed by the ledger since Sprint 1
  and produced by **nothing**. Budget corrections, manual keepers and reverts all got surfaces
  in DI-069/DI-070; this was the one left, and it is the one that matters most.
- **Why it matters most.** A pick's class decides whether its dollars enter the auction
  analytics *at all*. A ceremonial keeper counted as a bid is a phantom data point in
  `competitive_seq`, market inflation, skew, run detection and every tendency profile; a real
  bid counted as a keeper removes a true one from all of them. DI-071 measured exactly this
  against the live league — six unseated keepers moved the competitive count from 140 to 146 —
  and until now the only remedy was to edit YAML and restart the tool mid-draft.
- **What shipped:**
  - `Correction` gains `kind: reclassify`, carrying `pick_no` and `pick_class`. **No slot**, and
    deliberately: seating is late-bound (D1), so a slot copied into the row at 9pm is a second,
    staler answer to a question the pick itself already answers — the same reasoning that made
    keeper supersession key on `player_id` rather than `(slot, player_id)`.
  - A model validator: each kind must carry its own key fields. There are three call sites and
    one of them is a person editing YAML at a table, so "a row that folds to nothing" is caught
    at load rather than discovered by its absence.
  - `GET /api/live/picks` — settled picks newest first, each with **the class it currently
    carries, as folded**, corrections included. Without the current class you cannot see whether
    you are about to change anything; without "as folded" you would correct the same pick twice.
  - `POST /api/live/corrections/reclassify`, and the form in the stable shell (never inside
    `#app`, per DI-070). Empty box offers the last eight picks, because the pick worth arguing
    with is nearly always the one that just landed.
  - Rehearsal chaos case 7: a reclassification mid-draft moves `competitive_picks` by one, the
    undo puts it back, **and the money never moves**. That last clause is the whole reason this
    is easy to ship broken — every conservation check passes while the analytics quietly read a
    ceremonial keeper as a $24 bid.
- **Three refusals, each for a reason:** a pick the ledger does not hold (404); a correction
  that changes nothing (422 — it would sit in the audit trail explaining nothing); and
  `FLAGGED` (422). The last is the interesting one: FLAGGED is the classifier saying *"I don't
  know, a person should look"*, so a person looking and choosing "I don't know" settles nothing
  and leaves the pick out of a competitive series it may well belong in.
- **Manual keepers are deliberately not reclassifiable.** They have no `pick_no` — they exist
  because the feed never delivered them — so there is nothing for a `Reclassify` to key on. The
  way to undo one is to revert it, which the corrections list already offers.
- **`model_dump(mode="json")` on write.** `PickClass` is a `StrEnum` and PyYAML's
  SafeRepresenter dispatches on exact type rather than the MRO, so a str subclass is "undefined"
  to it and raises instead of writing `KEEPER`. Plain scalars round-trip identically, so nothing
  already on disk changes.
- **Acceptance criteria:**
  - [x] a product path constructs `Reclassify` — DI-057's first criterion, closed
  - [x] the correction reaches the *analytics*, not merely the store: asserted on
        `competitive_picks`, and mutation-verified by making `events()` drop the event
  - [x] reverting restores the class exactly, via a real `Revert`
  - [x] the form is outside the repainted region; the resulting correction is inside it
  - [x] three refusals, each mutation-verified
  - [x] `make ci` green — 669 tests, 95% coverage; rehearsal PASSED with seven chaos cases
- **Still open on DI-057:** arming the classifier, its pre-draft toggle, and keying the window
  on manifest incompleteness rather than `pick_no <= 20`. Those were blocked on this card — a
  backstop whose FLAGGED verdict could not be answered was a one-way trap — and are no longer.
- **Reviewer verdict:** pending. · **Evaluator verdict:** pending.

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

**Sprint 2 gate** — amended by **ADR-0006**, accepted 2026-09-02. Three clauses restated or cut,
two standing exactly as written. The original text is quoted in the ADR; this is what the sprint
is now held to.

1. **`make prep` produces the priced board** against the real keeper manifest, the real
   projections and the real scoring settings. Running it against the *live league* additionally
   requires DI-043 — three managers have not joined — which is outside this sprint's control and is
   named as a dependency rather than held as a gate.
2. **Money-conservation invariants hold.** *(Unamended.)*
3. **A human has reviewed the board.** *(Unamended, and deliberately not softened.)* §4.9's premise
   is that a model first seen three minutes before the auction cannot be sanity-checked. Two review
   rounds and two adversarial evaluations found real defects here, including prices sourced from
   another draft entirely — none of which substitutes for the person who knows this league reading
   it and disagreeing. Under the amendment this is now the **only** whole-model review, so its
   stakes went up, not down.

   **✅ MET 2026-09-03.** The user read the board and disagreed with it: the top QB priced at
   **$17.74, 25th overall, in a league that starts twenty of them.** That is the clause working
   exactly as §4.9 intended — a person who knows this league finding something six audit rounds
   did not, because it is not a defect in the code. It produced DI-061 and then DI-062, and DI-062
   in turn found that three of the four override fields were inert. **The disagreement was worth
   more than the review rounds that preceded it.**
4. **The live walk-away lookup is O(1)** against a board precomputed between settled picks; the
   precompute completes inside 30 seconds at 8 or fewer open slots, and its cost at more open slots
   is stated on the page rather than hidden. *(Replaces "walk-away recompute p99 < 200ms", which
   measured the wrong thing: a curve is dozens of solves by construction, and ADR-0003 already
   promises a lookup rather than a solve on the live path.)*
5. ~~500-run Monte Carlo and the p<0.01 bot gate.~~ **Cut to Sprint 5**, on the terms this gate
   itself set — "cut item #1 if the schedule slips". **The cost is real and is recorded rather than
   buried:** this was the only planned check on the valuation *as a whole*. Every remaining test
   checks a component; nothing now asks whether the model actually wins drafts, which is the only
   question that catches a model that is internally consistent and collectively wrong.

## Backlog — Sprints 3–5

Epic level only until Sprint 2 closes.

- **Sprint 3 — Cockpit:** FastAPI + WebSocket · React cockpit per §5 · nomination entry +
  reconciliation · override UI and inspector · three-way visual badging · keeper arming switch
  with `N/20` readout · λ slider · keyboard map · charts
- **Sprint 4 — Hardening:** chaos suite · offline mode · snapshot/restore · `RUNBOOK.md` ·
  `DRAFT_DAY_CHEATSHEET.md` · 60-minute rehearsal run as both Case A and Case B
- **Sprint 5 — Stretch:** nomination advisor · post-draft report · opponent bid modelling ·
  **mock auction simulator (10 bots, 5 strategies), the 500-run Monte Carlo, and the p<0.01 bot
  gate** — cut from the Sprint 2 gate by ADR-0006. Nothing in the tree simulates a draft today.
