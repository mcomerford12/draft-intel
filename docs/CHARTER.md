# Draft Intelligence Platform — Build Context & Charter

**Handoff document for an autonomous Claude Code agent team.**
**Owner:** league manager (single user, one seat at the table)
**Hard deadline:** live auction draft in ~7 days. Ship-blocking date is non-negotiable.
**Repo name:** `draft-intel`
**Ships with:** `config/keepers.yaml` (the keeper manifest — see Appendix A)

**Settled and not up for debate:** league settings (§1), floor rounding on keepers, the keeper slate itself (Appendix A), local-first stack (§3), the valuation methodology (§4), and the review/evaluator independence rules (§6).

**Genuinely unknown, resolve as you go:** whether keepers are pre-loaded in Sleeper (§2), which auction-value fields the undocumented endpoint exposes for 2026 (§4.4), the keeper value-snapshot date (Appendix A.6), and everything in §11.

**Needed from the user at Sprint 0:** their Sleeper username (to resolve `league_id`, `draft_id`, and their own `roster_id`). Ask once, early, and do not block other work waiting for it.

---

## 0. Read This First (Orchestrator Brief)

You are the **lead/orchestrator agent**. You do not write feature code yourself. You:

1. Decompose this charter into a kanban backlog.
2. Spawn specialized subagents to execute cards.
3. Enforce that **every** line of code passes an independent review agent and an independent evaluator agent before a card moves to Done.
4. Re-groom scope after every sprint based on evaluator findings.

**The prime directive:** this tool is used *once*, live, under time pressure, with real money and real stakes on the line. A tool that is 80% featured and 100% reliable beats a tool that is 100% featured and flaky. **Reliability and latency outrank feature count in every prioritization decision.** When you must cut, cut features, never cut tests.

**The second directive:** the user cannot test this against a live auction before draft day. Therefore the **replay harness and mock auction simulator are not "nice to have testing infrastructure" — they are the primary product surface during development** and must be built in Sprint 1, before any analytics.

---

## 1. The League (Ground Truth Configuration)

| Parameter | Value |
|---|---|
| Platform | Sleeper |
| Draft type | **Auction** |
| Teams | **10** |
| Budget per team | **$200** |
| Total pot | **$2,000** |
| Scoring | **Full PPR** |
| Season | 2026 |

**Roster (starters):**

| Slot | Count |
|---|---|
| QB | 2 |
| RB | 2 |
| WR | 2 |
| TE | 1 |
| FLEX (RB/WR/TE) | 2 |
| K | 1 |
| **Total starters** | **10** |
| Bench | 6 |
| **Total draftable spots** | **16** |
| IR | 2 (not draftable — season-long roster feature) |

### 1.1 Keepers — this reshapes the entire economy

**Every team enters the auction with 2 keepers already selected, retained at 75% of their Sleeper auction value.**

This is not a cosmetic detail. It changes the pool, the budgets, the replacement levels, and the baseline inflation rate. Treat it as a first-class part of the domain model, not a preprocessing step.

```
keepers_per_team     = 2
keeper_price_t,p     = floor(0.75 × sleeper_auction_value_p)   # ROUND DOWN, confirmed
K_t                  = Σ keeper_price over team t's 2 keepers
open_slots_t (t=0)   = 16 − 2 = 14
total_auction_picks  = 10 × 14 = 140
total_live_money     = 2000 − Σ K_t
discretionary_live   = total_live_money − 140
```

**Rounding is floor, confirmed by the user.** A player at a $47 Sleeper auction value is kept at `floor(35.25) = $35`. Implement as integer floor, not `round()`, not banker's rounding. Unit-test the boundary cases (`$1`, `$4` → `$3`, values where `0.75×` lands exactly on an integer).

**Budget derivation is uniform — do not special-case keepers.** Every team's ledger starts at `$200` and is reduced by the `metadata.amount` of *every* pick attributed to them, keeper or competitive. This holds whether keepers were pre-loaded by the commissioner or drafted live (see §2), so there is exactly one code path for money. `starting_budget_t = 200 − K_t` is a useful *planning* figure for pre-draft analysis, but it must never appear as a special case in the runtime ledger.

**Consequences the agent team must handle explicitly:**

1. **Spending power is unequal from pick 1, even though the ledger is uniform.** Do not confuse these. Every team's ledger starts at `$200` and is decremented by every pick (see the paragraph above) — that is one code path with no keeper special case. But because keeper costs differ, *remaining* budgets diverge immediately, and every consumer of budget data must read the per-team value rather than assuming a shared figure. `max_bid_t = budget_remaining_t − (open_slots_t − 1)`, where `open_slots_t` is 14 once both keepers are recorded.

2. **20 players are off the board before the auction starts.** Mostly high-value ones. The draftable pool, positional demand, and replacement levels must all be computed on the **post-keeper** universe. See §4.2.

3. **⭐ The 25% keeper discount creates structural league-wide inflation.** Because each keeper is retained below market, the value removed from the pool exceeds the money removed from budgets. The surplus flows into the auction as inflation on every remaining player:

   ```
   keeper_surplus_total = Σ (market_value_of_keeper − keeper_price)
                        ≈ 0.25 × Σ market_value_of_all_20_keepers
   ```

   **Baseline inflation at pick 0 will be greater than 1.0.** The model must compute it and display it prominently before the draft begins, in plain language: *"The room starts with $X of surplus buying power. Expect the field to clear about Y% over book value."* A user who does not internalize this number will systematically under-bid all night and end the draft with unspent cash. This is the single most actionable pre-draft output of the whole system.

4. **Keeper surplus is unevenly distributed.** A team keeping two elite players at 75% captures far more dollars of surplus than a team keeping two cheap fliers. Rank and display it — see §4.6.

5. **⭐ All 20 keepers are known in advance.** The user has supplied the full slate — every team's two players — before draft day; see **Appendix A** and the shipped `config/keepers.yaml`. **Retention prices are *not* supplied and must be derived** as `floor(0.75 × market_value)`, then reconciled against whatever Sleeper actually shows (see Appendix A.6 on the value-snapshot ambiguity). This is a significant advantage and the architecture should exploit it:

   - **The entire valuation model can be computed, validated, and frozen days before the draft.** There is no scramble to converge during the opening minutes. Pre-draft deliverables (§4.9) become a real milestone with time to inspect and correct them.
   - **Classification becomes deterministic rather than heuristic.** Any pick whose `player_id` is on the known keeper manifest is a keeper, full stop — no timing heuristics, no price-matching guesswork. See §2.
   - **Reconciliation becomes possible.** The system knows exactly what *should* happen and can alert the instant reality diverges — a wrong price loaded by the commissioner, a keeper that quietly changed, a team that enters only one.

   **The keeper manifest is expected-state, not ledger truth.** Store it as `config/keepers.yaml`, committed and user-editable. It feeds pre-draft valuation, pick classification, and reconciliation alerting. It is **never** by itself a source of budget or roster state — the picks feed remains the sole authority for money, per the uniform-ledger rule stated earlier in this section. Keeping these two roles cleanly separated is what prevents the divergence bug warned about in §2. (The user *may* manually promote a keeper into ledger state; that path and its safety rules are specified at the end of §2.)

   Even so, **the keeper set remains mutable input to the model, not a startup-time constant.** A full revaluation — pool, positional demand, replacement levels, dollar conversion, tiers — must be triggerable by any manifest change and complete inside the 200ms budget. Keepers can be entered wrong, corrected, or changed the day before, and the model must re-price without a restart.

**Derived facts the value model depends on:**

- Total players drafted league-wide: `160` (20 keepers + 140 auction picks)
- Minimum bid is `$1`; every team must reserve `$1` per unfilled slot
- **Max bid for a team** = `budget_remaining_t − (open_slots_remaining_t − 1)`
- **No DEF/DST slot.** Defenses are excluded from the player pool entirely. (Verify against the API — see below.)
- Starting slots by position: QB 20, RB 20, WR 20, TE 10, K 10, plus 20 FLEX allocated among RB/WR/TE — **less whatever the 20 keepers already occupy.**

> ### ⚠️ CRITICAL CONFIGURATION RULE
> **Do not hardcode any of the above.** At boot, fetch `GET /v1/league/{league_id}` and `GET /v1/draft/{draft_id}` and derive teams, budget, `roster_positions`, `scoring_settings`, and `rounds` from the API. Then **validate against the config file above and refuse to start with a loud, specific error on any mismatch.** The table above is a *tripwire*, not a source of truth. A commissioner changing a setting the night before the draft is a realistic and catastrophic failure mode.

