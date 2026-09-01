# draft-intel

Draft intelligence for a 10-team, $200, full-PPR **2QB** Sleeper **auction** with
2 keepers per team retained at `floor(0.75 × sleeper auction value)`.

**Draft day: Thursday, September 4, 2026.**

## Status

Pre-implementation. This repo currently holds the charter and the refined build plan.

| Document | What it is |
|---|---|
| `docs/CHARTER.md` | The original charter as supplied. Source of truth for **scope**. |
| `docs/PLAN.md` | Refined context and build plan. Source of truth for **how**. Resolves four contradictions in the charter and corrects three technical impossibilities. |
| `docs/DECISIONS_FOR_REVIEW.md` | Open rulings and decisions taken, per charter §11. |
| `config/keepers.yaml` | The keeper manifest. Expected state, **never** ledger truth. |
| `config/keepers.original.yaml` | The manifest as originally supplied, kept for diffing. |
| `docs/KANBAN.md` | Board state, per charter §7. Single source of truth for what is done. |
| `docs/adr/` | Architecture decisions, including every deviation from the charter. |
| `docs/api-findings.md` | Sprint 0 discovery: 9 findings against the live 2026 API. |
| `.claude/agents/` | Subagent roster per charter §6, with independence rules. |

## Read the plan first

`docs/PLAN.md` is not a restatement of the charter. It changes things the charter got
wrong, and those changes affect every price the model produces. In particular:

- **Keeper prices are observed, not derived.** The charter defined them three
  incompatible ways. `ΣK_t` scales every live price, so this mattered.
- **The pre-draft board is an estimate.** Prices arrive on draft morning, so the
  charter's "freeze the model days early" premise does not hold.
- **`keeper_inflation` and `market_inflation` are different numbers.** The charter
  used one word for both.
- **The live optimizer is a DP, not an ILP.** The charter demanded PuLP *and*
  sub-200ms; CBC's subprocess overhead makes those mutually exclusive.

## Ground rules carried over from the charter

- Never hardcode player names, teams, rankings, or tiers outside `config/keepers.yaml`
  and clearly-labelled test fixtures.
- Never hardcode league settings — derive from the API at boot and fail loudly on any
  mismatch against the charter's §1 tripwire table.
- Never reverse-engineer or connect to Sleeper's internal websocket.
- Poll no faster than 1s.
- Derived state is always `f(api_events + override_events)` — append-only, never mutated.
