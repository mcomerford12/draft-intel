# ADR-0002: Config validation is graded, not binary

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** architect, data-engineer

## Context

Charter §1 says: *"validate against the config file above and refuse to start with a loud, specific
error on any mismatch."*

Sprint 0 discovery found the live league already contradicts itself:

| Field | `league.roster_positions` | `draft.settings` |
|---|---|---|
| QB | 2 | 1 |
| DEF | 0 | 1 |
| BN | 6 | 5 |
| Total | 16 | 15 rounds |

Taken literally, the charter's rule means the tool refuses to start on the user's real league
*today*, and would refuse on draft night unless the commissioner fixes it in time.

`roster_positions` is authoritative: it is corroborated by `draft.metadata.scoring_type == "2qb"`
and by the settings of the user's own mock draft, which has `slots_qb: 2, slots_def: 0, rounds: 16`.

## Decision

Two severities.

- **BLOCKING** — `league.roster_positions` or `draft.settings.budget` disagreeing with
  `config/league.yaml`. Refuse to start, naming the field and both values.
- **WARNING** — `draft.settings` slot counts, rounds, or `league.settings.max_keepers` disagreeing
  with `roster_positions`. Boot, and show a persistent banner.

## Consequences

The tripwire still does its real job: a commissioner changing QB slots or the budget the night
before is caught and blocks startup. Tested by `test_a_changed_roster_setting_refuses_to_start`.

The known discrepancy is loud but non-fatal. Bricking on draft night over something already
diagnosed would be the worse failure — the charter's own prime directive is that reliability
outranks everything.

We are obliged to keep DI-004 open until the commissioner re-saves, and to make the banner
prominent enough that the user does not tune it out.
