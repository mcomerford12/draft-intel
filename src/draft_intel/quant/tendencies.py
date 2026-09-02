"""DI-037 — manager tendency profiles, keyed on ``competitive_seq``.

Charter §4.6 asks for a profile per manager:

* positional bias — where their money goes relative to value;
* early vs late aggression — skew regressed on pick number;
* reaction to runs — does this manager chase;
* stars-and-scrubs vs balanced — the Gini coefficient of their roster spend;
* nomination behaviour — do they nominate their own targets.

Four of the five are computable from the picks feed and are here. **Nomination behaviour is
not**, and is reported as unavailable rather than approximated: Sleeper's picks endpoint records
who *won* each player, never who put them up. There is no field for it anywhere in the payload,
so any figure this module produced for it would be invented. See :attr:`Profile.unavailable`.

----

**"Skew regressed on pick number" is regressed on ``competitive_seq``, not ``pick_no``.**

This is ADR-0001's D3 and it is load-bearing here specifically. In Case B the twenty ceremonial
keeper picks occupy ``pick_no`` 1-20 and shift every competitive pick's number by 20. A slope
fitted against ``pick_no`` is therefore a different slope in Case A and Case B, and the blocking
equivalence gate — *"every derived output ... including tendency profiles ... must be
bit-identical"* — cannot pass. Fitting against the dense competitive index makes it identical by
construction.

``competitive_seq`` is recomputed on every fold and never persisted; a profile is recomputed
wholesale alongside it.

----

**Every figure reports its sample size, and refuses below a floor.** A manager's "tendency" from
two picks is not a tendency, and a slope fitted to three points is noise with a direction. The
charter's own framing — *"is this a real threat or a manager about to get priced out"* — is a
decision the user makes with money, so a profile that reads confidently off four picks is worse
than one that says it does not know yet.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from draft_intel.quant.skew import PickSkew, SkewBoard

MIN_PROFILE_PICKS = 5
"""Below this, a manager has a history rather than a tendency, and nothing is reported."""

MIN_SLOPE_PICKS = 6
"""A slope needs more than a ratio does: two points always fit a line perfectly."""

RUN_LENGTH = 3
"""Consecutive picks at one position that constitute a run, for the chase measurement."""


class PositionalBias(BaseModel):
    """Where one manager's money went at one position, against what the model said."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: str
    picks: int
    spent: int
    share_of_spend: float
    """Fraction of this manager's total spend that went here."""

    mean_edge_skew: float


