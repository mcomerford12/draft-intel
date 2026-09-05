# Handoff — Draft Intelligence Platform

> ## ⚠ Sections 1, 9, 11 and 12 are out of date and were written 2026-09-01
>
> **Corrected 2026-09-05.** Four days of work happened after this document was written, and
> its status sections describe a project that no longer exists. Read the correction below
> before anything else in this file.
>
> **What is still true and still worth reading:** §2 (hard facts), §3 (what is trustworthy),
> §5 (the fix-pass pattern), §7 (discovery findings), §8 (architecture invariants), §10
> (process rules — including the honest caveat about agent independence, which has not stopped
> being true). §4's defects are closed; §6's blockers have shrunk but not vanished.
>
> **Where to look instead:**
>
> | For | Read |
> |---|---|
> | What to do on draft night | `docs/RUNBOOK.md` |
> | What was built and why | `docs/KANBAN.md`, cards DI-001 → DI-074 |
> | Whether it works right now | `make ci`, then `make rehearsal-live` |

---

## 0. Correction — the state on 2026-09-05

The recommendation in §1 and §12 below was followed, and then overtaken.

**Sprint 1's open defects are closed.** Sprints 2, 3 and 4 were built after this document was
written: the priced board, the valuation stack, the live cockpit, its rehearsal, and the four
correction surfaces. `make ci` is green at **678 tests, 95% coverage**. `make rehearsal` drives
160 real picks through the real cockpit one poll at a time and passes every invariant at every
pick, plus seven chaos cases.

**The tool connects to the live draft.** §1's claim that it "cannot connect to the real draft
at all" was true when written — six of ten managers had not joined. Eight have now joined and
the cockpit polls the real league successfully.

**What remains open is not code.** Two managers (Burt, TD) have still not joined, so four
keepers cannot be placed on a slot. `make rehearsal-live` fails on exactly that and says so.
The keeper backstop (`make arm ON=1`) mitigates it by turning those four silent
misclassifications into four questions.

**What §12 got right, and it is worth recording:** point 4 said the printable board was the
deliverable that mattered most, and point 5 said to prioritise the offline board over live
ingestion while the league was unreachable. Both held up. The board was built first, and the
live path was built afterwards against a league that had by then become reachable.

**What §12 got wrong:** point 3 recommended a single review pass per card. In practice the
review rounds kept finding real defects — including tests that could not fail, a classifier
reading the wrong draft's seating, and a false claim in a code comment — so the two-pass rule
was worth its cost. Roughly sixteen of the later cards still carry pending verdicts; that debt
is real and is recorded honestly on each card rather than quietly closed.

---

## 1. Status in one paragraph *(SUPERSEDED — see §0)*

The data spine (Sprint 1) works and is **rejected**. Three independent review rounds and
three adversarial evaluation rounds have all returned REJECT. The replay ledger is exact, the
golden file has been independently re-derived three times, crash recovery survives a real
`SIGKILL`, and CI is deterministic at 118 tests. But each fix pass has
closed the named defects and introduced a new silent-money defect, three rounds running, and
several remain open. The three money-safety items are now closed or partial (§4.1); the
duplicate-`pick_no` case still loses money. **Sprint 2, the priced board, has never been started.** The draft is
in four days. The previous session was told to stop and write this document rather than
attempt a fourth fix pass.

### The recommendation you are inheriting

The open defects are, without exception, in **live-ingestion robustness** — negative amounts,
duplicate pick numbers, revert-chain edge cases, mutation guards. **None of them affect
`make prep`,** which needs projections, replacement levels and valuation math, and which runs
off the keeper manifest and a static fixture, both of which are verified sound.

Separately, **the tool cannot connect to the real draft at all right now** (DI-043: six of ten
managers have not joined the league). Perfecting live ingestion for a draft it cannot reach is
the wrong use of the remaining days.

If you are picking this up with the deadline still live, the highest-value path is: finish the
one remaining money-safety item in §4.1, then **stop reviewing Sprint 1 and build the priced
board.** A printed tier sheet with walk-away prices is worth more on draft night
than a perfect ledger with nothing to price.

---

## 2. Hard facts — do not re-derive

| Fact | Value |
|---|---|
| Sleeper username | `mattchupiccu` → `user_id` `1264817262276128768` |
| League | `1391959336820953088` — "GJFL 2026 Auction Draft" |
| Real draft | `1391959337445920768` (status `pre_draft`, 0 picks) |
| **User's `roster_id`** | **3** |
| Mock draft (the only replay fixture) | `1400259554721165312` — complete, 160 picks |
| **Draft time** | **Sat 2026-09-05, 21:00 ET** (Sleeper `start_time` = 2026-09-06 01:00 UTC). The user has said 9/4; Sleeper is the authority. |
| Prior season | None. `previous_league_id` is null — **nothing to backtest against.** |

