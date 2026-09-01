# Handoff — Draft Intelligence Platform

**Written 2026-08-31. Read this before touching anything.**

You are picking up a build with a hard, immovable deadline. This document is the shortest path
to being useful. Read it fully, then `docs/KANBAN.md` for live state, then `docs/CHARTER.md`
only for the parts you need.

---

## 1. What this is, in one paragraph

A single-user tool for one live Sleeper auction draft. 10 teams, $200 each, full PPR, **2QB**,
16 draftable roster spots. Every team enters with **2 keepers** retained at
`floor(0.75 × sleeper auction value)`, so 20 mostly-elite players are off the board before
bidding starts. That reshapes the pool, the budgets, the replacement levels, and creates
structural league-wide inflation. The tool ingests Sleeper's settled-picks feed, keeps a
correct money ledger, prices the remaining pool, and tells the user what to bid.

**The prime directive from the charter, which drives every trade-off:** this is used *once*,
live, under time pressure, with real money. A tool that is 80% featured and 100% reliable beats
one that is 100% featured and flaky. **When you must cut, cut features, never tests.**

---

## 2. Hard facts — do not re-derive these

| Fact | Value |
|---|---|
| Sleeper username | `mattchupiccu` → `user_id` `1264817262276128768` |
| League | `1391959336820953088` — "GJFL 2026 Auction Draft" |
| Real draft | `1391959337445920768` (status `pre_draft`, 0 picks) |
| **User's `roster_id`** | **3** |
| Mock draft (replay fixture) | `1400259554721165312` — complete, 160 picks |
| Draft time | **Sleeper says Sat Sept 5 2026, 01:00 UTC = Fri Sept 4, 9:00 PM ET.** The user said 9/4. Sleeper's `start_time` is the authority. |
| Prior season | None. `previous_league_id` is null — there is **no history to backtest against**. |

**Verified keeper slate** (Appendix A re-derived independently, it checks out): 7 QB / 6 RB /
7 WR / 0 TE / 0 K. Remaining base starting demand QB 13 / RB 14 / WR 13 / TE 10 / K 10 = 60,
plus 20 FLEX = **80 remaining starting slots** against **140 remaining roster spots**. Those two
numbers are different and are easy to transpose; assert both.

**AJ, Mason and Burt are the three teams holding no QB**, so each needs two. The user holds
Josh Allen and needs one. That asymmetry is the single most exploitable fact in the draft.

---

## 3. The nine discovery findings that shaped everything

Full detail in `docs/api-findings.md`. The ones that change how you write code:

1. **No auction-value field exists for 2026.** All twelve ADP variants are present with full
   coverage across 3,271 projection records; `auction`, `auction_value`, `dollar` and `price`
   are absent entirely. **The league's keeper rule references a number Sleeper does not publish
   over REST.** Retention prices must be *read* from the draft room, never derived.
   `floor(0.75 × …)` is a reconciliation *check*, not a price source. `adp_2qb` is the correct
   curve input for the fallback.

2. **Mock draft picks carry `roster_id: null` and `picked_by: ""`.** Team identity keys on
   **`draft_slot`**, never `roster_id`. The charter's example payload shows both populated;
   following it produces a ledger that yields nothing on the only replay fixture that exists.

3. **The 20 ceremonial keeper picks carry `is_keeper: false`.** The mock is a clean **Case B**
   fixture (keepers ceremonially drafted as picks 1–20 at retention prices). The charter's
   `is_keeper` detection catches **none** of them. Manifest match is the only classifier that
   fires on real data.

4. **The league's own settings contradict each other.** `league.roster_positions` says 2 QB /
   0 DEF / 6 BN / 16 slots; `draft.settings` says 1 QB / 1 DEF / 5 BN / 15 rounds, and
   `max_keepers` is 1 rather than 2. `roster_positions` wins — corroborated by
   `draft.metadata.scoring_type == "2qb"` and by the mock draft's own settings. See ADR-0002.

