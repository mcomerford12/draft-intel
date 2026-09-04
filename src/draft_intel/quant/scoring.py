"""DI-026 — projections scored under the league's own settings.

Charter §4.1: do not trust a pre-scored ``pts_ppr`` field blindly. Pull raw stat projections
and apply the league's own ``scoring_settings``, so any scoring quirk (TE premium, first-down
bonuses, non-standard kicker scoring) is handled correctly rather than assumed away.

That is done here, with one honest exception discovered by measurement rather than assumed.

**Kickers cannot be scored from the raw projections in this league.** The league scores field
goals by distance bucket -- ``fgm_0_19`` through ``fgm_60p`` -- but Sleeper only projects
``fgm_40_49`` and ``fgm_50p``. Every field goal under 40 yards is unprojected, so the raw path
silently undercounts kickers: measured across 37 kickers, the median divergence from Sleeper's
own PPR figure is 29.8% and the worst is 83.3%, versus **0.0%** for QB, RB, WR and TE.

Rather than hardcode "kickers are special", the fallback is calibrated per position against
Sleeper's own figure. A position whose median divergence exceeds the charter's 5% bug-signal
threshold is scored from ``pts_ppr`` instead, and every player carries a ``projection_source``
recording which path produced their number.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

# Charter §4.1: "log any player where the computed score and Sleeper's own PPR figure diverge
# by more than 5% - that divergence is a bug signal."
DIVERGENCE_THRESHOLD_PCT = 5.0

# Keys that are not stats: ADP variants and Sleeper's own pre-scored totals.
_NON_STAT_PREFIXES = ("adp", "pts_")


class ProjectionSource(StrEnum):
    COMPUTED = "computed_from_stats"
    SLEEPER_PPR = "sleeper_pts_ppr"


class PlayerProjection(BaseModel):
    """One player's projected points under this league's scoring."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    player_id: str
    name: str
    position: str
    team: str | None = None
    points: float
    projection_source: ProjectionSource
    computed_points: float
    sleeper_ppr: float | None = None
    divergence_pct: float | None = None

    @property
    def diverged(self) -> bool:
        return (self.divergence_pct or 0.0) > DIVERGENCE_THRESHOLD_PCT


def score_stats(stats: Mapping[str, Any], scoring: Mapping[str, float]) -> float:
    """Apply the league's scoring settings to one player's raw stat line.

    Ignores ADP and pre-scored totals, and any stat the league does not score. Non-numeric
    values are skipped rather than raising -- an unexpected type in a projection feed must not
    take the pipeline down.
    """
    total = 0.0
    for key, value in stats.items():
        if key.startswith(_NON_STAT_PREFIXES):
            continue
        weight = scoring.get(key)
        if not weight or not isinstance(value, int | float) or isinstance(value, bool):
            continue
        total += weight * value
    return total


def _divergence_pct(computed: float, reference: float | None) -> float | None:
    if reference is None or reference <= 0:
        return None
    return abs(computed - reference) / reference * 100.0


def unreliable_positions(
    payload: Iterable[Mapping[str, Any]],
    scoring: Mapping[str, float],
    *,
    threshold: float = DIVERGENCE_THRESHOLD_PCT,
    min_points: float = 20.0,
) -> dict[str, float]:
    """Positions where scoring from raw stats does not reproduce Sleeper's own figure.

    Returns ``{position: median divergence %}`` for positions above ``threshold``. Calibrating
    per position rather than per player matters: a single player can diverge for a benign
    reason (a two-way player with return stats), but a whole position diverging means the
    league scores something the projections do not carry, and the raw path is structurally
    incomplete there.

    Players below ``min_points`` are excluded because percentage divergence on a near-zero
    projection is noise.
    """
    by_position: dict[str, list[float]] = {}
    for record in payload:
        stats = record.get("stats") or {}
        player = record.get("player") or {}
        position = player.get("position")
        reference = stats.get("pts_ppr")
        if not position or reference is None or reference < min_points:
            continue
        pct = _divergence_pct(score_stats(stats, scoring), reference)
        if pct is not None:
            by_position.setdefault(position, []).append(pct)
    return {
        position: statistics.median(values)
        for position, values in by_position.items()
        if statistics.median(values) > threshold
    }


def build_projections(
    payload: Iterable[Mapping[str, Any]],
    scoring: Mapping[str, float],
    *,
    positions: Iterable[str] = ("QB", "RB", "WR", "TE", "K"),
) -> tuple[list[PlayerProjection], dict[str, float]]:
    """Score every projection, returning ``(projections, unreliable_positions)``.

    A position in the returned mapping was scored from ``pts_ppr`` rather than from raw stats,
    with the median divergence that triggered the fallback. Callers should surface it: it is a
    real limitation of the inputs, not a detail.
    """
    records = list(payload)
    wanted = set(positions)
    fallback = unreliable_positions(records, scoring)

    out: list[PlayerProjection] = []
    for record in records:
        player = record.get("player") or {}
        position = player.get("position")
        player_id = record.get("player_id")
        if position not in wanted or not player_id:
            continue
        stats = record.get("stats") or {}
        computed = score_stats(stats, scoring)
        reference = stats.get("pts_ppr")

        if position in fallback:
            points, source = (
                (float(reference), ProjectionSource.SLEEPER_PPR)
                if reference is not None
                else (computed, ProjectionSource.COMPUTED)
            )
        else:
            points, source = computed, ProjectionSource.COMPUTED

        out.append(
            PlayerProjection(
                player_id=str(player_id),
                name=f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                position=position,
                team=record.get("team") or player.get("team"),
                points=round(points, 2),
                projection_source=source,
                computed_points=round(computed, 2),
                sleeper_ppr=float(reference) if reference is not None else None,
                divergence_pct=_divergence_pct(computed, reference),
            )
        )
    out.sort(key=lambda p: p.points, reverse=True)
    return out, fallback
