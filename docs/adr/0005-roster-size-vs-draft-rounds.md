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
draft_rounds: 16   # players each team BUYS at auction. Scales every price.
roster_size:  16   # total roster capacity. Anything above draft_rounds is waiver space.
```

`auction_pool = teams * draft_rounds` is the only one of the two that appears in the pricing
model. Roster capacity above `draft_rounds` is filled from waivers during the season; it costs
nothing at auction and must not be able to move a single price.

Severity follows from that, and the grading rule for the whole config file becomes a single
question — **does this field change what a player costs?**

| Field | Severity | Why |
|---|---|---|
| `starters.*`, `budget`, `teams` | BLOCKING | scale every price, unambiguous API source |
| `draft_rounds` | **conditional** | scales every price, but no unambiguous API source yet |
| `roster_size`, `bench` | WARNING | waiver capacity, no price effect |
| `draft.settings.*` staleness | WARNING | diagnosed in Finding 1 |
| `draft.start_time` drift | WARNING | changes the countdown, not the prices |

One roster-shape case still blocks: `roster_size < draft_rounds`. A team cannot seat every
player it drafts. When the contradiction is between two fields of our own config file it is
caught at load, not at validation — that is a typo in this repo, not a league that drifted, and
it should never reach the API comparison.

### `draft_rounds` is conditionally blocking, and why it cannot simply be blocking

The first draft of this ADR listed `draft_rounds` as BLOCKING in the table above and then said,
four paragraphs later, that it "cannot block against anything at boot." Both statements shipped.
The code implemented the second and the documentation advertised the first, which is the worst
of the available outcomes: a check that reads as a guarantee and is not one.

The difficulty is real. `draft_rounds` has two candidate API sources and neither is trustworthy
alone:

- `draft.settings.rounds` says 15 while this is a 16-round league (Finding 1). Blocking against
  it takes the tool down on draft night over a discrepancy already diagnosed.
- `len(roster_positions)` says 16 today, but the whole point of this ADR is that a roster may be
  larger than the draft. Once the two fields are decoupled, roster length stops being evidence
  about the draft at all.

So the severity turns on **whether the API agrees with itself**:

- `settings.rounds == len(roster_positions)` — two independent fields corroborate each other.
  That agreed value is authoritative and disagreeing with it **blocks**.
- they disagree — the API is internally inconsistent, which is the state today. Nothing is
  authoritative, so each mismatch warns and the tool boots.

This closes the case that mattered: a commissioner re-saves settings, the roster grows to 18 and
`rounds` becomes 18, the two agree, our configured 16 is wrong, and the tool now refuses to
price rather than shipping a board built on a 160-player pool against a 180-pick draft.

The check is deliberately two-sided. A `draft_rounds` too *large* is the more dangerous
direction and the one no downstream guard catches.

## Consequences

**A commissioner adding bench spots the night before the draft is now a banner, not an
outage.** Under the old field that scenario raised `ConfigMismatch` and the tool refused to
start — for a change that moves no number in the model. This was the single most likely
remaining way for the tool to be down at 7pm on draft day, and it is closed.

**The tripwire now runs on the pricing path, not only on `smoke`.** It previously fired nowhere
a person reading a priced board would see it, which made a blocking check that nothing blocked
on. `cli.value()` validates before it prices, and prints the auction pool, the budget and the
draft start above the board.

**Two compensating controls claimed by the first draft of this ADR were false**, and are struck
rather than quietly dropped:

- *"the ledger rejects a team exceeding its draftable spots, so a wrong `draft_rounds` surfaces
  within the first round of live picks"* — the ledger's cap fires on a team's **17th** pick,
  which is the end of the draft, and never fires at all when the configured figure exceeds
  reality. It is a one-sided check at the wrong end of the night.
- *"`make prep` prints the pool size at the top of the board"* — there is no `prep` target.
  DI-039 will add one. The pool size is now printed by `cli.value()`, which does exist.

Once DI-004 lands and the commissioner re-saves the draft settings, the two API fields agree and
`draft_rounds` becomes unconditionally blocking without any further change here.

**The 18-vs-16 question does not need resolving to proceed.** Whichever roster size is real,
the auction buys 160 players and no price moves. Flagged in `docs/api-findings.md` Finding 10
rather than silently resolved; `roster_size` tracks what the API says today and warns if that
changes.