> ### ⚠️ CRITICAL DATA RULE
> **Never hardcode player names, teams, rankings, or tiers anywhere in the codebase, tests, or fixtures used for production logic.** NFL rosters churn constantly through August. All player identity, position, team, injury status, and bye week comes from `GET /v1/players/nfl` at runtime, refreshed daily. Any player name appearing in source outside of a clearly-labeled test fixture is a review-blocking defect.
>
> **The one exception is `config/keepers.yaml`** (Appendix A), which necessarily names 20 specific players. It is *configuration*, not source, and it is user-editable by design. Even there, names are only an input to `player_id` resolution — **once resolved, all downstream logic keys on `player_id`, never on the name string.** Any code path that matches a keeper by name at runtime is a review-blocking defect.

---

## 2. What Has Already Been Verified (Do Not Re-Litigate)

These facts were confirmed before this handoff. Treat as established; spend your discovery budget elsewhere.

### Sleeper public REST API — documented, no auth, read-only

Base: `https://api.sleeper.app/v1`

| Endpoint | Use |
|---|---|
| `GET /user/{username}` | resolve username → `user_id` |
| `GET /user/{user_id}/leagues/nfl/{season}` | find the league |
| `GET /league/{league_id}` | settings, `roster_positions`, `scoring_settings` |
| `GET /league/{league_id}/users` | manager display names, avatars |
| `GET /league/{league_id}/rosters` | roster_id ↔ owner_id mapping |
| `GET /league/{league_id}/drafts` | locate the draft |
| `GET /draft/{draft_id}` | draft status, `settings.budget`, `settings.rounds`, `settings.teams`, `slots_*` |
| **`GET /draft/{draft_id}/picks`** | **the core feed** |
| `GET /players/nfl` | full player map, ~5MB, cache once per day |
| `GET /players/nfl?position={pos}&active=true` | filtered, much smaller payload |

**Rate limit: stay under 1000 calls/minute per IP or risk an IP block.** At a 1s poll interval on a single endpoint that is 60/min — a ~16x safety margin. Do not exceed a 1s floor.

**The auction price is in the pick payload.** Each element of `/draft/{draft_id}/picks` looks like:

```json
{
  "round": 1,
  "roster_id": 1,
  "player_id": "6794",
  "picked_by": "378716407027937280",
  "pick_no": 1,
  "draft_slot": 1,
  "draft_id": "787796366440124417",
  "is_keeper": false,
  "metadata": {
    "first_name": "...", "last_name": "...", "position": "WR",
    "team": "MIN", "status": "Active", "injury_status": "",
    "player_id": "6794", "years_exp": "2", "number": "18",
    "amount": "10"
  }
}
```

`metadata.amount` is **the winning bid, as a string.** Parse defensively. This single field makes settled prices, team budgets, and rosters fully reconstructible in real time.

### Sleeper internal API — undocumented but public and read-only

Base: `https://api.sleeper.com` (note: `.com`, not `.app`, and **no** `/v1`)

- `GET /projections/nfl/{season}?season_type=regular&position[]=QB&position[]=RB&...` — season-long projections
- `GET /projections/nfl/{season}/{week}?season_type=regular&position[]=...` — weekly
- `GET /stats/nfl/player/{player_id}?season_type=regular&season={year}` — player season stats
- `GET /projections/nfl/player/{player_id}?season={season}&season_type=regular&grouping=season`
- Supports an `order_by` parameter including ADP variants.

These are the endpoints Sleeper's own clients use. They are stable in practice but carry **zero compatibility guarantee**.

### ⛔ The Hard Constraint — read this twice

**There is no public feed for the in-progress nomination.** Sleeper's REST API exposes picks only *after they settle*. There is no documented endpoint or public websocket for:

- the player currently on the block
- the current high bid
- the bid ladder / bid history
- who is currently bidding
- the nomination timer

The draft room UI gets this over an internal websocket / GraphQL channel that is not part of the public API.

**Therefore the architecture is a hybrid, and this is a requirement, not a workaround:**

1. **Automatic layer (ground truth):** poll `/draft/{draft_id}/picks` every 1s. Settled picks are authoritative and reconcile everything.
2. **Manual layer (live nomination):** a keyboard-driven widget where the user types the player on the block and the current bid in under two seconds. This drives the "should I bid?" analytics *during* the nomination.
3. **Self-healing:** when the pick settles and arrives via poll, the manual entry is automatically reconciled against it, corrected, and cleared. The manual layer is never allowed to corrupt the authoritative state. If the user forgets to enter a nomination, nothing breaks — the poll picks it up.

**Do not attempt to reverse-engineer, scrape, or connect to Sleeper's internal websocket.** It is out of scope: it is unstable, likely against ToS, and a failure there on draft day is unrecoverable. Reviewers must reject any PR that attempts it.

### Other operational realities to design for

- **Picks can be undone.** Sleeper commissioners can reverse picks mid-draft. The picks array can *shrink* or *change*. Naive append-only ingestion will corrupt state. Ingestion must diff full snapshots, not assume monotonic growth.
- **The draft can be paused.** Status field on the draft object. Handle `pre_draft`, `drafting`, `paused`, `complete`.
- **Keepers are in play in this league, but their presence in Sleeper is UNVERIFIED.** Sleeper represents a keeper as a pick with `is_keeper: true` and `metadata.amount` carrying the retention price. Whether the commissioner has actually loaded the 20 is unknown, and the user does not expect to find out until the draft opens. **Sprint 0 should check the picks feed anyway** — if they are already there, that is valuable early confirmation — **but must not block on it or assume the answer.** Two cases, both fully supported, selected at runtime with no code change:
  - **Case A (expected) — keepers are pre-loaded in Sleeper.** They appear in `/draft/{draft_id}/picks` with `is_keeper: true` before the auction opens. Ingest as initial state.
  - **Case B (fallback, decided by the league) — the commissioner's keeper setup did not take.** In that event the league will *ceremonially draft the keepers as the first 20 auction picks*, two per team, at their keeper prices. These arrive through the normal picks feed as ordinary picks with `is_keeper: false`.
  - **This will not be known until draft night.** The system must handle both without a code change, a restart, or a config edit. Assume Case B will happen and be pleasantly surprised.

> ### The ceremonial-pick problem — design for this explicitly
>
> Case B is nearly free for the **money and roster** layer: a $35 pick decrements a budget by $35 and fills a slot whether it was bid on or ceremonially entered. One ledger path, no special case.
>
> It is *not* free for the **analytics** layer. Those 20 picks were not competitive bids. If they are treated as auction results they will poison skew statistics, inflation calibration, run detection, and every manager tendency profile — and they will do so silently, producing a system that looks like it is working while giving bad advice for the entire night.
>
> **Requirement: every pick carries a `pick_class` of `KEEPER` or `COMPETITIVE`.** All auction analytics filter to `COMPETITIVE`. All money, roster, slot, and max-bid math uses both. Classification is determined by:
>
> 1. **Manifest match (primary).** Because all 20 keepers are known in advance (§1.1), any pick whose `player_id` appears on the keeper manifest for that team is classified `KEEPER` automatically. This is deterministic and covers both Case A and Case B without the user doing anything. It is the main mechanism; the rest are backstops.
> 2. **`is_keeper: true`** → `KEEPER`. Confirms Case A.
> 3. **Keeper-mode arming switch** (Case B backstop). A prominent pre-draft toggle for the situation where a ceremonial pick is entered for a player *not* on the manifest — a late keeper swap the user didn't hear about. While armed, unmatched early picks are flagged for confirmation rather than silently treated as competitive bids.
> 4. **Manual reclassification of any pick, at any time, with one keystroke**, in either direction. This is just another override type per §4.8 and rides the same event log, so it is retroactive and free: reclassify a pick at 9pm and every downstream statistic recomputes correctly.
>
> **Reconciliation alerting (required).** Maintain a live `keepers seen: N/20` readout against the manifest, broken out by team. Alert immediately and specifically on any divergence:
> - a keeper pick whose amount differs from `floor(0.75 × market_value)` → *"Team 6's keeper loaded at $41, manifest says $38"*
> - a keeper entered for a player not on the manifest
> - a manifest keeper that never appears once competitive bidding has clearly begun
> - a team with fewer or more than 2 keepers recorded
>
> These are the errors most likely to actually occur, they are quiet, and each one silently corrupts a team's budget for the rest of the night. Catching them in the first three minutes is worth more than most of the analytics in this document.
>
> **The manifest is for expectation, the picks feed is for truth.** `config/keepers.yaml` drives pre-draft valuation, classification, and reconciliation alerting. It does **not** by itself derive budgets, rosters, or slot counts.
>
> **But the user must be able to promote a manifest keeper into real ledger state manually, and it must survive every subsequent poll.** This is required, not optional: if the commissioner's setup fails *and* the ceremonial draft is delayed or botched, manual entry is the only way the tool stays usable. Do not read the paragraph above as forbidding it.
>
> The way this stays safe is that **manual keeper entry is an override event on the same append-only log as everything else (§4.8), never a mutation of computed state.** Derived state is always `f(api_events + override_events)`, so a manual keeper is an *input* to recomputation and is structurally incapable of being wiped by a poll cycle. There is still exactly one ledger and one code path. What is forbidden is a *separate* keeper state store that the poller doesn't know about — that is the divergence bug.
>
> **Supersession and de-duplication (the actual risk):** the danger is not erasure, it is double-counting. If the user manually enters Team 4's keeper at $38 and the ceremonial pick for that same player later arrives through the feed, a naive implementation charges Team 4 twice and every number for that team is wrong for the rest of the night.
> - Match manual entries to incoming picks on `(player_id, roster_id)`.
> - On match, **automatically retire the manual entry** and log a visible reconciliation line in the pick feed: *"Team 4 / Player X — manual $38 superseded by pick at $38."*
> - If the amounts differ, the pick wins, and raise a **loud** alert naming both figures. A silent correction here is worse than no correction.
> - A team may never hold more than 2 keepers from any combination of sources. Assert it; alert on violation.
> - Property test: for any interleaving of manual keeper entries and matching real picks, in any order, each keeper is counted **exactly once**.

