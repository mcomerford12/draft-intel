"""DI-039 — tier breaks, derived from the priced board rather than declared.

Charter §4.9 item 5 wants a tier sheet: *"Tier breaks per position with the price gap across each
break — the thing to actually print and put on the desk."*

The §1 CRITICAL DATA RULE forbids hardcoded tiers outright, and rightly: a tier list typed in
August is a snapshot of somebody's opinion, and it goes stale the moment a depth chart moves. So
tiers here are **found**, not assigned. Within a position, players are ordered by live auction
value and a break is declared wherever the drop to the next player is large relative to the drops
around it.

**The threshold is relative, not a dollar figure.** A $4 gap is a chasm among $8 tight ends and
noise among $40 running backs, so a fixed cutoff would carve one position into slivers and
declare the other a single tier. The rule used is a multiple of the *median* gap at that
position: robust to the one enormous gap at the top, which a mean is not.

What the sheet is actually for: the last player above a break is worth paying up for, because
the next one down is a real step worse. That is the only decision a tier sheet supports, so the
gap across each break is the number carried, not the tier's membership count.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

BREAK_MULTIPLE = 2.5
"""A gap this many times the position's median gap is a tier break."""

MIN_TIER_SAMPLE = 6
"""Below this many players a position has no gap distribution worth measuring against."""


class Tier(BaseModel):
    """One tier at one position."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: str
    number: int
    players: tuple[tuple[str, str, float], ...]
    """``(player_id, name, live value)``, best first."""

    gap_below: float
    """Dollars between this tier's cheapest player and the next tier's best. 0.0 for the last."""

    @property
    def size(self) -> int:
        return len(self.players)

    @property
    def top_value(self) -> float:
        return self.players[0][2] if self.players else 0.0

    @property
    def bottom_value(self) -> float:
        return self.players[-1][2] if self.players else 0.0


def tier_sheet(
    players: Sequence[tuple[str, str, str, float]],
    *,
    break_multiple: float = BREAK_MULTIPLE,
    min_sample: int = MIN_TIER_SAMPLE,
) -> dict[str, list[Tier]]:
    """Find tier breaks per position.

    Args:
        players: ``(player_id, name, position, live value)`` for the available board.
        break_multiple: Multiple of the position's median gap that constitutes a break.
        min_sample: Players needed at a position before breaks are looked for. Below it the
            whole position is one tier, which is the honest answer -- with four players there
            is no gap distribution to call anything unusual against.

    Positions with fewer than ``min_sample`` players come back as a single tier rather than
    being omitted, because a kicker list is still a list the user reads.
    """
    by_position: dict[str, list[tuple[str, str, float]]] = {}
    for player_id, name, position, value in players:
        by_position.setdefault(position, []).append((player_id, name, value))

    sheet: dict[str, list[Tier]] = {}
    for position, group in sorted(by_position.items()):
        group.sort(key=lambda row: -row[2])
        sheet[position] = _split(position, group, break_multiple, min_sample)
    return sheet


def _split(
    position: str,
    group: Sequence[tuple[str, str, float]],
    break_multiple: float,
    min_sample: int,
) -> list[Tier]:
    gaps = [group[i][2] - group[i + 1][2] for i in range(len(group) - 1)]
    positive = [gap for gap in gaps if gap > 0]

    if len(group) < min_sample or not positive:
        return [Tier(position=position, number=1, players=tuple(group), gap_below=0.0)]

    # Median, not mean: the gap below the best player at a position is routinely several times
    # every other gap, and a mean drags the threshold up until nothing else qualifies.
    threshold = statistics.median(positive) * break_multiple

    tiers: list[Tier] = []
    current: list[tuple[str, str, float]] = [group[0]]
    for index in range(1, len(group)):
        gap = group[index - 1][2] - group[index][2]
        if gap >= threshold:
            tiers.append(
                Tier(
                    position=position,
                    number=len(tiers) + 1,
                    players=tuple(current),
                    gap_below=round(gap, 2),
                )
            )
            current = []
        current.append(group[index])
    tiers.append(
        Tier(position=position, number=len(tiers) + 1, players=tuple(current), gap_below=0.0)
    )
    return tiers
