# Sleeper API Findings — Sprint 0 Discovery Spike

Captured 2026-08-31 against the live 2026 season. Fixtures in `fixtures/`.
Every claim below is observed, not assumed.

## Identity resolution

| Item | Value |
|---|---|
| Username | `mattchupiccu` |
| `user_id` | `1264817262276128768` |
| League | `1391959336820953088` — "GJFL 2026 Auction Draft" |
| Real `draft_id` | `1391959337445920768` (status `pre_draft`, 0 picks) |
| **User's `roster_id`** | **3** |
| Mock `draft_id` | `1400259554721165312` (status `complete`, 160 picks) |
| Prior season | `previous_league_id: null` — **no history to backtest against** |

**Real draft start time: 2026-09-06 01:00 UTC = Sat Sept 5, 9:00 PM ET.**
The user said 9/4. Sleeper says the 5th. One extra day, if Sleeper is right.

---

## 🔴 FINDING 1 — The league's own settings contradict each other

The §1 configuration tripwire fired on the first run. `GET /league/{id}.roster_positions`
and `GET /draft/{id}.settings` describe **two different leagues**:

| Slot | League `roster_positions` | Draft `settings` | |
|---|---|---|---|
| QB | **2** | **1** | 🔴 MISMATCH |
| RB | 2 | 2 | ok |
| WR | 2 | 2 | ok |
| TE | 1 | 1 | ok |
| FLEX | 2 | 2 | ok |
| K | 1 | 1 | ok |
| **DEF** | **0** | **1** | 🔴 MISMATCH |
| **BN** | **6** | **5** | 🔴 MISMATCH |
| **Total** | **16** | **15 rounds** | 🔴 MISMATCH |

The league object agrees with the charter exactly: 2QB, no DEF, 6 bench, 16 slots.
The draft object describes a 1QB league with a defense and 15 rounds.

`draft.metadata.scoring_type` is `"2qb"`, which sides with the league object, and the
mock draft the user built has `slots_qb: 2, slots_def: 0, rounds: 16` — matching the
league object too. **Working theory: the draft object holds stale defaults from before
roster settings were finalized, and Sleeper did not re-sync it.**

**This is not a cosmetic discrepancy.** Whether QB slots are 1 or 2 is the single
largest input to this valuation model — the charter's §4.2 sanity gate exists solely to
catch getting it wrong. A tool that booted off `draft.settings` would price a 2QB league
as a 1QB league and be confidently wrong all night.

**Required action: the commissioner must confirm and re-sync before draft day.**
Until then the boot validator trusts `league.roster_positions` (corroborated 2-to-1) and
refuses to start on any remaining mismatch.

## 🔴 FINDING 2 — `settings.max_keepers` is 1, not 2

`league.settings.max_keepers = 1`, while the charter and manifest specify **2 per team**.
`league.settings.draft_rounds = 3` is also unexplained. Commissioner question.

## 🔴 FINDING 3 — No auction-value field exists for 2026

`GET api.sleeper.com/projections/nfl/2026` returns 3,271 records. Every ADP variant is
present with full coverage — `adp_2qb`, `adp_ppr`, `adp_std`, `adp_half_ppr`, dynasty and
IDP variants. **There is no `auction`, `auction_value`, `dollar`, or `price` field.
Anywhere.**

Consequences:

