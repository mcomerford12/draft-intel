"""DI-029 — the four replacement baselines of ADR-0001.

Charter §4.2 defines two baselines; §4.3 defines two valuations on a *different* axis and
never pairs them. Four exist. ADR-0001 pins the mapping:

===========================  ==================  =========================================
baseline                     universe            feeds
===========================  ==================  =========================================
``full.starter``             all 160             diagnostics only
``full.last_drafted``        all 160             ``VORP`` -> ``market_value``
``live.starter``             post-keeper 140     scarcity counters, QB pressure panel
``live.last_drafted``        post-keeper 140     ``VORP_live`` -> ``baseline_value``
===========================  ==================  =========================================

Pricing uses the **last-drafted** baselines, per §4.2: bench players cost real money, so the
relevant replacement is the last player actually rostered, not the last starter.

**How last-drafted demand is derived.** The charter sketches expected roster counts ("QB:
~24-28 rostered in total, minus 7 kept") and then says to derive demand from the actual pool
rather than assume it. Hardcoding 26 QBs would bake a guess into every price, so instead this
solves for a fixed point:

1. Seat the mandatory starting slots -- every team must field a legal lineup.
2. Allocate the remaining bench spots to whoever has the most value over the *current*
   replacement estimate.
3. Recompute replacement from that roster and repeat until it stops moving.

Positions with genuine depth earn bench spots; positions without do not. In a 2QB league the
fixed point pulls QB demand up on its own, which is exactly the structural effect §4.2 says
the model must reproduce rather than be told about.

Kickers are pinned to exactly one per team. Nobody rosters a backup kicker, and letting a
VORP-driven allocator decide would either starve the position or hoard it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from draft_intel.quant.scoring import PlayerProjection
from draft_intel.quant.slots import FLEX_ELIGIBLE, SlotDemand

MAX_ITERATIONS = 50


class Baseline(BaseModel):
    """Replacement points per position, plus the roster that produced them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    points: dict[str, float]
    rostered: dict[str, int]
    pool_size: int

    def vorp(self, projection: PlayerProjection) -> float:
        """Value over replacement, floored at zero per charter §4.3."""
        return max(0.0, projection.points - self.points.get(projection.position, 0.0))


def _by_position(
    players: Iterable[PlayerProjection],
) -> dict[str, list[PlayerProjection]]:
    out: dict[str, list[PlayerProjection]] = {}
    for player in players:
        out.setdefault(player.position, []).append(player)
    for group in out.values():
        group.sort(key=lambda p: p.points, reverse=True)
    return out


def starter_baseline(
    players: Sequence[PlayerProjection],
    *,
    base_slots: Mapping[str, int],
    flex_slots: int,
) -> Baseline:
    """Fill starting slots greedily, then read replacement off the last starter.

    Base slots first by position, then FLEX from the best remaining RB/WR/TE regardless of
    position. Charter §4.2: "Record the resulting RB/WR/TE flex split - do not assume a split,
    derive it."
    """
    pool = _by_position(players)
    taken: dict[str, int] = {}

    for position, count in base_slots.items():
        taken[position] = min(count, len(pool.get(position, [])))

    flex_candidates = sorted(
        (
            player
            for position in FLEX_ELIGIBLE
            for player in pool.get(position, [])[taken.get(position, 0) :]
        ),
        key=lambda p: p.points,
        reverse=True,
    )[:flex_slots]
    for player in flex_candidates:
        taken[player.position] = taken.get(player.position, 0) + 1

    return Baseline(
        points={
            position: pool[position][count - 1].points
            for position, count in taken.items()
            if count > 0 and position in pool
        },
        rostered=taken,
        pool_size=sum(taken.values()),
    )


def last_drafted_baseline(
    players: Sequence[PlayerProjection],
    *,
    base_slots: Mapping[str, int],
    flex_slots: int,
    roster_spots: int,
    pinned: Mapping[str, int] | None = None,
) -> Baseline:
    """Solve for the replacement level implied by filling every roster spot.

    Args:
        roster_spots: Total players rostered league-wide in this universe (160 full, 140 live).
        pinned: Positions whose rostered count is fixed regardless of value, e.g. ``{"K": 10}``.

    Iterates to a fixed point. Converges in a handful of passes; the iteration cap exists so a
    pathological input cannot spin forever rather than because convergence is in doubt.
    """
    pool = _by_position(players)
    pinned = dict(pinned or {})

    # Seed from the mandatory starting slots: every team must field a legal lineup, so these
    # are demanded whatever the value curve says.
    seed = starter_baseline(players, base_slots=base_slots, flex_slots=flex_slots)
    taken = dict(seed.rostered)
    for position, count in pinned.items():
        taken[position] = min(count, len(pool.get(position, [])))

    def replacement_from(counts: Mapping[str, int]) -> dict[str, float]:
        return {
            position: pool[position][count - 1].points
            for position, count in counts.items()
            if count > 0 and position in pool
        }

    previous: dict[str, float] = {}
    for _ in range(MAX_ITERATIONS):
        points = replacement_from(taken)
        if points == previous:
            break
        previous = points

        counts = dict(taken)
        for position in pinned:
            counts[position] = taken[position]

        # Hand out the remaining bench spots to whoever gains most over the current
        # replacement estimate. Pinned positions are excluded from the contest.
        remaining = roster_spots - sum(counts.values())
        candidates = sorted(
            (
                (player.points - points.get(player.position, 0.0), player)
                for position, group in pool.items()
                if position not in pinned
                for player in group[counts.get(position, 0) :]
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )[: max(0, remaining)]
        for _gain, player in candidates:
            counts[player.position] = counts.get(player.position, 0) + 1
        taken = counts

    return Baseline(points=replacement_from(taken), rostered=taken, pool_size=sum(taken.values()))


class Baselines(BaseModel):
    """All four baselines of ADR-0001, computed together so they cannot drift apart."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    full_starter: Baseline
    full_last_drafted: Baseline
    live_starter: Baseline
    live_last_drafted: Baseline


def compute_baselines(
    players: Sequence[PlayerProjection],
    *,
    keeper_ids: frozenset[str],
    demand: SlotDemand,
    roster_spots_full: int,
    roster_spots_live: int,
    kicker_slots: int,
) -> Baselines:
    """Compute all four baselines, adjusting supply and demand together for the live pair.

    The live universe removes the keepers from **supply** (they are gone from ``available``)
    and from **demand** (``demand.remaining_base`` / ``remaining_flex``). Doing one without the
    other is the error §4.2 singles out.
    """
    available = [p for p in players if p.player_id not in keeper_ids]

    return Baselines(
        full_starter=starter_baseline(players, base_slots=demand.base, flex_slots=demand.flex),
        full_last_drafted=last_drafted_baseline(
            players,
            base_slots=demand.base,
            flex_slots=demand.flex,
            roster_spots=roster_spots_full,
            pinned={"K": kicker_slots},
        ),
        live_starter=starter_baseline(
            available, base_slots=demand.remaining_base, flex_slots=demand.remaining_flex
        ),
        live_last_drafted=last_drafted_baseline(
            available,
            base_slots=demand.remaining_base,
            flex_slots=demand.remaining_flex,
            roster_spots=roster_spots_live,
            pinned={"K": kicker_slots - demand.keeper_base.get("K", 0)},
        ),
    )