---

## 3. Recommended Stack (with rationale)

The user deferred this choice. **Recommendation: local-first, runs entirely on the user's machine.** Rationale: on draft day the only dependencies should be the laptop and Sleeper itself. A hosting provider having a bad afternoon must not be able to take the tool down. No auth, no accounts, no cloud, no cold starts.

| Layer | Choice | Why |
|---|---|---|
| Runtime | Python 3.12+, managed with **uv** | fastest reliable toolchain; the analytics are Python-native |
| API | **FastAPI** + uvicorn | async, WebSocket support, typed |
| HTTP client | **httpx** (async, with retry/backoff) | connection pooling, timeouts, testable via `respx` |
| Persistence | **SQLite** (WAL mode) + SQLAlchemy 2.x | zero-ops, durable, survives a crash mid-draft |
| Models | **Pydantic v2** | strict validation at the API boundary |
| Optimizer | **PuLP** (CBC) | roster optimization is a small ILP; solves in ms |
| Numerics | pandas, numpy, scipy | |
| Frontend | **React 18 + TypeScript + Vite** | |
| State/data | **TanStack Query** + **Zustand** | |
| UI | **Tailwind CSS** + **shadcn/ui** + **TanStack Table** | dense sortable big board |
| Charts | **Recharts** | |
| Transport | WebSocket push from FastAPI, HTTP for cold loads | sub-second UI updates without client polling |
| Py tests | **pytest**, pytest-asyncio, **respx**, **Hypothesis** | Hypothesis for money-conservation invariants |
| TS tests | **Vitest** + React Testing Library | |
| E2E | **Playwright** | drives the replay harness end to end |
| Lint/format | **ruff**, **mypy --strict**, eslint, prettier | |
| Package mgr (JS) | **pnpm** | |
| CI | GitHub Actions (or local `make ci` if no remote) | must run on every card |
| Run | `make draft` → one command, both processes, opens browser | |

**Version policy:** the agent team must check current stable versions at implementation time rather than trusting any version pinned from memory. Pin exact versions in `uv.lock` / `pnpm-lock.yaml`. **Lockfiles are committed and CI installs from them frozen.**

**Network binding:** bind `0.0.0.0` so the user can open the cockpit on a tablet or second monitor on the same LAN while drafting on the laptop. Print the LAN URL and a QR code on startup.

**Offline tolerance:** the full player map, projections, and computed baseline values are persisted to SQLite. If the network drops mid-draft, the app must stay up, keep serving the last known state, display a prominent connection-lost banner with time-since-last-successful-poll, allow the user to enter settled picks manually, and reconcile automatically when connectivity returns.

---

## 4. The Analytics Specification

This is the heart of the product. The quant agent implements exactly this. **Do not let an agent invent its own valuation methodology.** Deviations require an ADR and orchestrator sign-off.

### 4.1 Projections → league-scored points

Do **not** trust a pre-scored `pts_ppr` field blindly. Pull raw stat projections from `api.sleeper.com/projections/nfl/2026` and **apply the league's own `scoring_settings` object** from `GET /league/{league_id}`. This guarantees correctness if the league has any scoring quirk (TE premium, first-down bonuses, non-standard kicker scoring, etc.).

Emit a `projection_source` field per player and log any player where the computed score and Sleeper's own PPR figure diverge by more than 5% — that divergence is a bug signal.

Support an optional **CSV import** so the user can blend or override with an external projection set (FantasyPros, etc.). Blend weight configurable, default 100% Sleeper.

### 4.2 Replacement level (the step that makes or breaks a 2QB league)

> **Keeper adjustment — do this first, it is easy to get wrong.** Replacement level must be computed on the **post-keeper universe**, adjusting *both* sides of the equation:
> - **Supply:** remove the 20 keepers from the player pool entirely.
> - **Demand:** reduce league-wide positional slot demand by the slots the keepers already occupy. Assign each keeper to a slot using the same greedy lineup-filling logic (base slot first, then FLEX), so demand reduction reflects how the keeper will actually be started.
>
> Both shifts matter and they push in opposite directions. Removing elite players from supply raises the value of the remainder; removing their slots from demand lowers replacement thresholds. **A naive implementation that does one and not the other will produce plausible-looking but badly wrong prices.** Require explicit unit tests on both totals, which are different numbers and are easy to transpose:
> - **Remaining *starting* slots** = 100 total starters − 20 keepers = **80**
> - **Remaining *roster* spots** = 160 total − 20 keepers = **140**
>
> Assert both. A test that only checks one will pass while the other is wrong.

Compute **two** replacement baselines per position and use the second for pricing:

**(a) Starter replacement** — fill the remaining league-wide starting slots greedily:
1. Fill base slots by position (QB 20, RB 20, WR 20, TE 10, K 10) **minus keeper-occupied base slots**.
2. Fill the remaining FLEX slots with the highest-projected available RB/WR/TE regardless of position. Record the resulting RB/WR/TE flex split — **do not assume a split, derive it.**

**(b) Last-drafted replacement** — the correct baseline for auction pricing, because bench players cost real money. Simulate filling all **140 remaining** roster spots: after starters, allocate the remaining bench spots by expected positional draft demand. Derive that demand from the actual available pool (highest remaining VORP), constrained by realistic roster behavior:

These counts are **totals including keepers**; subtract the keeper count at each position to get auction demand. Getting this wrong double-counts the keepers and is the most likely arithmetic slip in the whole model.

- QB: ~24–28 rostered in total, **minus 7 kept ⇒ roughly 17–21 bought in the auction** (in a 10-team 2QB league nearly every startable NFL starter is owned — **this is the defining feature of this league**)
- K: exactly 10, none kept ⇒ 10 bought
- TE: ~14–18, none kept ⇒ all bought
- RB: total minus 6 kept
- WR: total minus 7 kept

Replacement points for a position = the projected points of the **last player at that position expected to be rostered**.

**Sanity gate (must be an automated test):** in this league, QB replacement level must land materially higher than in a 1QB league, compressing QB VORP at the top while making the QB20–QB28 band expensive. If the model prices QB1 like a 1QB league would, the model is wrong.

**Keeper interaction on QB — this is now a known fact, not a hypothesis.** The actual slate is **7 QB, 6 RB, 7 WR, 0 TE, 0 K** (Appendix A). Seven of the twenty starting QB slots are pre-filled, and the kept quarterbacks skew heavily to the elite tier, so *quality* supply is cut far more than the raw 35% suggests. Only 13 starting QB jobs remain, and **three teams need two apiece** (Appendix A.4). The remaining QB market is the most distorted market in this draft and the model must show it.

Assert as a hard error any run where remaining QB supply falls below remaining QB slot demand without prices responding sharply. Surface `remaining QB supply vs. remaining QB demand` as a dedicated, always-visible counter in the UI. **Zero TEs and zero kickers were kept**, so those two markets should come out of the model structurally undistorted — if the model shows TE scarcity comparable to QB, it is wrong.

### 4.3 VORP → dollars

Two distinct valuations are needed. Do not conflate them.

**(i) Full-market value** — what a player would cost in a keeper-free $2,000 / 160-slot auction. This is the reference used to price the keepers themselves and to compute keeper surplus.

```
VORP_i           = max(0, proj_points_i − replacement_points_full_market(i))
pool_full        = top 160 players by VORP
discretionary    = 2000 − 160 = 1840
dollars_per_vorp = discretionary / Σ VORP over pool_full
market_value_i   = 1 + VORP_i × dollars_per_vorp
```

