# ADR-0004: Optimizer objective includes a weighted bench term

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** quant-analyst, user

## Context

Charter §4.7b specifies maximising projected **starting lineup** points. The user has 14 picks
remaining for 8 starting slots and 6 bench slots. Under that objective bench players contribute
exactly zero, so the optimizer always recommends spending everything on starters and taking six $1
bench players — finishing the night at $0 with no injury cover and no bye-week depth.

That is roughly right in a shallow 10-team league, and badly wrong at the margin. It also makes the
roster completion planner structurally incapable of warning about depth.

## Decision

```
maximise  Σ(starting lineup points)  +  λ × Σ(bench VORP)
```

λ defaults to **0.2** and is exposed as a live slider in the cockpit (0.0–1.0), so the user can dial
bench weight to zero late in the draft when bench genuinely is worthless.

λ = 0 recovers the charter's literal objective exactly, making this a superset rather than a
deviation from intent.

## Consequences

Walk-away prices stop being systematically too aggressive. The user is no longer advised to end the
auction with exactly $0.

λ is a judgement coefficient, not a measurement. It must be badged as a model parameter in the UI,
and the walk-away display should make clear that moving the slider moves the number.

Obliges the DP and the CBC oracle (ADR-0003) to implement the same objective, λ included.