5. **The real draft object has no `slot_name_*` keys at all.** Only the mock does. Owner
   identity in production comes from joining `slot_to_roster_id` through `/rosters` and
   `/users`. This was a draft-night defect; see §6.

6. Name collisions in Sleeper's 12,225-player map: **Josh Allen** (guard `2212` vs QB `4984`)
   and **Lamar Jackson** (CB `6994` vs QB `4881`). The charter warned about the first, not the
   second. Position confirmation is mandatory. `fixtures/players_slim.json` deliberately retains
   off-position name collisions — an earlier trim deleted them and would have let broken
   resolution look correct.

7. Full PPR confirmed (`rec: 1.0`), **no TE premium**, raw stat components present so league
   scoring can be applied to projections per charter §4.1.

8. Real draft timers: 30s nomination / 60s pick. The fast-auction cockpit premise holds.

9. **Only 4 of 10 managers have joined.** Owner→slot mapping is incomplete and must be
   late-bound. See DI-043.

---

## 4. Where the work stands

Branches are stacked; merge bottom-up and GitHub retargets each base.

| PR | Branch | Base | State |
|---|---|---|---|
| #1 | `sprint-0-discovery` | `main` | Draft. Discovery, findings, fixtures. |
| #2 | `sprint-1-data-spine` | `sprint-0-discovery` | Draft. **Rejected by both review and eval**; fixes are in #4. |
| #3 | `di-000-process-scaffold` | `sprint-1-data-spine` | Draft. Kanban, ADRs, agent definitions. |
| #4 | `di-042-review-fixes` | `di-000-process-scaffold` | Draft. **Current tip.** Closes all 15 blocking findings. |

`main` exists at the charter/refined-plan commit — pure documentation, so no code reached it
unreviewed. The repo was completely empty when this started.

**Current CI:** ruff clean, `mypy --strict` clean on 22 files, **82 tests, 97% coverage**.
`make replay` reproduces every team's budget to the dollar ($1,979 spent / $21 left, keeper
spend $549, 140 competitive picks). `make smoke` boots against the live league with the four
expected DI-004 warnings.

### Sprint 1 was rejected twice, then fixed

Both an independent `code-reviewer` and an adversarial `evaluator` ran against Sprint 1. Both
returned **REJECT** — 12 blocking findings from the reviewer, 3 from the evaluator. Full verdicts
are in `docs/KANBAN.md` under DI-040 and DI-EVAL-1, with reproductions.

The headline lessons, because they will recur:

- **Two headline property tests were tautologies.** `remaining` is *defined* as
  `budget - spent`, so `Σ spent + Σ remaining ≡ Σ budget` held for any value of `spent`,
  including a badly wrong one. They now compare per-team spend against an independent replay.
- **The Case A/B bit-identity gate was vacuous.** It passed with the classifier replaced by a
  constant function, because the two payloads differed only in `is_keeper`, which never reaches
  derived state. Each case now gets only the mechanism it would really have.
- **The golden file was checked and is NOT circular.** The evaluator re-derived
  `tests/test_replay_gate.py::EXPECTED` from `fixtures/picks.json` with a script importing none
  of the project code. Exact match. Criterion 1 is genuinely earned.
- **Crash-restart was verified with a real SIGKILL**, not by dropping an object, and all seven
  event kinds round-trip byte-exact.

DI-042 closed all 15 blocking findings. **13 of the new regression tests were run against commit
`fa4f177` in a git worktree and fail there** — they encode the defects rather than restate the
fixes. Do this for any future fix; it is the only way to know a test can fail.

**#4 has not been re-reviewed or re-evaluated.** That was the next step when this handoff was
requested. Charter §7: two consecutive rejections escalate to the orchestrator for scope
renegotiation rather than a third attempt at the same approach. This would be attempt two.

---

## 5. Blocked on the user — nothing you can do in code

**DI-004 — the commissioner must re-save the draft settings.** The QB 2-vs-1 disagreement and
`max_keepers: 1`. Development is unblocked (the tool boots on `roster_positions` and warns), but
the *league* is not correct until this is fixed.