**(ii) Live auction value** — what a player should cost in *this* auction, given the keepers are off the board and the money left in the room is `2000 − Σ K_t` spread unevenly across teams. **This is the number the user bids against.**

```
VORP_live_i      = max(0, proj_points_i − replacement_points_post_keeper(i))
pool_live        = top 140 available players by VORP_live       # keepers excluded
total_live_money = 2000 − Σ K_t
discretionary_live = total_live_money − 140
dpv_live         = discretionary_live / Σ VORP_live over pool_live
baseline_value_i = 1 + VORP_live_i × dpv_live
```

**Invariants (property-test all three):**
- `Σ market_value over pool_full == 2000` ± $1
- `Σ baseline_value over pool_live == total_live_money` ± $1
- `Σ K_t + total_live_money == 2000` exactly

If any fails, the model is broken and the app must refuse to present prices.

**Display both.** The UI shows full-market value alongside live auction value for every player, because the gap between them *is* the keeper inflation, made concrete per player. A player whose live value is $58 against a $47 full-market value tells the user, at a glance, exactly how much the keeper discount is costing them tonight.

Then apply, as clearly separated and individually toggleable adjustments:
- **Risk discount** — injury status, games-missed history, age curve at position. Keep the magnitude modest and document the coefficients in an ADR.
- **Uncertainty widening** — produce a value *range* (p25/p50/p75), not just a point estimate. The user is bidding against a distribution; show them one.

Store `baseline_value`, `adjusted_value`, and `market_value` as three distinct, separately-displayed fields. Never collapse them.

### 4.4 Market value (the "auction value" side of skew)

The user asked to measure skew against Sleeper's own values.

- **Primary:** attempt to source Sleeper's projected auction value / average bid via the internal projections endpoint (ADP and auction-adjacent fields). **Sprint 0 must empirically map which fields actually exist for the 2026 season and document the exact response shape.** Do not assume; observe and record a fixture.
- **Mandatory fallback:** if no usable Sleeper auction field exists, the system must still fully function. Market value falls back to (in order): user-supplied CSV import → ADP-derived value curve → the internal baseline value with a clear "no independent market source" badge in the UI.
- **Architectural requirement:** market value is a pluggable `MarketValueProvider` interface with at least three implementations. **No feature may hard-depend on an undocumented endpoint.** A reviewer must reject any PR where the app breaks if `api.sleeper.com` returns a 404.

### 4.5 Live inflation

Recompute after every settled pick.

```
remaining_money         = Σ (200 − all_spend_t) over all teams   # all_spend includes keeper picks
remaining_slots         = Σ (16 − all_picks_t) over all teams    # keeper picks count as filled slots
discretionary_remaining = remaining_money − remaining_slots
remaining_pool          = top `remaining_slots` available players by baseline_value
remaining_value         = Σ (baseline_value_i − 1) over remaining_pool
inflation               = discretionary_remaining / remaining_value
adjusted_value_i        = 1 + (baseline_value_i − 1) × inflation
```

Note that `baseline_value` already prices in the keeper effect, so `inflation` here starts near 1.0 and drifts with the room's actual behavior. Separately compute and display **`keeper_inflation` = live value / full-market value**, which is a fixed structural number known before the draft starts. Two different quantities, two different labels, never merged.

Also compute **per-position inflation** — this is the higher-signal metric and the one most likely to make the user money. Restrict money and slots to positional need (allocating FLEX proportionally to remaining positional demand). Surface it as: *"RB is inflating at 1.18× while QB has deflated to 0.91× — QBs are cheap right now."*

Chart inflation over pick number, overall and per position, live.

### 4.6 Skew (the headline metric)

Two distinct measures. Label them unambiguously in the UI; do not let an agent merge them.

| Metric | Formula | Meaning |
|---|---|---|
| **Market skew** | `price_paid − market_value` | did the room overpay vs. consensus |
| **Edge skew** | `price_paid − our_inflation_adjusted_value` | did the room overpay vs. *our* model |

Report both as absolute dollars and as a percentage of value. Aggregate across:

- **Per pick** — the live feed, color-coded
- **Per team** — cumulative skew, mean skew, skew std dev, `$ spent per projected point`
- **Per position** — where is the money going relative to value
- **Per price bucket** — do managers overpay at the top of the board or on scraps
- **League-wide distribution** — mean, median, σ, and a z-score for each pick so an outlier is instantly visible

**Manager tendency profiles**, built live and shown as a compact per-team card:
- positional spend distribution vs. league mean (Δ%)
- early vs. late aggression (skew regressed on pick number)
- reaction to runs — does this manager chase
- stars-and-scrubs vs. balanced (Gini coefficient of their roster spend)
- nomination behavior — do they nominate their own targets

#### Keeper surplus board (pre-draft deliverable, must exist before draft day)

Keeper skew is a distinct metric from auction skew and must be computed and presented separately, before the auction begins.

```
keeper_surplus_t = Σ (market_value_p − keeper_price_p) over team t's keepers
```

Present as a ranked table with, per team: the two keepers, their full-market values, their retention prices, dollar surplus, surplus as a % of the $200 budget, and **effective buying power** (`budget_remaining_t + keeper_surplus_t`) — which is the honest measure of how much team is really in the room. Two teams both showing $150 remaining are not equal if one of them captured $40 of keeper surplus and the other captured $6.

Feed `effective buying power` into the opponent-threat ranking in §4.7c. A team that kept cheap studs is dangerous in a way that a raw budget column will not reveal.

Also report **keeper surplus by position** — if the surplus is concentrated at QB, that confirms the QB scarcity thesis in §4.2 and should raise the user's willingness to pay at the position early.

### 4.7 Decision support (what actually wins the draft)

**a) My max bid** — `min(budget − (my_open_slots − 1), adjusted_value + strategic_premium)`, with the binding constraint labeled.

**b) Marginal value engine — the flagship feature.** For any player at any hypothetical price, answer *"does bidding this much make my team better?"*

Formulate as an ILP (PuLP/CBC): maximize projected **starting lineup** points subject to remaining budget, remaining roster slots, and lineup legality (2QB/2RB/2WR/1TE/2FLEX/1K), over the remaining player pool at inflation-adjusted prices. Solve twice — with the player forced in at price `X`, and with them excluded — and report the delta.

Render it as a **walk-away price curve**: the x-axis is bid price, the y-axis is Δ projected starting points. Where it crosses zero is the walk-away number, displayed as one enormous digit. This must recompute in **under 200ms** so it can update live as the bidding climbs.

**c) Opponent max bids.** For every other team, live: `budget − (open_slots − 1)`. Then the single most actionable auction display in existence:

> **Who can still afford this player, and at what price does each of them drop out.**

Rank opponents by (max bid × positional need × their demonstrated aggression at this position). This tells the user whether they are bidding against a real threat or against a manager who is about to get priced out.

**d) Positional scarcity and run detection.** Remaining startable players at each position vs. remaining league-wide need at that position. Alert on tier breaks: *"last player in RB Tier 2 is on the block."* Detect runs statistically — N consecutive picks at one position above the expected rate — and alert, because the correct response to a run is usually to sit it out.

**e) Nomination advisor.** Two modes:
- *Drain mode* — nominate players you do not want, at positions where opponents have both need and money, to burn their budget.
- *Bargain mode* — nominate your targets once opponents at that position are financially exhausted.
Rank candidate nominations by expected budget drained from rivals per dollar of personal risk.

**f) Roster completion planner.** Always show: *"With $X and Y slots left, here is the best legal roster you can still finish with"* — the ILP solution, refreshed after every pick. Include the projected starting lineup total and how it ranks against every other team's best achievable roster. This turns budget anxiety into an actual number.

### 4.8 Manual Override Layer ⭐ required, and architecturally load-bearing

**The user must be able to manually adjust team budgets and player values at any time, before or during the draft, and the system must remain correct afterward.**

This is not a debug affordance bolted on at the end. It is a first-class subsystem, specified here so no agent invents its own version. The motivating reality: on draft day the user's eyes are the highest-authority sensor in the room. If Sleeper lags, if a keeper price was entered wrong, if the commissioner grants someone a budget correction verbally, if the room is obviously valuing a position differently than the model — **the user must be able to correct the system in seconds and keep going.** A tool that cannot be corrected gets abandoned mid-draft.

#### Core design principle

**Overrides are events, not mutations.** Never overwrite a computed or API-derived value in place. Every override is an append-only, timestamped, reversible entry in the same event log that carries picks. Derived state is always recomputed as `f(api_events + override_events)`. This falls directly out of the event-sourced ingestion already required in Sprint 1, and it is the only design that survives a pick reversal, a restart, or a late correction without corrupting anything.