Keeper slate, re-derived independently and confirmed: **7 QB / 6 RB / 7 WR / 0 TE / 0 K**.
Remaining base starting demand QB 13 / RB 14 / WR 13 / TE 10 / K 10 = 60, plus 20 FLEX =
**80 remaining starting slots** against **140 remaining roster spots**. Different numbers,
easy to transpose, assert both.

**AJ, Mason and Burt hold no QB and each need two.** The user holds Josh Allen and needs one.
That asymmetry is the most exploitable fact in the draft and the thing the priced board most
needs to surface.

---

## 3. What is genuinely trustworthy

Everything here was confirmed by an agent running the artifact, not by reading it, and most
of it independently more than once.

- **The replay ledger is exact.** `make replay` reproduces every team's final budget to the
  dollar: slots 1–10 at `(16,199) (16,200) (16,195) (16,200) (16,200) (16,200) (16,200)
  (16,200) (16,185) (16,200)`, total spent **$1,979**, remaining **$21**, keeper spend
  **$549**, 140 competitive picks, 20/20 keepers, 10/10 teams complete, zero alerts.
- **The golden file is not circular.** Re-derived three separate times by scripts importing
  no project code. Exact match every time.
- **Crash recovery is real.** Tested with an actual `SIGKILL` at pick 77 (exit 137): 80 events
  survived, all seven event kinds round-trip byte-exact, resume folds to correct state.
- **CI is deterministic.** 12/12 and 8/8 cold runs green after the parse fix; 118 tests as of `0da8214`. It was
  previously failing roughly 1 run in 3, which invalidated earlier "CI green" claims.
- **The Case A / Case B gate is no longer vacuous.** Verified by deleting each classifier
  branch in turn; both now fail the gate. Contamination audit: dropping one manifest key moves
  competitive QB spend 157 → 186 (+18%) while `total_spent` stays 1979.
- **Retention price**: zero divergences from `max(1, floor(Fraction(3,4)·v))` over 1..20,000.
- **No keeper branch in the money ledger**, no `roster_id` keying, no runtime name matching,
  no websocket/GraphQL, no hard dependency on the undocumented endpoint.
- **The identity fallback works against the live API.** `make smoke` resolves 4/10 slots via
  `rosters` → `users` and prints both blockers.

---

## 4. What is broken — open defects with reproductions

### 4.1 Money safety — D1 and D3 CLOSED, D2 partial (commit `0da8214`)

**D1. Negative amounts — CLOSED.** `parse_amount` now applies the sign check once, at a single
exit, to whatever its reading arms return, so a fifth arm cannot be added around it. And `fold`
alerts on any negative roster entry, which is the one point every ingestion path crosses —
`ManualKeeper` included, which never touched the parser at all.

```
parse_amount("-500.0")                        -> (-500, 'amount is negative (-500)')
fold([ManualKeeper(..., amount=-500)], ...)   -> spent -500  max_bid 686  alerts 1
```

Note the deliberate design choice: the absurd figure is still *recorded as observed* rather
than clamped or dropped. What changed is that it is no longer silent. If you prefer refusal to
observation, add `ge=0` to `PickSnapshot.amount` and `ManualKeeper.amount` — but decide it
consciously, because recording-and-alerting is defensible for a ledger whose job is to reflect
what the feed said.

**D2. Duplicate `pick_no` — PARTIALLY closed. Money is still lost.**

```
two rows claiming pick_no 30 -> total_spent 1947 (should be 1979)
rejects 1   alerts 0   conservation still "holds"
```

The row is now surfaced through the rejects channel, so it is no longer invisible. **But $32 is
still gone and no alert fires.** The snapshot map is keyed on `pick_no`, so the second row
overwrites the first. If you fix one thing in this section, fix this: a reject line in a scroll
is much weaker than an alert, and the ledger still reports a wrong total as if it were right.

**D3. `FrozenDict.__ior__` — CLOSED.** `state.teams |= {...}` no longer mutates.

