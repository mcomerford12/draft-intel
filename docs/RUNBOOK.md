# Draft night

**Saturday 2026-09-05, 19:00 MDT.** One page. Read it once now, not at 7pm.

---

## 1. Thirty minutes before

Four commands, in this order. Each one either passes or tells you what is wrong.

```bash
make ci                # the tool is sound          (~2 min)
make rehearsal-live    # the LEAGUE is ready        (~1 min)
make prep              # print the board            (~1 min)
make cockpit           # then open localhost:8000/live
```

**`make rehearsal-live` is the one that matters.** It replays 160 real picks through the real
cockpit against the real league. It fails while any keeper cannot be placed on a slot — which is
not a bug report, it is the league telling you it is not ready. Read the seating block it prints
and check every manager is where you expect.

`make prep` writes `reports/prep.txt` — the printable board: priced top 30, tier sheet, keeper
surplus, positional map, budget scenarios, and a walk-away price per target. **Print it.** If the
laptop dies at 8:15 you still have prices, tiers and walk-away numbers on paper, and that is the
difference between a bad night and a wasted one.

**Read its first `!!` block before you print.** It states where the keeper prices came from, and
right now the answer is "not this league" — see §6.

`make cockpit` polls the live draft. `make serve` does not — that is deliberate, so opening the
price table never opens a socket to Sleeper.

---

## 2. What the page is telling you

Top to bottom, in the order it renders:

| Line | Means |
|---|---|
| **Red bar** | A blocker. Every number below it is untrustworthy until you fix it. |
| **`● live · 1s ago`** | The connection and the age of the reading. |
| **`NOT LIVE`** | The last reading is stale. The figures are still on screen and still that old. |
| **`0 picks, 0 competitive`** | Total picks, and how many count as bids. The gap is keepers. |
| **`backstop off` / `ARMED`** | Whether unrecognised early picks get flagged. §5. |
| **the block** | What the nominated player is worth to you, and who can outbid you. |
| **the room** | Every team's money, slots and max bid. Yours is highlighted. |
| **inflation** | What the room is paying over book, live. |

**`inflation 1.40x` before a single pick is not a bug.** It is the structural read: $1,840 of
discretionary money chasing $1,311 of value. It moves toward the live market as picks land.

---

## 3. The one thing you tell it

**Sleeper does not publish the nomination over its public API.** Every other number on the page
arrives on its own; this one does not.

When the room names somebody, type them in **who is up** and pick from the list. You get their
value, your max bid, and the ladder of who can outbid you. Type the next name when the next
player comes up — you do not need to clear the last one.

If you type nothing, everything else still works. You lose the block view and nothing else.

---

## 4. When something looks wrong

Work down this table. The left column is what you see; the right is what to do.

| You see | Do |
|---|---|
| **`NOT LIVE`** | Nothing, for ~10s. It recovers by itself. If it persists, check the terminal — the connection error is named on the page. |
| **A team's money is wrong** | `corrections` → the team → what the room says they *actually* have. Stored as a difference, so the next pick will not undo it. |
| **A keeper never arrived** | `corrections` → team, player, price. Sleeper publishes no auction value, so retention prices are typed. Superseded automatically if the real pick shows up. |
| **A keeper counted as a bid** (or a bid as a keeper) | `corrections` → `pick … was really a …` → `recount it`. Moves no money; moves whether those dollars reach inflation and skew. |
| **A manager is missing / named wrong** | `seating` → slot → manager → `assign`. Lands on the next poll. |
| **`⚠ SUSPECT` beside a team** | A negative amount is in their ledger. Their spent, remaining and max bid are all downstream of a number that cannot happen. Do not bid against that figure. |
| **`PAYLOAD CONFLICT`** | Sleeper sent a row disagreeing with itself. The pick was kept; one of that team's figures may belong to another. Check the team against the room. |
| **A form wipes what you typed** | It will not. Every form sits below the live region for exactly this reason. If it happens, that is a bug — use the API directly. |
| **Everything is wrong** | `Ctrl-C`, `make cockpit` again. The ledger is a fold of the event log, not incremental state, so a restart rebuilds it exactly. You lose nothing. |

Every correction has an **undo** beside it in `corrections in force`. Nothing you type is
one-way.

---

## 5. The keeper backstop

Off by default. Turn it on with `make arm ON=1`, off with `ON=0`, check with `make arm`.

**Armed**, a pick by a team that still owes ceremonial keepers, which the manifest does not
recognise, is **flagged** rather than counted as a bid. Each flag is a question you answer under
`recount it`. Unanswered, that money stays out of inflation and skew — which is the safe
direction, but it is still a question.

**When to arm it:** if Burt and TD have still not joined by kickoff. Their four keepers cannot be
placed, so they will be read as competitive bids and quietly corrupt every threat read.

Measured, against the live league as it stands:

```
armed=False:  competitive=144   flagged=0     ← four phantom bids
armed=True:   competitive=140   flagged=4     ← four questions instead
```

Arming gets the count right even with two managers missing. It does not fix the league; it turns
a silent error into a visible one.

---

## 6. What not to trust

Stated plainly, because a tool that hides its limits is worse than one that has none.

- **The keeper prices are not your league's — and the report now says how they are wrong.**
  `config/keepers.yaml` carries **0 of 20** retention prices, so the tool fell back to what
  those players cost in the *mock* draft.

  Section 2 gives you **two scenarios**, and right now they disagree about the direction of the
  night:

  | scenario | keeper inflation | reads as |
  |---|---|---|
  | prices under the 75% rule | **1.0747x** | field clears ~7% **over** book |
  | prices as loaded (the mock's) | 0.9608x | field clears ~4% **under** book |

  **Read the rule row.** All twenty loaded prices sit above the rule — none scattered either
  side — averaging +$8.6, which works out at **109% of auction value rather than 75%**. Twenty
  out of twenty in the same direction is not twenty mispriced keepers; it means those figures
  are full auction values, not retention prices. The report states this in its second `!!`
  block.

  Filling in `price` and `price_source` in `config/keepers.yaml` settles it for certain — the
  manifest is consulted first and wins wherever it has a value. Twenty numbers, and the best
  twenty minutes available before Saturday.

- **Market values are the model's own** unless you supply `config/auction_values.csv`. The board
  marks estimates as `ESTIMATE`. They are internally consistent and not externally validated.
- **`draft.settings` disagrees with the league's roster positions** — 15 rounds vs 16, and no
  `max_keepers`. The roster positions win, and the page carries a red banner about it. This is
  the commissioner's re-save that never happened.
- **Walk-away curves are slow early and fast late,** because a curve prices you against the
  players still available. Measured on this machine, at realistic draft states:

  | picks landed | your open slots | precompute |
  |---:|---:|---:|
  | 20 | 14 | **183s** |
  | 60 | 10 | 62s |
  | 100 | 6 | 13s |
  | 140 | 2 | 1s |

  So for roughly the first forty picks the panel will say `computing`, and it means it. That is
  the cost ADR-0006 accepted and required to be stated on the page, not a hang. It never blocks
  a poll — the curves run in a worker thread and the live path is a dictionary lookup. **In the
  early rounds, price off the printed board.**
- **Nothing reads Sleeper's websocket.** No live nomination, no live bid, no clock. By design —
  the charter forbids reverse-engineering it, and this tool does not.
- **Every price is an opinion.** The tool's job is to make the room's money legible, not to bid
  for you.

---

## 7. If it all falls over

You have the printed board from `make prep`. It has every player, their tier, their value and
their walk-away price. That was the point of printing it.

The draft still happens. Bid from the paper.