#### Precedence

`manual override  >  API-derived  >  model-computed`

The user always wins. **But the system must never silently hide a disagreement.** Whenever an override diverges from what the API or model says, display both values side by side with the delta. Never let the user forget they are looking at a number they typed rather than a number that was measured.

#### Budget overrides — two modes, both required

The subtle failure here is obvious once stated: if a budget override is stored as an absolute pin, the very next poll cycle will recompute derived spend and fight the user's correction forever. Solve it with correction events, not pins.

| Mode | Semantics |
|---|---|
| **Correction** (default) | Inserts a `budget_adjustment` event of `±$N` for team `t` at the current point in the log. All subsequent derived spend continues to apply normally on top of it. This is the right answer ~95% of the time. |
| **Reset baseline** | Declares "as of now, team `t` has exactly `$N`." Implemented as a computed correction event equal to `N − current_derived_budget`. Subsequent picks decrement from there. |

Both must also support editing a **keeper price** and a **starting budget** before the draft, since keeper amounts are the most likely thing to be wrong on day one.

**Invariant relaxation, deliberately:** with manual overrides active, `Σ budgets + Σ spent` may no longer equal `$2,000`. Do **not** crash, and do **not** silently renormalize. Display a persistent reconciliation banner showing the discrepancy and its source. The user may be correcting for something real. Property tests must assert money conservation *in the absence of override events*, and assert exact, auditable accounting *including* them.

#### Roster and keeper overrides

Manually asserting that a team owns a player at a price is a required override type, used for keepers that never made it into Sleeper and for settled picks entered during network loss. Same event log, same guarantees:

- Persists across poll cycles and restarts; cannot be wiped by recomputation.
- Automatically superseded by a matching real pick on `(player_id, roster_id)`, with the reconciliation surfaced in the feed.
- Counted exactly once, ever — see the de-duplication rules in §2.
- Reversible with one keystroke; visible in the override inspector like everything else.
- Carries a `pick_class` so a manually-entered keeper is excluded from auction analytics exactly like a real one.

#### Value overrides

Overridable per player: `baseline_value`, `market_value`, `projected_points`, `tier`, and target/avoid flags. Plus:

- **Bulk positional multiplier** — "scale all TE values by 1.15." The highest-leverage knob in a live draft, because positional mispricing is usually recognized wholesale rather than one player at a time. Must be a single control per position.
- **Blacklist / never-bid flag** — zero out a player so the optimizer stops recommending them (injury news, personal read).
- **CSV bulk import** of values, already required in §4.4, routed through this same override layer.

**Renormalization policy:** overriding one player's value must **not** silently redistribute value across the rest of the pool — that would make a single edit ripple unpredictably through every other price mid-draft. Default to no renormalization, and display the resulting deviation of `Σ values` from `total_live_money` as a visible number. Offer renormalization as an explicit, opt-in action with a preview of what it would change.

#### Reconciliation with the poller

- A **value** override is permanent until revoked. Poll cycles never touch it.
- A **budget** correction persists as a log entry; derived spend continues to apply on top.
- If a **settled pick** later contradicts a manual entry (the user typed the nomination at $54, it settled at $57), the API is authoritative for the *pick*, the override is retired automatically, and the correction is logged to the feed so the user sees what changed and why.
- Manual entry of a **settled pick** during network loss is a first-class flow: on reconnect, matching API picks supersede manual ones, duplicates are detected and merged by `player_id`, and any genuine conflict is surfaced for one-tap resolution rather than resolved silently.

#### Non-negotiable requirements

- **Override inspector panel.** A single always-reachable list of every active override, with author timestamp, original value, current value, and a one-click revert. Real failure mode being prevented: nudging TEs at 7:10pm, forgetting, and spending the rest of the night confused by prices. If overrides are invisible, they are dangerous.
- **Global revert-all**, and per-override undo.
- **Persisted to SQLite**, survives restart, exported with the state snapshot.
- **Visually badged everywhere.** Any displayed number that is or descends from an override renders with distinct treatment. No exceptions — the user must never confuse a typed number for a measured one at speed.
- **Fast.** Editing a value is a keystroke and an inline edit, never a modal, never a settings page. Full recompute after any override must stay inside the 200ms budget.

### 4.9 Pre-Draft Deliverables ⭐ promoted to core scope

Because all 20 keepers are known in advance, the full board can be priced days early. **This is now core scope, not a stretch goal.** The reasoning is practical: a valuation model you first see three minutes before the auction is one you cannot sanity-check. A model you see four days early is one you can argue with, correct, and trust.

Produce a **`make prep`** command that runs the full pipeline against the real keeper manifest and emits a static, printable report plus the same data in the cockpit:

1. **The priced board.** Every available player with projected points, VORP, live auction value (p25/p50/p75), full-market value, tier, and positional rank. Sorted and sliced by position.
2. **The structural keeper-inflation figure** (§1.1). One number, stated plainly: how much over book the field should be expected to clear, and why.
3. **The keeper surplus board** (§4.6) — per team, with effective buying power.
4. **Positional market map.** Remaining supply vs. remaining demand per position after keepers, with QB called out first. Where the cliffs are, and at what price.
5. **Tier sheet.** Tier breaks per position with the price gap across each break — the thing to actually print and put on the desk.
6. **Budget scenario planner.** Interactive: allocate a hypothetical budget across positions and see the best achievable roster and projected starting lineup total. Answers "if I spend $75 on two QBs, what does the rest of my roster look like?" before the money is real. Uses the same ILP as §4.7b, so it is mostly wiring, not new machinery.
7. **Target list** with per-player walk-away prices, exportable and loadable into the cockpit.

**Timing requirement:** `make prep` must produce usable output by the end of Sprint 2, even if the cockpit is unfinished. The user should be reading their priced board and arguing with it **at least three days before the draft.** If the model is wrong, that gap is the only chance to find out. Treat a working `make prep` as a Sprint 2 gate condition.

---

## 5. UI Specification — the Draft Day Cockpit

**Design constraints, in priority order:** glanceable under stress → keyboard-first → dense → dark. The user has roughly 10 seconds of decision time per nomination and will be simultaneously watching Sleeper. Anything requiring a mouse hunt or a scroll is a design failure.

The frontend agent must consult the `frontend-design` skill before implementation.

**Layout — single screen, no scrolling for the critical path:**

1. **Nomination bar (top, fixed, largest type on screen).** Player on the block, position, team, bye. Current bid (manual entry). Our adjusted value. Market value. **Walk-away price as the biggest number on the screen.** Live skew if it lands at the current bid. Count of opponents who can still afford it.
2. **My status strip.** Budget, max bid, $/slot remaining, open slots by position, current best-achievable projected lineup total.
3. **League grid (10 rows).** Per team: keepers (2, with retention price), starting budget, budget remaining, max bid, **effective buying power** (budget + keeper surplus), slots left of 14, positional needs as icons, cumulative skew, spend Gini. Sortable. Highlight teams that need the position currently on the block. Every cell inline-editable for budget correction.
4. **Big board.** Filterable, sortable, virtualized. Columns: player, pos, team, bye, proj pts, VORP, **live auction value**, adjusted value, **full-market value**, tier, my target flag, availability. Keepers shown struck through with owner and retention price, filterable out. Inline-editable value cells. Fast fuzzy search bound to `/`.
   - **Persistent scarcity counters** above the board: remaining supply vs. remaining demand per position, QB first.
5. **Analytics panel (collapsible).** Inflation curves, positional spend treemap, skew distribution histogram, run detector.
6. **Pick feed.** Reverse-chronological, color-coded by skew magnitude, with the buyer.

**Keyboard map (must be implemented, must be discoverable via `?`):**
`/` search · `n` new nomination · `↑/↓` adjust current bid · `Enter` commit · `Esc` clear · `t` toggle target on selected player · `e` inline-edit value on selected player · `b` budget correction for selected team · `o` override inspector · `1–6` jump to panel · `?` shortcut overlay.

**Non-negotiable UI behaviors:**
- Connection status is always visible: last successful poll timestamp, in seconds, in color.
- Every number that comes from a model is distinguishable from every number that comes from Sleeper, **and both are distinguishable from any number the user manually overrode.** Three visual treatments, consistently applied. The user must never confuse measured, modeled, and typed values at speed.
- An override count badge is always visible; it is never possible to have active overrides you cannot see.
- No modal dialogs. Ever. A modal during a live auction is a lost player.
- Optimistic rendering with rollback — the UI never blocks on a network call.

---

## 6. Agent Team Structure

Define these as Claude Code subagents in `.claude/agents/`. Each gets a focused system prompt, an explicit tool allowlist, and a narrow domain. **Subagents must not be given permission to modify tests they did not author, or to modify CI configuration.**