class Profile(BaseModel):
    """One manager's demonstrated behaviour tonight."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slot: int
    owner: str
    picks: int
    spent: int

    positional_bias: tuple[PositionalBias, ...]

    aggression_slope: float | None
    """Dollars of edge skew per competitive pick. Positive means they heat up as the draft runs.

    ``None`` below :data:`MIN_SLOPE_PICKS`, or when every pick landed at the same point in the
    sequence and the slope is undefined rather than zero.
    """

    early_mean_skew: float | None
    late_mean_skew: float | None
    """The same question asked without a model: the first and second halves of their picks.

    Carried alongside the slope because a slope is a single number that hides its own shape, and
    two means are harder to misread. When they disagree with the slope's sign, the manager's
    behaviour is not linear and neither figure should be leaned on.
    """

    gini: float | None
    """Concentration of roster spend. 0 is perfectly even, approaching 1 is stars-and-scrubs."""

    chases_runs: float | None
    """Mean edge skew on picks made *during* a positional run, minus their overall mean.

    Positive means this manager pays more when a run is on -- they chase. ``None`` when they
    made no picks during a run, which is not the same as not chasing.
    """

    run_picks: int
    unavailable: tuple[str, ...] = ()
    """Charter-requested figures that the data cannot support. Named, never approximated."""

    @property
    def is_reportable(self) -> bool:
        return self.picks >= MIN_PROFILE_PICKS

    def describe(self) -> list[str]:
        if not self.is_reportable:
            return [f"{self.owner}: {self.picks} pick(s), too few to profile"]
        lines = [f"{self.owner}: {self.picks} picks, ${self.spent} spent"]
        if self.gini is not None:
            shape = "stars-and-scrubs" if self.gini > 0.45 else "balanced"
            lines.append(f"  spend shape: {shape} (Gini {self.gini:.2f})")
        if self.aggression_slope is not None:
            direction = "heats up" if self.aggression_slope > 0 else "cools off"
            lines.append(f"  {direction} as the draft runs ({self.aggression_slope:+.2f}/pick)")
        if self.chases_runs is not None:
            verb = "chases" if self.chases_runs > 0 else "sits out"
            lines.append(
                f"  {verb} positional runs ({self.chases_runs:+.1f} vs their own average, "
                f"{self.run_picks} pick(s) during runs)"
            )
        for position in sorted(self.positional_bias, key=lambda b: -b.share_of_spend)[:2]:
            lines.append(
                f"  {position.position}: {position.share_of_spend:.0%} of spend, "
                f"{position.mean_edge_skew:+.1f}/pick vs model"
            )
        for missing in self.unavailable:
            lines.append(f"  (not measurable: {missing})")
        return lines


def _gini(amounts: Sequence[int]) -> float | None:
    """Concentration of spend. 0 is perfectly even; approaching 1 is one player and scraps.

    Undefined on an empty roster or an all-zero one, and ``None`` says so rather than 0.0 --
    which would read as "perfectly balanced", the opposite of "no information".
    """
    values = sorted(amounts)
    total = sum(values)
    if not values or total <= 0:
        return None
    n = len(values)
    weighted = sum((index + 1) * value for index, value in enumerate(values))
    return round((2 * weighted) / (n * total) - (n + 1) / n, 4)


def _slope(points: Sequence[tuple[int, float]]) -> float | None:
    """Least-squares slope of ``y`` on ``x``, or ``None`` when it is undefined.

    Undefined when every ``x`` is identical: the fit has no direction to report, and returning
    0.0 would claim the manager's behaviour is flat when in fact it was never observed changing.
    """
    if len(points) < 2:
        return None
    xs = [float(x) for x, _y in points]
    ys = [y for _x, y in points]
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return round(numerator / denominator, 4)


def _runs(picks: Sequence[PickSkew], length: int) -> set[int]:
    """``competitive_seq`` values that fall inside a run of ``length`` picks at one position.

    A run is measured across the whole room, not per manager: the thing a manager reacts to is
    the room taking four running backs in a row, whoever took them.
    """
    ordered = sorted(picks, key=lambda p: p.competitive_seq)
    inside: set[int] = set()
    for index in range(len(ordered) - length + 1):
        window = ordered[index : index + length]
        if len({pick.position for pick in window}) == 1:
            inside.update(pick.competitive_seq for pick in window)
    return inside


def profiles(
    skew: SkewBoard,
    *,
    owners: Mapping[int, str] | None = None,
    min_picks: int = MIN_PROFILE_PICKS,
    min_slope_picks: int = MIN_SLOPE_PICKS,
    run_length: int = RUN_LENGTH,
) -> dict[int, Profile]:
    """Build a profile per draft slot from tonight's skew board.

    Keyed on ``draft_slot``, never on owner name: names may be unresolved -- six managers have
    not joined the league -- and two teams can share a fallback label, while the slot is always
    present and always unique.

    Args:
        skew: The skew board, which has already filtered to ``COMPETITIVE`` picks.
        owners: ``draft_slot -> owner name``, for display only.
        min_picks: Picks below which nothing is reported for a manager.
        min_slope_picks: Picks below which the aggression slope is withheld.
        run_length: Consecutive same-position picks that constitute a run.
    """
    names = dict(owners or {})
    run_seqs = _runs(skew.picks, run_length)

    by_slot: dict[int, list[PickSkew]] = {}
    for pick in skew.picks:
        if pick.slot is not None:
            by_slot.setdefault(pick.slot, []).append(pick)

    out: dict[int, Profile] = {}
    for slot, picks in sorted(by_slot.items()):
        picks = sorted(picks, key=lambda p: p.competitive_seq)
        spent = sum(pick.price_paid for pick in picks)
        overall = statistics.fmean([pick.edge_skew for pick in picks]) if picks else 0.0

        bias: list[PositionalBias] = []
        by_position: dict[str, list[PickSkew]] = {}
        for pick in picks:
            by_position.setdefault(pick.position, []).append(pick)
        for position, group in sorted(by_position.items()):
            position_spend = sum(pick.price_paid for pick in group)
            bias.append(
                PositionalBias(
                    position=position,
                    picks=len(group),
                    spent=position_spend,
                    share_of_spend=round(position_spend / spent, 4) if spent else 0.0,
                    mean_edge_skew=round(statistics.fmean([pick.edge_skew for pick in group]), 2),
                )
            )

        during_runs = [pick for pick in picks if pick.competitive_seq in run_seqs]
        half = len(picks) // 2
        reportable = len(picks) >= min_picks

        out[slot] = Profile(
            slot=slot,
            owner=names.get(slot) or f"slot {slot}",
            picks=len(picks),
            spent=spent,
            positional_bias=tuple(bias) if reportable else (),
            aggression_slope=(
                _slope([(pick.competitive_seq, pick.edge_skew) for pick in picks])
                if len(picks) >= min_slope_picks
                else None
            ),
            early_mean_skew=(
                round(statistics.fmean([p.edge_skew for p in picks[:half]]), 2)
                if reportable and half
                else None
            ),
            late_mean_skew=(
                round(statistics.fmean([p.edge_skew for p in picks[half:]]), 2)
                if reportable and half
                else None
            ),
            gini=_gini([pick.price_paid for pick in picks]) if reportable else None,
            chases_runs=(
                round(statistics.fmean([p.edge_skew for p in during_runs]) - overall, 2)
                if reportable and during_runs
                else None
            ),
            run_picks=len(during_runs),
            unavailable=(
                (
                    "nomination behaviour: Sleeper's picks feed records who WON each player, "
                    "never who nominated them, and no field anywhere in the payload carries it",
                )
                if reportable
                else ()
            ),
        )
    return out