The wider concern from the third review stands and is **not** addressed: `FrozenDict` is
`dict[Any, Any]`, so replacing `Mapping[int, TeamState]` lost the static typing that made item
assignment a `mypy --strict` error project-wide, and `copy`/`deepcopy`/`pickle`/`model_validate`
round-trips raise. Not reachable from today's entry points; trivially reachable from a Sprint 3
cockpit process boundary. Consider restoring the `Mapping` annotation and closing the mutation
gap another way.

### 4.2 Correctness, lower severity

| # | Defect | Detail |
|---|---|---|
| D4 | `rejects` lost across an `EventStore` round-trip | It is a `fold` parameter, not a derivation. `orphans` survives; `rejects` does not, so criterion 2's "identical state" fails on that field. Only `cli.replay` supplies it. |
| D5 | `Revert(target_seq=0)` can cancel an unstamped revert | The `active` map is computed before the `UNSTAMPED` guard, so a revert the code *says* it ignored is the one that changed the answer. Two unstamped reverts also collide on key `0`. |
| D6 | Revert chain assumes canceller seq > target seq | Never enforced, never alerted. A revert targeting a higher seq silently neutralises a later override. |
| D7 | `manifest_keys(teams=)` not wired into the replay path | The collapse guard exists and is reachable only from `cli._smoke`; `cli._classifier` passes `require=` only. Uncovered by tests. |
| D8 | Ambiguous display-name drop discards an authoritative mapping | Applied per-name and unconditionally, overriding the per-slot "draft metadata wins" rule. Can leave `is_complete` true with zero resolvable owners. |
| D9 | `KeeperClassifier.armed` reachable from no production path | The Case B arming switch the charter requires. Asked for three rounds. Either wire it or move it to Sprint 3 on the board. |
| D10 | `Reclassify` keys on `pick_no` | Unsafe if Sleeper renumbers after a reversal. The diff handles renumbering; the event does not. |
| D11 | `_gate` binds to the first contended event loop | Harmless today (`cli` builds a client inside `asyncio.run`); will bite the Sprint 3 cockpit, which holds a client across the app lifetime. |
| D12 | No dependency ADR | httpx, pydantic, sqlalchemy, pyyaml. Charter requires one. SQLAlchemy is heavyweight for one four-column append-only table. |

### 4.3 Tests that are still unsound

- **The Case A/B companion test has a dead arm.** `test_replay_gate.py:145` and `:150` are the
  identical expression, and the comment above `:145` describes a fix that was not made. A
  previous commit message claims this was repaired; **it was not.** Verify before trusting.
- `test_no_team_exceeds_two_keepers_without_an_alert` matches `f"slot {slot} holds"`, which
  also matches the over-roster alert. Should match `"keepers, limit is"`.
- `test_manual_keeper_counted_exactly_once` still passes one drawn slot to both the pick and
  the manual entry, so the mismatch case is unexercised. Asked for three rounds.
- `test_ledger_reconciles_exactly_with_overrides` draws `st.integers(1, 10)` only, so the new
  orphan semantics rest on a single hand-written example.
- `identity.py:106`, `:169` and `ledger.py:303` are uncovered; mutating two identity behaviours
  away leaves the suite green.
- **`cli.py` is excluded from coverage** (`pyproject.toml`), and every newly wired fix lives
  there. The 96% headline does not measure the connections.

---

## 5. The pattern — read this before starting a fix pass

Three rounds, same shape, in both reviewers' words: **each pass closes the named defects and
introduces one new silent-money defect plus one test that certifies a partial fix as
complete.**

Concretely, across the rounds the author: shipped two headline property tests that were
tautologies (`remaining` is *defined* as `budget − spent`); shipped a Case A/B gate that
passed with the classifier replaced by a constant; fixed "amounts parse to $0 silently" by
introducing "parser raises and takes the poll cycle down"; wrote a revert-chain test that
stopped at depth 2, exactly where the bug is invisible; wrote a test asserting a phantom team
as its expected value; and claimed in a commit message to have fixed a dead test arm that is
still dead.

**Practical implications for you:**

1. **Write the test against the old code first.** Every regression here was validated by
   checking out the prior commit and confirming it fails. Do the same, and force
   `PYTHONPATH` to the old `src` — the editable install silently resolves to the new source
   and a naive worktree run passes spuriously.
2. **Ask what the assertion would look like if the code were wrong.** If you cannot construct
   that, the test is probably an identity.
3. **Wire the fix, then prove the wire.** Three separate fixes shipped connected to nothing.
   A test that captures `cli.replay()` stdout and asserts the expected line is three lines.
4. **Assume the newest code is the least reviewed and the most likely to be wrong.**

---

## 6. Blocked on the user — no code can fix these