| Agent | Domain | Must never |
|---|---|---|
| `orchestrator` | (the main session) backlog, sprints, sequencing, scope arbitration, ADR sign-off | write feature code |
| `architect` | system design, ADRs, module boundaries, interface contracts, data schema | implement |
| `data-engineer` | Sleeper client, caching, polling, event ingestion, reconciliation, SQLite schema | touch valuation math |
| `quant-analyst` | projections, VORP, replacement levels, pricing, inflation, skew stats, ILP optimizer | touch UI or transport |
| `backend-engineer` | FastAPI routes, WebSocket, services, DI wiring | touch valuation math |
| `frontend-engineer` | React cockpit, state, keyboard, charts | touch backend logic |
| `test-engineer` | pytest/vitest/playwright, replay harness, mock auction simulator, fixtures | implement production features |
| `code-reviewer` | blocking review of every diff | author any code it reviews |
| `evaluator` | independent verification against acceptance criteria; adversarial | have seen the implementation reasoning |
| `docs-scribe` | runbook, ADR index, draft-day cheat sheet | |

### Independence rules — enforce these strictly

1. **An agent may never review or evaluate its own work.** If the same agent identity authored a card, a different identity must review and a *third* must evaluate.
2. **The evaluator is adversarial and reads only the acceptance criteria plus the built artifact** — not the implementation plan, not the author's reasoning. Its job is to find the failure, not to confirm the success.
3. **Review and evaluation verdicts are written artifacts** appended to the card, with specific findings. "LGTM" is a rejected verdict; the reviewer must state what it checked.
4. **Two consecutive rejections on a card escalate to the orchestrator** for scope re-negotiation rather than a third attempt at the same approach.

---

## 7. Process — Kanban + Sprints

### Board

Maintain `docs/KANBAN.md` as the single source of truth, updated at every state transition.

Columns: `Backlog → Ready → In Progress → In Review → In Eval → Done` plus `Blocked`.

**WIP limits:** In Progress ≤ 3, In Review ≤ 2, In Eval ≤ 2. If a limit is hit, finish work before starting work.

**Card schema:**

```markdown
### [DI-014] Reconcile pick reversals without state corruption
- **Sprint:** 1
- **Owner:** data-engineer
- **Depends on:** DI-009, DI-011
- **Size:** M
- **Acceptance criteria:**
  - [ ] Ingestion diffs full snapshots; does not assume monotonic pick growth
  - [ ] Removing a pick from the feed restores the buyer's budget and roster slot exactly
  - [ ] Changing a pick's amount in place updates derived state within one poll cycle
  - [ ] Property test: money conservation holds across 10k random add/remove/edit sequences
- **Reviewer verdict:** _(pending)_
- **Evaluator verdict:** _(pending)_
```

### Definition of Done — all must be true

- [ ] Acceptance criteria demonstrably met (evaluator ran it, not just read it)
- [ ] Unit tests written by an agent other than the implementer where feasible
- [ ] `ruff` clean, `mypy --strict` clean, eslint clean
- [ ] Coverage ≥ 90% on `quant/` and `ingest/`, ≥ 80% elsewhere
- [ ] No new dependency without an ADR
- [ ] Public functions typed and docstringed
- [ ] Reviewer verdict: approved, with written findings
- [ ] Evaluator verdict: approved, with written findings
- [ ] Full CI green
- [ ] `docs/` updated if behavior changed

### Git discipline

Branch per card (`di-014-pick-reversal`). No direct commits to `main`. Conventional commits. Squash-merge only after both verdicts. Tag a release at every sprint gate.

### Sprint gates

A sprint does not end because its cards are done. It ends when its **gate demo** passes, executed by the evaluator. If the gate fails, the orchestrator re-grooms and the sprint continues.

---

## 8. Sprint Plan

Sprints are scoped by milestone, not calendar days — but Sprint 3 must complete with ≥2 days of wall-clock slack before draft day.

### Sprint 0 — Discovery & Scaffolding
- **API discovery spike.** Hit every endpoint above against the real 2026 season. Record actual response shapes as committed fixtures. **Explicitly determine whether a Sleeper auction-value/ADP field exists for 2026 and document it.** Write findings to `docs/api-findings.md`.
- Locate the user's real `league_id` and `draft_id`; verify settings match §1; **report any mismatch immediately and loudly.**
- **Keeper manifest.** The full slate is **already supplied** — see Appendix A and the shipped `config/keepers.yaml`. Resolve all 20 to Sleeper `player_id`s **confirming by position** (note the Josh Allen QB/LB collision and the Caleb/Kyren Williams pair), produce a human-reviewable confirmation table, and compute expected retention prices as `floor(0.75 × market_value)`. **Report any price that does not reconcile with what Sleeper shows before writing another line of code** — a wrong manifest silently poisons every downstream number, and this is the cheapest possible moment to catch it.
- **Reproduce the Appendix A.4 structural findings independently.** If the model disagrees with the arithmetic there, stop and resolve the discrepancy before proceeding.
- **Keeper reconnaissance.** Check whether keepers are already loaded in Sleeper (Case A) or absent (Case B) per §2 — but **do not block on the answer.** Build both paths regardless.
- Repo skeleton, uv + pnpm, ruff/mypy/eslint, CI, `make` targets, `.claude/agents/`, ADR template.
- Architect writes `docs/adr/0001-architecture.md` and the module interface contracts.
- **Gate:** `make ci` green on an empty project; fixtures committed; API findings documented; league config verified against live API.

### Sprint 1 — Data Spine ⭐ highest risk, do it first
- Async Sleeper client: retries, exponential backoff, timeouts, circuit breaker, respects the 1000/min limit with headroom.
- Daily player cache with an ETag/staleness strategy.
- Event-sourced pick ingestion with **snapshot diffing** (handles undo, edit, pause, reorder).
- **`pick_class` classification engine** per §2: `is_keeper` detection, keeper-mode arming switch, floor-price auto-detection heuristic, and retroactive manual reclassification. Uniform `$200` ledger with no keeper special-casing.
- **Keeper-set-change revaluation trigger:** any change to the keeper set fires a full model recompute inside the latency budget.
- **Override event log** per §4.8: budget corrections, reset-baseline, value overrides, positional multipliers, revert. Same log as picks. This must land in Sprint 1, not later — retrofitting an override layer onto mutable derived state is a rewrite.
- Derived state engine: per-team budget, spent, roster, open slots, max bid — computed as `f(api_events + override_events)`, never mutated in place.
- Persistence to SQLite; crash-restart recovers full state **including overrides**.
- **Replay harness:** feed a completed historical Sleeper auction draft's picks through the pipeline at configurable speed (1x–100x).
- **Mock auction simulator:** 10 bot managers with configurable strategies (stars-and-scrubs, balanced, positional-hoarder, value-hunter, panic-bidder) producing a synthetic but realistic pick stream.
- **Gate:** replay a real completed 10-team auction and reproduce every team's final roster and final budget **exactly**, to the dollar, with keepers seeded and asymmetric starting budgets. Kill the process mid-replay and confirm it resumes with identical state including all overrides. Apply a budget correction mid-replay and confirm subsequent picks decrement correctly from the corrected baseline rather than reverting to the derived value.
  - **Case A / Case B equivalence test (blocking).** Replay the same draft twice: once with keepers pre-loaded as `is_keeper` picks, once with the identical keepers arriving as the first 20 ordinary picks and classified via the arming switch. **Every derived output — budgets, rosters, values, inflation, skew, tendency profiles — must be bit-identical between the two runs.** This single test is the strongest guarantee that draft night goes fine either way.

### Sprint 2 — Intelligence Core
- Projections ingestion + league-scoring application.
- Replacement level (both baselines), computed on the post-keeper universe with both supply and demand adjusted.
- **Dual valuation:** full-market value and live auction value per §4.3.
- **Keeper surplus board** and structural keeper-inflation figure per §1.1 and §4.6 — this is a pre-draft deliverable and should land early in the sprint, not last.
- Value override plumbing wired through the model (positional multipliers, per-player overrides, blacklist).
- `MarketValueProvider` interface + 3 implementations.
- Live inflation, overall and positional.
- Skew: market and edge, all aggregations.
- Opponent max-bid and affordability engine.
- ILP roster optimizer + marginal value / walk-away curve.
- Manager tendency profiles.
- **Gate:** `make prep` (§4.9) produces the full priced board against the real keeper manifest, and a human has reviewed it. Then: run 500 simulated auctions. Model-implied prices must produce a plausible distribution against real historical auction prices. The optimizer, playing as one seat against bots, must beat every bot strategy on projected starting points across the 500 runs at p<0.01. Money conservation invariants hold in every run. Walk-away recompute p99 < 200ms.