1. **The league's keeper rule is not computable from the API.** `floor(0.75 ×
   sleeper_auction_value)` references a number Sleeper does not publish over REST. This
   independently confirms resolution C1 and makes it non-optional: retention prices must
   be **read**, from the draft room or the commissioner. They cannot be derived.
2. `MarketValueProvider` falls back to the **ADP-derived value curve**, and `adp_2qb` is
   the correct input for this league (full coverage, 2QB-specific). CSV import remains
   the override path.
3. §4.4's mandated fallback chain is now the *primary* path, not a contingency.

## FINDING 4 — Mock draft `roster_id` is null; key on `draft_slot`

Every pick in the completed mock has `roster_id: null` and `picked_by: ""`. The charter's
§2 example payload shows both populated. Mock drafts have no rosters behind them.

**Ingestion must key team identity on `draft_slot`, resolved through
`draft.slot_to_roster_id`** — never on `roster_id` directly. Keying on `roster_id` would
null out every pick in the replay fixture and collapse the entire ledger. Real league
drafts do populate it, so both paths need support and the replay gate exercises the hard one.

## FINDING 5 — `is_keeper` is `false` on the ceremonial keeper picks

The mock is a clean **Case B** fixture: picks 1–20 are the 20 keepers, two per slot, in
manifest order, at retention prices — all carrying `is_keeper: false`. Picks 21–160 omit
the field entirely (`None`).

So the charter's classification mechanism #2 (`is_keeper: true` → KEEPER) **would have
caught none of them.** Manifest match is not merely the primary mechanism, it is the only
one that works on this fixture. The charter's priority ordering was right.

Observed: **ΣK_t = $549** → `total_live_money = $1,451`, `discretionary_live = $1,311`.
These are the user's *estimated* retention prices; real ones arrive draft day.

## FINDING 6 — Keeper ID resolution, with a collision the charter missed

All 20 resolved to a unique `player_id` confirmed by position. Two name collisions in
Sleeper's 12,225-player map:

- **Josh Allen** → `2212` (G, no team) and `4984` (QB, BUF). Charter warned about this. Resolves to **4984**.
- **Lamar Jackson** → `4881` (QB, BAL) and `6994` (CB). **The charter did not warn about this one.** Resolves to **4881**.

Caleb Williams (`11560`) and Kyren Williams (`8150`) never actually collide — different
first names. The charter's concern there was unnecessary but harmless.

Every resolved ID also matches the `player_id` on the corresponding mock pick — an
independent second confirmation.

## FINDING 7 — Scoring and projections are workable

`league.scoring_settings`: `rec: 1.0` (**full PPR confirmed**), `pass_td: 4.0`,
`pass_yd: 0.04`, `rush_td`/`rec_td`: 6.0, `pass_int`: −1.0, `fum_lost`: −2.0.
**No `bonus_rec_te`** — no TE premium, so the TE market is undistorted as A.4.3 predicts.

Projections carry raw stat components (`rush_yd`, `rec`, `rec_yd`, `rec_td`, `fum_lost`,
`gp`) alongside precomputed `pts_ppr`, so §4.1's requirement to apply the league's own
scoring to raw projections is satisfiable. 598 of 3,271 records carry `pts_ppr` — those
are the fantasy-relevant set.

## FINDING 8 — Timers confirm the fast-auction premise

Real draft: `nomination_timer: 30`, `pick_timer: 60`. Mock: `10` / `10`. The §5 design
constraint (glanceable, keyboard-first, no modals) is correct, with slightly more room
than the charter's "10 seconds" assumed.

## FINDING 9 — Only 4 of 10 managers have joined

Rosters 5–10 have `owner_id: null`. Joined: `ajthebeard` (roster 2), `MasonWAlpert`
(roster 1), `mattchupiccu` (roster 3), `steeveegee300` (roster 4). The manifest's ten
owner names cannot be fully mapped to `roster_id`s until the rest join. Owner→roster
mapping must therefore be **late-bound and re-resolvable**, not a boot-time constant.

---

## 🟡 FINDING 10 — the commissioner reports 18 roster positions; the API reports 16

Asked to confirm the league shape, the commissioner answered: *"2QB, 0 DEF, 6B. 18 roster
positions, 16 rounds in the draft."*

The first three agree with `league.roster_positions` exactly and settle Finding 1 in its
favour for a third time. The fourth does not:

| Source | Roster positions | Draft rounds |
|---|---|---|
| `league.roster_positions` | **16** (10 starters + 6 BN, no IR, no taxi) | — |
| `draft.settings` | — | 15 (stale, Finding 1) |
| The user's own mock draft | — | 16 (160 picks, 16 per team) |
| Commissioner, directly | **18** | 16 |

`league.settings.taxi_slots` and `reserve_slots` are both `0`, so there is no hidden pair of
slots making 18 out of what the API returns. Either two bench spots are intended and not yet
saved, or the count includes something the API does not expose.

**Left open deliberately, because it changes nothing.** What scales prices is the number of
players *bought* — `teams × draft_rounds = 160` — and both readings agree on 16 rounds. Roster
capacity above the draft is waiver space that costs nothing at auction. ADR-0005 splits the two
fields so this can stay unresolved: `roster_size` tracks what the API says today, growth warns
rather than blocks, and the priced pool is untouched either way.

Worth confirming with the commissioner anyway, since it likely rides along with the DI-004
settings re-save.

---

## Finding 11 — the public draft object carries the live nomination, which §2's ⛔ Hard Constraint says has no public feed

**✅ DECIDED 2026-09-02: the manual layer is retained. Capture is carded as DI-052.** Charter §1
says that where two passages contradict, the contradiction is surfaced rather than picked
between. This was a charter passage contradicting observed data, which is the same situation
with more at stake, so it was escalated rather than resolved in code. The orchestrator's answer:
**§2's hybrid architecture stands unchanged** — the manual entry layer remains the live
nomination path, and nothing on draft night depends on the fields below.

What the finding is still worth is recorded separately: the same fields can be *logged*
alongside the picks poll without being relied upon, which is what DI-052 covers. That is
additive and reversible; the decision above is what keeps it from becoming load-bearing.

Charter §2:184, under "⛔ The Hard Constraint — read this twice", states there is no public
endpoint for, among other things, *the player currently on the block*, *the current high bid*,
and *who is currently bidding*, and derives the whole hybrid manual-entry architecture from it.

`fixtures/draft.json` — the plain public `/v1/draft/{id}` response, no websocket involved —
carries all three in `metadata`:

| Field | Observed value | Charter item it contradicts |
|---|---|---|
| `nominated_player_id` | `'4227'` | the player currently on the block |
| `highest_offer` | `'1'` | the current high bid |
| `nominating_slot` | `'5'` | who is currently bidding |
| `offering_slot` | `'5'` | " |
| `offering_user_id` | present | " |

**What is genuinely absent** is the bid *ladder* (history of offers) and the nomination timer.
And the picks feed is confirmed clean: no nominator field on the pick or in its metadata, across
all 160 mock picks. So retroactive analysis of a finished draft is impossible as documented —
this does not change DI-037's deviation.

**What it does change is what is possible going forward**, and that is the part needing a
decision:

- Nomination behaviour (§4.6's fifth tendency) becomes measurable if a poller records
  `nominating_slot` + `nominated_player_id` from the first nomination. It cannot be recovered
  afterwards, so **this is decided before 9/5 or not at all**.
- The manual-entry layer's premise weakens. It is still needed — a 1s poll against an
  overwritten single-slot field will miss fast nominations, and there is no bid ladder — but
  "there is no feed" and "there is a lossy feed worth cross-checking the operator against" are
  different architectures.

**Decided.** Reading this field is within the ToS constraint (it is the documented REST object,
not the internal websocket, which remains out of scope and untouched), but building on an
undocumented, unstable field on draft night is exactly the risk §2 was written to avoid — and
that risk is why the manual layer stays. DI-052 logs the fields as an observation feed only:
nothing reads them back on the night, so a shape change or a missed sample degrades a Sprint 3
analysis rather than the live cockpit.

---

## Endpoint status

| Endpoint | Status | Note |
|---|---|---|
| `/v1/user/{username}` | ✅ | |
| `/v1/user/{id}/leagues/nfl/2026` | ✅ | 1 league |
| `/v1/league/{id}` | ✅ | authoritative for `roster_positions` |
| `/v1/league/{id}/users` | ✅ | 4 of 10 |
| `/v1/league/{id}/rosters` | ✅ | 6 unowned |
| `/v1/draft/{id}` | ✅ | ⚠️ settings stale — see Finding 1 |
| `/v1/draft/{id}/picks` | ✅ | 160 on mock, 0 on real |
| `/v1/players/nfl` | ✅ | 14.6 MB, 12,225 players |
| `api.sleeper.com/projections/nfl/2026` | ✅ | 3,271 records, **no auction value** |

Fixtures committed: `players_slim.json` (4,233 QB/RB/WR/TE/K) and `projections_slim.json`
(598 scored) are trimmed from the raw payloads to keep the repo sane; the raw shapes are
documented above and re-fetchable.