**DI-043 — six managers have not joined the league.** Jake, Connor, Keenan, Willie, Burt, TD.
Their Sleeper display names are unknowable until they join, so `config/owners.yaml` cannot be
completed and only 8 of 20 keeper keys resolve. **The tool cannot run against the real draft
until they join.** `make smoke` reports this as a blocker rather than proceeding quietly.
Known names: `mattchupiccu` (slot 3), `ajthebeard`, `MasonWAlpert`, `steeveegee300`.

**DI-004 — the league's settings contradict themselves.** `league.roster_positions` says 2 QB
/ 0 DEF / 6 BN / 16 slots; `draft.settings` says 1 QB / 1 DEF / 5 BN / 15 rounds; and
`max_keepers` is 1, not 2. The commissioner must re-save. The tool boots on `roster_positions`
(ADR-0002, corroborated by `draft.metadata.scoring_type == "2qb"` and by the mock draft) and
warns, so development is unblocked — but the league is not correct.

---

## 7. Discovery findings that shaped the design

Full detail in `docs/api-findings.md`. The load-bearing ones:

1. **No auction-value field exists for 2026.** All twelve ADP variants present with full
   coverage across 3,271 records; `auction`, `auction_value`, `dollar`, `price` absent
   entirely. **The league's keeper rule references a number Sleeper does not publish.**
   Retention prices must be *read* from the draft room. `floor(0.75 × …)` is a reconciliation
   check, not a source. `adp_2qb` is the right fallback curve.
2. **Mock picks carry `roster_id: null` and `picked_by: ""`.** Identity keys on `draft_slot`.
3. **The 20 ceremonial keeper picks carry `is_keeper: false`.** The manifest is the only
   classifier that fires on real data.
4. **The real draft object has no `slot_name_*` keys.** Only the mock does. Production owner
   identity comes from joining `slot_to_roster_id` through `/rosters` and `/users`.
5. Name collisions: **Josh Allen** (guard `2212` vs QB `4984`) and **Lamar Jackson** (CB
   `6994` vs QB `4881`). The charter warned about the first only. `players_slim.json`
   deliberately retains off-position collisions — an earlier trim deleted them and would have
   let broken resolution look correct.
6. Full PPR (`rec: 1.0`), **no TE premium**, raw stat components present for §4.1 scoring.
7. Real draft timers 30s nomination / 60s pick.

---

## 8. Architecture invariants — do not break

**One equation.** `derived_state = f(api_events + override_events)`. Append-only log, full
refold on every change. Refolding 160 picks costs microseconds, and paying it makes pick
reversal, restart recovery, retroactive reclassification and override commutativity correct by
construction. ADR-0001.

**Money is uniform.** Every team starts at $200, decremented by every pick, keeper or
competitive. There is deliberately **no keeper branch** in `domain/ledger.py`.

**`draft_slot` is the canonical team key.** Never `roster_id`.

**`competitive_seq`** is a dense index over `COMPETITIVE` picks, recomputed every fold,
deliberately *not* stable across folds. All time-series analytics key on it; **never persist
or cache a value.**

**Two inflations, never merged:** `keeper_inflation` (structural, `live ÷ full_market`, fixed,
>1) and `market_inflation` (live, exactly 1.00 at pick 0).

**Four replacement baselines**, mapped in ADR-0001 because charter §4.2 and §4.3 never paired
them. Pricing uses the **last-drafted** baselines.

**The optimizer is a DP, not an ILP** (ADR-0003). The charter demands PuLP *and* a 200ms
walk-away budget; CBC's subprocess overhead makes those mutually exclusive at 40–80 solves per
curve. CBC is retained as an offline test oracle. Walk-away prices are precomputed per player.

**ILP objective includes a bench term** (ADR-0004): `starting points + λ × Σ bench VORP`,
λ default 0.2, live slider. λ=0 recovers the charter's literal objective.

```
src/draft_intel/
  config.py     LeagueConfig + graded boot tripwire      models.py   types, events, FrozenDict
  sleeper/      client (rate floor, breaker), poller (snapshot diffing, ParseResult)
  domain/       identity, keepers, classify, ledger      store/      append-only SQLite
  replay/       harness, Case A synthesis                cli.py      replay + smoke
```

---

## 9. Repo state *(SUPERSEDED — see §0; `main` now carries every card through DI-074)*