### Sprint 3 — The Cockpit
- FastAPI + WebSocket push.
- Full React cockpit per §5.
- Manual nomination entry + automatic reconciliation against settled picks.
- **Override UI:** inline value editing, per-team budget correction, positional multiplier controls, override inspector panel, revert-all, three-way visual badging (measured / modeled / typed).
- **Keeper-mode arming switch** as a large, unmissable pre-draft control, with a live "keepers recorded: N/20, teams complete: M/10" readout and one-keystroke pick reclassification from the feed.
- Keeper display: struck-through board entries, keeper surplus board, effective buying power column.
- Keyboard map, search, target list.
- Charts.
- **Gate:** Playwright drives a full 160-pick replay end to end. Pick-to-pixel latency p99 ≤ 2s. Zero console errors. A human-legibility pass: can the walk-away number be read at a glance from three feet away.

### Sprint 4 — Hardening & Draft Day Readiness
- Chaos suite: API 429, 500, timeout, malformed JSON, null `amount`, duplicate picks, pick reversal mid-poll, network drop and recovery, clock skew, laptop sleep/wake.
- Offline mode + manual settled-pick entry + reconciliation.
- Snapshot/restore, one-key state export.
- **`docs/RUNBOOK.md`** — startup checklist, what to do when X breaks, kill switches, how to fall back to a plain browser and still function. **First item on the checklist must be the keeper determination: open the draft, look at the picks feed, and either confirm keepers are loaded or arm keeper mode.** This is a 15-second decision the user makes under mild time pressure and it must be reduced to a single, unambiguous instruction.
- **`docs/DRAFT_DAY_CHEATSHEET.md`** — one page, printable: keyboard map, how to read each metric, the 2QB pricing intuition for this specific league.
- **Gate: full 60-minute rehearsal, run twice — once as Case A, once as Case B.** Simulated live draft at realistic pace, with injected failures, with the user's real league configuration, requiring zero developer intervention and zero restarts. The Case B run must include the user arming keeper mode, 20 ceremonial picks arriving, auto-disarm, and one deliberately misclassified pick corrected retroactively mid-draft.

### Sprint 5 — Stretch (only if Sprint 4 gate passed with slack)
- Nomination advisor.
- Post-draft report: final skew leaderboard, who won the auction, projected standings, biggest bargains and reaches.
- Deeper opponent bid-behavior modeling.
- (Pre-draft prep was promoted to core scope — see §4.9.)

---

## 9. Testing & Evaluation Strategy

**The user cannot test against a live auction. Simulation is the only validation available. Budget for it accordingly.**

| Layer | What |
|---|---|
| Unit | Every pure function in `quant/` and `ingest/` |
| **Property (Hypothesis)** | **Money conservation (no overrides):** `Σ spent + Σ remaining == $2,000` after *any* sequence of adds/removes/edits, where `spent` **includes keeper picks** — under the uniform-ledger rule (§1.1) keeper cost is not a separate term, and writing it as `Σ K_t + Σ spent + Σ remaining` double-counts every keeper. Assert separately that `Σ K_t` equals the keeper-classified subset of `Σ spent`. **Override accounting:** with overrides present, the ledger reconciles exactly to `$2,000 + Σ override_deltas`, and the discrepancy banner reports precisely that figure. **Max-bid legality:** no derived max bid ever lets a team fail to fill its 14 remaining slots. **Roster legality:** the optimizer never returns an illegal lineup and never proposes a keeper. **Value normalization:** `Σ market_value == 2000 ± $1` and `Σ baseline_value == total_live_money ± $1`. **Keeper demand:** after keeper slot assignment, remaining *starting* slots sum to exactly 80 and remaining *roster* spots to exactly 140 — assert both, they are different numbers and easy to transpose. **Override idempotence:** applying then reverting any override returns state bit-identical to before. **Override commutativity:** overrides and poll cycles interleaved in any order converge to the same state. **Manual/real keeper de-duplication:** for any interleaving of manual keeper entries and matching real picks, each keeper is counted exactly once and no team ever exceeds 2 keepers. **Keeper price floor:** `keeper_price == floor(0.75 × market_value)` for all generated values, including exact-integer boundaries. **Case equivalence:** for any generated draft, the Case A and Case B ingestion paths produce identical derived state. |
| Golden file | Real completed auction drafts → exact expected final state |
| Replay | Full historical drafts at 1x–100x |
| Simulation | 500-run Monte Carlo mock auctions with bot strategy diversity |
| Backtest | Value model ranking vs. actual prior-season outcomes; report rank correlation |
| Contract | Schema assertions on every live Sleeper response; alert on drift |
| Chaos | Every failure mode in Sprint 4 |
| E2E | Playwright over the replay harness |
| Perf | Pick-to-pixel p99 ≤ 2s; full recompute p99 ≤ 200ms; UI at 60fps with all 160 picks in |
| Soak | 4-hour continuous run without memory growth or connection leak |

**Evaluator agents additionally run:**
- **Adversarial review** — given only acceptance criteria and the artifact, actively try to break it.
- **Numerical sanity audit** — independently re-derive the value model on paper for a handful of players and compare against the code's output. Any unexplained divergence is a blocking defect.
- **The 2QB check** — verify quarterback pricing reflects 20 starting QB slots in a 10-team league, net of QB keepers. This is the most likely place for a subtle, expensive, silent error.
- **The keeper double-count audit** — independently verify that keeper players are removed from supply *and* their slots removed from demand, exactly once each. Deliberately construct a fixture where a naive implementation double-counts and confirm the code does not.
- **The ceremonial-pick contamination audit** — construct a Case B fixture and confirm no auction statistic differs from its Case A twin. Then deliberately leave one ceremonial pick classified as `COMPETITIVE` and confirm the resulting distortion is detectable, proving the filter is actually load-bearing rather than decorative.

---

## 10. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| No live bid feed exists | High | Designed-in hybrid manual layer (§2). Accepted, not solved. |
| Undocumented `api.sleeper.com` endpoint changes or dies | High | `MarketValueProvider` abstraction + CSV fallback. **No feature may hard-depend on it.** |
| Value model silently wrong for 2QB | **Critical** | Explicit replacement-level tests, independent evaluator re-derivation, simulator validation |
| Keeper supply/demand adjusted on one side only | **Critical** | Dedicated audit fixture, demand-sums-to-140 assertion, evaluator double-count audit |
| Keeper manifest wrong (bad price, stale keeper, wrong player) | High | Sprint 0 reconciles all 20 against `floor(0.75 × market)`; live `keepers seen: N/20` reconciliation alerting catches divergence in the first minutes |
| Commissioner's keeper setup fails; keepers drafted ceremonially | **Expected** | `pick_class` engine, arming switch, auto-detect, retroactive reclassification — no code change required on the night |
| Ceremonial picks silently poison skew/inflation/tendency stats | **Critical** | All auction analytics filter to `pick_class == COMPETITIVE`; evaluator test asserts a Case B draft produces statistics identical to the Case A equivalent |
| Keeper set changes late (swap, correction) | Medium | Keeper set is mutable model input, not a startup constant; sub-200ms full revaluation on change |
| Manual keeper entry double-counted against a later real pick | **Critical** | Supersession on `(player_id, roster_id)`, exactly-once property test, ≤2-keepers-per-team assertion, loud alert on amount mismatch |
| Override layer fights the poller, corrupting budgets | High | Corrections modeled as events, not pins; commutativity property tests |
| Active overrides forgotten and silently skewing prices | Medium | Override inspector, always-visible badge count, distinct visual treatment |
| Network fails during draft | High | Offline mode, local persistence, manual entry, reconciliation |
| Pick reversal corrupts state | High | Snapshot diffing, property tests, event sourcing |
| Scope creep eats the deadline | High | Sprint gates; features are cut, tests are not |
| Sleeper IP block from over-polling | Medium | 1s floor, single poller, backoff, 16x headroom |
| League settings change before draft | Medium | Boot-time validation tripwire against §1 |
| UI too slow/dense to use under pressure | Medium | Latency SLOs; three-feet legibility test; keyboard-first |

---

## 11. Open Questions — Resolve Autonomously, Document the Decision

Do not block on these. Pick the sensible default, write an ADR, flag it for the user in `docs/DECISIONS_FOR_REVIEW.md`.