**DI-043 — six managers have not joined.** Jake, Connor, Keenan, Willie, Burt, TD. Their Sleeper
display names are unknowable until they join, so `config/owners.yaml` cannot be completed and
`manifest_keys(require=20)` resolves only 8 of 20 against the real league. **The tool cannot run
against the real draft until they join.** It now raises loudly rather than failing silently.

Known display names: `mattchupiccu` (slot 3), `ajthebeard`, `MasonWAlpert`, `steeveegee300`.

---

## 6. Known-open defects — verified still open at handoff time

These were raised by the evaluator and are **not** fixed. Confirmed by inspection just now, not
from memory.

| # | Defect | Where |
|---|---|---|
| 1 | **`KeeperClassifier.armed` is never set `True` in any product code path.** The Case B arming switch the charter requires exists as a dataclass field and nothing sets it. | `domain/classify.py` |
| 2 | **`reconcile()` is called by nothing outside tests.** It is the only function that detects a keeper *under*-count, and no product path invokes it. | `domain/classify.py:56` |
| 3 | **Negative amounts are accepted silently.** `PickSnapshot.amount` has no `ge=0`. A `-500` pick gives `spent=-500, remaining=700, alerts=()`. Conservation holds arithmetically so no test notices. | `models.py:51` |
| 4 | **`test_max_bid_never_strands_a_team` asserts an invariant that is false**, and is green only because no team in the fixture goes broke before pick 90. On a broke team the assertion is `14 <= 0`. The property-test twin guards correctly; the gate version does not. | `tests/test_replay_gate.py` |
| 5 | `Reclassify` still keys on `pick_no`, unsafe if Sleeper renumbers after a reversal. The diff now emits remove+observe on a renumber, but the event does not follow. | `models.py`, `domain/ledger.py` |
| 6 | Some league constants remain inline in `cli.py` (a Sprint-1 hand harness, not production). | `cli.py` |
| 7 | No ADR for the four production dependencies (httpx, pydantic, sqlalchemy, pyyaml). Charter requires one per dependency. SQLAlchemy is heavyweight for one four-column append-only table. | `docs/adr/` |

Also noted by the evaluator and worth carrying forward: nothing in the suite exercises the
**renumbered Case A twin** (competitive picks 1..140, keepers 141..160), which is the scenario
`competitive_seq` exists to handle. The design does hold up under it when tested by hand.

---

## 7. Architecture — the parts you must not break

**One equation.** `derived_state = f(api_events + override_events)`. Append-only log, full refold
on every change, never patched incrementally. Refolding 160 picks costs microseconds, and paying
that makes pick reversal, restart recovery, retroactive reclassification and override
commutativity correct *by construction*. ADR-0001.

**Money is uniform.** Every team starts at $200 and is decremented by every pick's amount, keeper
or competitive. **There is deliberately no keeper branch in `domain/ledger.py`.** Keep it that way.

**`draft_slot` is the canonical team key.** Never `roster_id`.

**`competitive_seq`** is a dense 1..N index over `COMPETITIVE` picks, **recomputed every fold and
deliberately not stable across folds.** All time-series analytics key on it, never `pick_no`.
**Never persist or cache a `competitive_seq` value.**

**Two different inflations, never merged:** `keeper_inflation` (structural, `live ÷ full_market`,
fixed, >1) and `market_inflation` (live, exactly 1.00 at pick 0 by construction, drifts).

**Four replacement baselines**, mapped explicitly in ADR-0001 because charter §4.2 and §4.3 never
paired them. Pricing uses the **last-drafted** baselines.

**The optimizer is a DP, not an ILP** (ADR-0003). The charter demands both PuLP and a 200ms
walk-away budget; CBC's subprocess overhead makes those mutually exclusive at 40–80 solves per
curve. CBC is retained as an offline test oracle. Walk-away prices are precomputed per player
after each settled pick, so the live path is a lookup.