| Branch | PR | Contents |
|---|---|---|
| `main` | — | Charter + refined plan. Documentation only; no unreviewed code. |
| `sprint-0-discovery` | #1 | Discovery, 9 findings, fixtures |
| `sprint-1-data-spine` | #2 | Ingestion, ledger, replay, persistence |
| `di-000-process-scaffold` | #3 | Kanban, ADRs, agent definitions |
| `di-042-review-fixes` | #4 | Round-one fixes |
| `di-044-round2-fixes` | — | **Current tip.** Round-two fixes. No PR opened. |

Stacked; merge bottom-up. The repo was completely empty at project start, which is why `main`
begins at a documentation commit.

`docs/KANBAN.md` is the board and carries all six verdicts in full, with reproductions:
DI-040 (review 1), DI-EVAL-1, DI-EVAL-2, DI-EVAL-3, plus cards DI-042 and DI-043. **There is
no card for the round-two fix pass** (`di-044-round2-fixes`) — that gap should be closed.

**Sprint 2 is groomed to card level**: DI-026 → DI-039 with dependencies, in `docs/KANBAN.md`.
Starts with projections ingestion and applying the league's own `scoring_settings` to raw
stats. **None of it has been started.**

---

## 10. Process rules, and an honest caveat

- Branch per card (`di-NNN-slug`), no direct commits to `main`, squash-merge after both
  verdicts. The user chose per-card explicitly.
- **Author → review → eval, three distinct identities.** Charter §6. `code-reviewer` and
  `evaluator` are defined in `.claude/agents/`.
- **Correction to an earlier claim in this file's predecessor:** those agents were described
  as structurally unable to write, enforced by their tool allowlist. That is **false** — they
  have `Bash`, and the evaluator has used it to write verdicts into `docs/KANBAN.md`. The
  independence is a convention, not an enforcement.
- Two consecutive rejections escalate to the orchestrator for scope renegotiation. **We are at
  three.** The rule fired twice and was overridden by explicit user instruction to keep
  iterating; the user then stopped the loop.
- **The deeper caveat:** these agents are the same model reading code written under the same
  assumptions. They have been strikingly effective at mechanical defects — every finding in
  this document came from them — but they are structurally likely to share the author's
  conceptual blind spots. A human reading `domain/ledger.py` would be worth more than a fourth
  agent round.

---

## 11. Running it *(partly superseded — see `docs/RUNBOOK.md` for the draft-night sequence)*

```bash
uv sync                                    # Python 3.12 via uv
make ci                                    # ruff, mypy --strict, pytest + coverage
uv run python -m draft_intel.cli replay    # fold the mock draft, print the ledger
uv run python -m draft_intel.cli smoke     # live API, validate the real league
```

Expected `replay`: `total spent $1979  remaining $21  keeper spend $549`, `keepers seen:
20/20`, `competitive picks: 140`, no alerts.

Expected `smoke`: four DI-004 warnings, `identity: 4/10 slots resolved`, and two BLOCKER lines
for DI-043. Both blockers are correct output, not failures.

**Network:** `api.sleeper.app` and `api.sleeper.com` are reachable; the user widened the
environment's egress policy. A 403 at CONNECT means it lapsed —
`curl -sS "$HTTPS_PROXY/__agentproxy/status"` confirms.

---

## 12. If you have four days *(SUPERSEDED — this was followed; see §0 for what held up and what did not)*

1. **Finish §4.1 D2** — a duplicate `pick_no` still loses its money with only a reject line to
   show for it. D1 and D3 are closed (commit `0da8214`).
2. **Stop the Sprint 1 review loop.** Document §4.2 and §4.3 as known-open. They are all live-
   ingestion robustness and none of them touch the priced board.
3. **Build Sprint 2**, DI-026 → DI-039, with a single review pass per card rather than two.
4. **The Sprint 2 gate is the deliverable that matters:** `make prep` produces the estimated
   priced board and *a human reads it*. That is the user's only chance to argue with the model
   while there is still time to fix it. A printable tier sheet with per-player walk-away
   prices, the keeper surplus board, and the QB endgame plan is worth more on the night than
   anything else in this repo.
5. **Chase DI-043.** Until those six managers join, the live cockpit cannot run at all, which
   is itself a strong argument for prioritising the offline board.

**Never cut:** money-conservation property tests, Case A/B equivalence, the keeper
double-count audit, the 2QB replacement-level check (which cannot be audited until DI-030
exists), and `make prep`.

**The charter's standing instruction, which has repeatedly paid for itself: if you find two
passages that contradict each other, stop and flag it rather than picking one.** A
silently-resolved contradiction in the valuation or ledger rules is exactly the defect that
survives to draft night.