1. `league_id` / `draft_id` — obtain via username lookup; if unavailable, ship a first-run setup screen.
2. ~~Keeper rounding rule~~ — **RESOLVED: floor.** `floor(0.75 × sleeper_auction_value)`. Test the boundaries.
3. **Which Sleeper auction value the 75% was taken from, and when it was snapshotted.** Sleeper's values drift as projections update, so a keeper priced in July differs from one priced in August. Default: treat entered keeper prices as fixed historical fact and never recompute them; use current values only for surplus analytics. Flag if the observed prices imply a different snapshot date.
4. Whether the two keeper slots are positionally constrained — assume not; the manifest will reveal it.
5. Kicker valuation — kickers are near-worthless in VORP terms and will price at $1. Correct. Do not over-engineer.
6. Bye-week and stacking considerations in the optimizer — out of scope for v1 unless Sprint 5 slack exists.
7. Injury-risk coefficient magnitudes — pick defensible values, document them, make them configurable.
8. Whether to model opponent bidding behavior predictively — Sprint 5 stretch only.
9. Whether value overrides should persist across app restarts on a *new* day (they do by default; offer a "clear overrides" startup prompt if the last session ended more than 12 hours ago).

---

## 12. First Actions for the Orchestrator

1. Read this document in full. Confirm you understand the §2 hard constraint and the §1 configuration and data rules.
2. Create the repo skeleton and `docs/KANBAN.md`.
3. Spawn `architect` to produce ADR-0001 and interface contracts.
4. Spawn `data-engineer` on the Sprint 0 API discovery spike **immediately and in parallel** — everything downstream depends on knowing what the 2026 endpoints actually return, and it is the single highest-uncertainty item in the build.
5. In the same parallel batch, resolve the 20 keepers in `config/keepers.yaml` to Sleeper `player_id`s **confirming by position** (note the Josh Allen QB/LB collision, Appendix A.1) and produce the human-review confirmation table. This is cheap, blocking for the value model, and catches an unrecoverable class of error.
6. Groom the full backlog to card level for Sprints 0–2, and to epic level for 3–5.
7. Report back: proposed card list, sprint gates, the top three risks you see that are not in §10, and anything in this charter you believe is wrong.

**One standing instruction for the whole build:** this charter was assembled incrementally and revised five times. If you find two passages that contradict each other, **stop and flag it rather than picking one.** A silently-resolved contradiction in the valuation or ledger rules is exactly the kind of defect that survives to draft night.

**Push back if you disagree with something in this document.** It was written by someone who has not seen your codebase and cannot see your discovery findings. A charter is a starting position, not scripture — but deviations get an ADR.

---

## Appendix A — Keeper Manifest & Derived Market Structure

The full keeper slate is **known and supplied**. The machine-readable manifest ships alongside this charter as `config/keepers.yaml`. Everything below is arithmetic derived from it and should be verified, not trusted, by the agent team.

### A.1 The slate

| Owner | Keeper 1 | Keeper 2 |
|---|---|---|
| AJ | Christian McCaffrey (RB) | Zay Flowers (WR) |
| Jake | Jalen Hurts (QB) | Jahmyr Gibbs (RB) |
| **Me (user)** | **Josh Allen (QB)** | **Drake London (WR)** |
| Mason | Ja'Marr Chase (WR) | Amon-Ra St. Brown (WR) |
| Connor | Lamar Jackson (QB) | Jaxon Smith-Njigba (WR) |
| Keenan | Caleb Williams (QB) | Kyren Williams (RB) |
| Steve | Trevor Lawrence (QB) | Bijan Robinson (RB) |
| Willie | Jayden Daniels (QB) | Jonathan Taylor (RB) |
| Burt | Breece Hall (RB) | George Pickens (WR) |
| TD | Bo Nix (QB) | Puka Nacua (WR) |

**Positional distribution: 7 QB, 6 RB, 7 WR, 0 TE, 0 K.**

> ### ⚠ Player ID resolution — do not match on name
> Resolve every keeper to a Sleeper `player_id` via `GET /v1/players/nfl` and **confirm by position**, then commit the resolved IDs. Two live collisions in this exact slate:
> - **Josh Allen** — there is both a QB and a defensive player by this name in Sleeper's database. Matching on name alone will silently attach the user's own keeper to the wrong player and corrupt their roster.
> - **Caleb Williams (QB) / Kyren Williams (RB)** — same surname, different owners, different positions.
>
> Require a printed confirmation table (name, position, NFL team, resolved `player_id`) reviewed by a human before the manifest is accepted. This is a five-minute check that prevents an unrecoverable class of error.

### A.2 Remaining league-wide starting demand

| Pos | Base slots | Kept | Remaining |
|---|---|---|---|
| QB | 20 | 7 | **13** |
| RB | 20 | 6 | 14 |
| WR | 20 | 7 | 13 |
| TE | 10 | 0 | **10** |
| K | 10 | 0 | 10 |

Plus 20 FLEX slots, of which none are consumed by keepers beyond the base allocation above.

### A.3 Per-team remaining needs — all 14 picks

| Owner | QB | RB | WR | TE | FLEX | K |
|---|---|---|---|---|---|---|
| AJ | **2** | 1 | 1 | 1 | 2 | 1 |
| Jake | 1 | 1 | 2 | 1 | 2 | 1 |
| **Me** | **1** | **2** | **1** | **1** | **2** | **1** |
| Mason | **2** | 2 | 0 | 1 | 2 | 1 |
| Connor | 1 | 2 | 1 | 1 | 2 | 1 |
| Keenan | 1 | 1 | 2 | 1 | 2 | 1 |
| Steve | 1 | 1 | 2 | 1 | 2 | 1 |
| Willie | 1 | 1 | 2 | 1 | 2 | 1 |
| Burt | **2** | 1 | 1 | 1 | 2 | 1 |
| TD | 1 | 2 | 1 | 1 | 2 | 1 |

### A.4 Structural findings the model must reproduce

These are consequences of the arithmetic above. **The agent team must verify each independently rather than accepting it — but if the model contradicts one of these, that is a strong signal the model is wrong, not the arithmetic.**

1. **Seven of twenty starting QB slots are pre-filled, and the kept QBs are top-heavy.** Only 13 starting QB jobs remain, but supply of *quality* QBs has been cut far more than 35% because keepers skew to the elite tier. The remaining QB market is the most distorted market in the draft.

2. **⭐ Three teams — AJ, Mason, and Burt — need TWO starting QBs each.** This is the single most exploitable fact in the manifest. Six of the thirteen remaining QB starting slots belong to just three managers, all of whom must transact in a depleted market. They cannot opt out. Expect them to drive QB prices well past model value, and expect at least one of them to get squeezed badly late.
   - The user needs only **one** QB. That is a structural advantage and the strategy should be built around it.
   - The system must surface a dedicated **"QB pressure" panel**: remaining QB supply by tier, which of the three two-QB teams have filled a slot, and their remaining budgets. When two of the three have their QBs, the price collapses.

3. **Zero TEs and zero kickers were kept.** Those markets are structurally undistorted — full demand, full supply. Every team needs exactly one TE and one K. Since keeper surplus inflates the whole board, and TE/WR/RB/QB supply is depleted while TE supply is not, **TE is where the user is least likely to be forced into an overpay.** Verify this against the model rather than assuming it.

4. **RB and WR elite tiers are heavily depleted** (6 and 7 respectively, concentrated at the top). Replacement level at both positions rises sharply. The model must reflect that mid-tier RB/WR are worth more here than in any generic auction value list.

5. **Mason has no WR need at all** (kept two elite WRs) and needs 2 QB + 2 RB. Highly predictable bidding behavior — usable directly by the nomination advisor and the opponent-threat model.

6. **Keeper surplus is concentrated in the elite keepers.** Because retention is `floor(0.75 × value)`, the dollar surplus scales with the player's value. Teams holding two premium keepers captured materially more buying power than teams holding one premium and one mid-tier. Compute exactly; do not eyeball. Feed into `effective buying power` (§4.6).

### A.5 The user's own position

The user holds **Josh Allen (QB) + Drake London (WR)** and needs: 1 QB, 2 RB, 1 WR, 1 TE, 2 FLEX, 1 K, plus 6 bench = **14 picks**.

Having one elite QB already, in a league where three rivals need two apiece, is the defining feature of the user's draft. The pre-draft prep report (§4.9) must include an explicit **QB endgame plan**: at what price it is correct to take the second QB early versus wait for the two-QB teams to exhaust themselves, with the crossover price computed rather than asserted.

### A.6 Value snapshot ambiguity — resolve with the commissioner

Retention prices are `floor(0.75 × sleeper_auction_value)`, but Sleeper's auction values drift as projections update. **A keeper priced from a July snapshot differs from the same keeper priced in late August.** The user should confirm with the commissioner which snapshot was used, or simply read the actual dollar amounts out of the Sleeper draft room once keepers are loaded. Until confirmed:
- Compute expected prices from current values.
- Flag every keeper where the loaded price differs from the computed price by more than $2.
- Treat the loaded price as truth and the computed price as a check.
