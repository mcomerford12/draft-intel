# ADR-0005: Roster size and draft rounds are separate fields

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** architect, quant-analyst, user

## Context

`config/league.yaml` carried a single field, `total_slots: 16`, which was doing three jobs at
once:

1. the boot tripwire against `len(league.roster_positions)`,
2. the multiplier behind the priced pool, `teams * total_slots == 160`,
3. the per-team slot cap the ledger enforces and the max-bid reserve depends on.

That worked only because of a coincidence: this league happens to draft every roster spot it
has. The commissioner then reported the roster as **18 positions with 16 draft rounds**, while
the API reports 16 positions (10 starters + 6 BN, no IR, no taxi) and the mock drafted 16
rounds. Under one field, the two readings are in direct conflict and there is no way to hold
both.

They are not actually in conflict, because they are answers to different questions.

## Decision

Split the field.

```yaml
draft_rounds: 16   # players each team BUYS at auction. Scales every price. BLOCKING.
roster_size:  16   # total roster capacity. Anything above draft_rounds is waiver space.
```

`auction_pool = teams * draft_rounds` is the only one of the two that appears in the pricing
model. Roster capacity above `draft_rounds` is filled from waivers during the season; it costs
nothing at auction and must not be able to move a single price.

Severity follows from that, and the grading rule for the whole config file becomes a single
question — **does this field change what a player costs?**

| Field | Severity | Why |
|---|---|---|
| `starters.*`, `budget`, `teams`, `draft_rounds` | BLOCKING | scale every price |
| `roster_size`, `bench` | WARNING | waiver capacity, no price effect |
| `draft.settings.*` staleness | WARNING | diagnosed in Finding 1 |
| `draft.start_time` drift | WARNING | changes the countdown, not the prices |

One roster-shape case still blocks: `roster_size < draft_rounds`. A team cannot seat every
player it drafts. When the contradiction is between two fields of our own config file it is
caught at load, not at validation — that is a typo in this repo, not a league that drifted, and
it should never reach the API comparison.

## Consequences

**A commissioner adding bench spots the night before the draft is now a banner, not an
outage.** Under the old field that scenario raised `ConfigMismatch` and the tool refused to
start — for a change that moves no number in the model. This was the single most likely
remaining way for the tool to be down at 7pm on draft day, and it is closed.

**`draft_rounds` has no authoritative API source today.** `draft.settings.rounds` says 15 and
is known stale (Finding 1); `len(roster_positions)` is *not* corroboration once the two are
decoupled, since a roster is allowed to be larger than the draft. So `draft_rounds` cannot
block against anything at boot, which is uncomfortable for a field that scales every price.
Two things cover it:

- the ledger already rejects a team exceeding its draftable spots, so a wrong `draft_rounds`
  surfaces as rejects within the first round of live picks rather than silently;
- `make prep` prints the pool size at the top of the board, where a human sees it before
  trusting a single price.

Once DI-004 lands and the commissioner re-saves the draft settings, `draft.settings.rounds`
becomes authoritative and this gap closes on its own.

**The 18-vs-16 question does not need resolving to proceed.** Whichever roster size is real,
the auction buys 160 players and no price moves. Flagged in `docs/api-findings.md` Finding 10
rather than silently resolved; `roster_size` tracks what the API says today and warns if that
changes.