**ILP objective includes a bench term** (ADR-0004): `starting points + λ × Σ bench VORP`, λ
default 0.2, exposed as a live slider. λ=0 recovers the charter's literal objective.

```
src/draft_intel/
  config.py     LeagueConfig + graded boot tripwire        models.py   types, events
  sleeper/      client (rate floor, breaker), poller (snapshot diffing)
  domain/       identity, keepers, classify, ledger        store/      append-only SQLite
  replay/       harness, Case A synthesis
```

---

## 8. Process rules in force

- **Branch per card** (`di-NNN-slug`), no direct commits to `main`, squash-merge only after both
  verdicts. The user explicitly chose per-card over per-sprint. Sprints 0 and 1 were not
  retroactively split; per-card runs forward from DI-042.
- **Author → review → eval, three distinct identities.** Charter §6: an agent may never review or
  evaluate its own work. `code-reviewer` and `evaluator` are declared in `.claude/agents/` with
  **no write tools**, so they structurally cannot fix what they find.
- The evaluator gets **only** acceptance criteria and the artifact — never the implementation
  plan or the author's reasoning — and is told to *run* it, not read it.
- **"LGTM" is a rejected verdict.** Verdicts are written into the card in `docs/KANBAN.md`.
- Sprints 0 and 1 were originally built with **no independent review at all** — authored and
  self-checked. That was a process violation, caught by the user, and is why both were rejected
  when finally reviewed. Do not repeat it.

**Honest caveat on the agent review loop:** these agents are the same model reading code written
under the same assumptions, so they are most likely to miss precisely the errors the author was
already blind to. Treat verdicts as a strong filter for mechanical defects and a weak one for
conceptual ones. Genuine independence means a human reading `domain/ledger.py`.

---

## 9. Running it

```bash
uv sync                              # Python 3.12 via uv
make ci                              # ruff, mypy --strict, pytest + coverage
uv run python -m draft_intel.cli replay   # fold the mock draft, print the ledger
uv run python -m draft_intel.cli smoke    # hit the live API, validate the real league
```

Expected replay output: every team 16 picks / 2 keepers, `total spent $1979 remaining $21
keeper spend $549`, `keepers seen: 20/20`, `competitive picks: 140`.

**Network:** `api.sleeper.app` and `api.sleeper.com` were originally blocked by this
environment's egress policy; the user widened it. If they 403 again at CONNECT, that is the
cause — `curl -sS "$HTTPS_PROXY/__agentproxy/status"` confirms.

---

## 10. What to do next

In order:

1. **Re-review and re-evaluate PR #4** with fresh `code-reviewer` and `evaluator` agents. This is
   attempt two of two; a second rejection escalates for scope renegotiation.
2. Close the seven known-open defects in §6, or consciously defer them with a written reason.
3. **Sprint 2, cards DI-026 → DI-039** — groomed with dependencies in `docs/KANBAN.md`. Starts
   with projections ingestion and applying the league's own `scoring_settings` to raw stats.
4. **Sprint 2 gate is the thing that matters most to the user personally:** `make prep` produces
   the estimated priced board and *a human reads it*. It is their only window to argue with the
   model while there is still time to fix it. Prioritise reaching it.

**Scope reality, stated once.** The user chose the full charter — five sprints, ten agent roles,
90% coverage, ILP optimiser, React cockpit, Playwright, 500-run Monte Carlo, two 60-minute
rehearsals — and reaffirmed it when the concern was raised. That does not fit the time remaining.
`docs/KANBAN.md` carries a cut-order; the first item is the 500-run Monte Carlo and the p<0.01
bot gate, which measures the model against bots we wrote ourselves and therefore carries little
information. **Never cut:** money-conservation property tests, Case A/B equivalence, the keeper
double-count audit, the 2QB replacement-level check, `make prep`.

**The standing instruction from the charter, which has already paid for itself several times: if
you find two passages that contradict each other, stop and flag it rather than picking one.** A
silently-resolved contradiction in the valuation or ledger rules is exactly the kind of defect
that survives to draft night.
