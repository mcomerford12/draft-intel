"""DI-033 — skew, the headline metric.

Charter §4.6 defines two measures and is explicit that they must be labelled unambiguously and
never merged:

============  ==============================================  =================================
metric        formula                                         meaning
============  ==============================================  =================================
Market skew   ``price_paid - market_value``                    did the room overpay vs consensus
Edge skew     ``price_paid - our_inflation_adjusted_value``    did the room overpay vs *our* model
============  ==============================================  =================================

**They differ only because the two values come from different places**, and that is the whole
point. ``market_value`` here is the *consensus* number from :mod:`draft_intel.quant.market` --
what the room will pay -- not our own ``PlayerValue.market_value``, which is a model output.
Using ours on both sides makes market skew and edge skew the same quantity computed twice, and
the difference between them is the only thing that says whether *we* disagree with the room or
the room disagrees with itself.

That has a consequence worth stating plainly rather than burying: **until real auction values
arrive, market skew is weakly informative.** The fallback providers borrow our own price ladder,
so the two skews converge by construction. :attr:`PickSkew.market_value_is_estimate` carries
that per pick and :meth:`SkewBoard.caveats` says it out loud.

**Each pick is judged against the inflation the room actually faced when bidding on it**, not
against the final figure. A pick measured against the state it helped create is measured partly
against its own effect, which flatters an overpay and penalises a bargain. See
:class:`draft_intel.quant.inflation.InflationStep`.

Every input is filtered to ``COMPETITIVE`` picks, per §2: the ceremonial keeper picks were never
competitive bids and treating them as auction results poisons skew silently.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from draft_intel.models import DerivedState
from draft_intel.quant.inflation import walk_inflation
from draft_intel.quant.market import MarketValues
from draft_intel.quant.valuation import PlayerValue

# A skew percentage on a near-zero value is not a large percentage, it is a division artefact:
# $2 paid for a player valued at $0.10 is +1900%, which tells nobody anything. Below this the
# percentage is withheld and the dollar figure stands alone.
MIN_VALUE_FOR_PCT = 1.0


class PickSkew(BaseModel):
    """One competitive pick, measured both ways."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    competitive_seq: int
    player_id: str
    name: str
    position: str
    slot: int | None
    price_paid: int

    market_value: float | None
    """Consensus, from the market provider. ``None`` when no source covers this player."""

    market_value_is_estimate: bool
    """True when the consensus figure came from a fallback rather than real auction dollars."""

    adjusted_value: float
    """Our ``baseline_value`` scaled by the inflation the room faced *before* this pick."""

    inflation_at_pick: float

    @property
    def market_skew(self) -> float | None:
        """``paid - consensus``. Positive means the room paid over consensus."""
        if self.market_value is None:
            return None
        return round(self.price_paid - self.market_value, 2)

    @property
    def edge_skew(self) -> float:
        """``paid - our inflation-adjusted value``. Positive means the room paid over our model."""
        return round(self.price_paid - self.adjusted_value, 2)

    @property
    def market_skew_pct(self) -> float | None:
        if self.market_value is None or self.market_value < MIN_VALUE_FOR_PCT:
            return None
        return round((self.price_paid - self.market_value) / self.market_value * 100, 1)

    @property
    def edge_skew_pct(self) -> float | None:
        if self.adjusted_value < MIN_VALUE_FOR_PCT:
            return None
        return round((self.price_paid - self.adjusted_value) / self.adjusted_value * 100, 1)


class SkewAggregate(BaseModel):
    """Skew rolled up over a set of picks: a team, a position, or the whole room."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    picks: int
    spent: int
    projected_points: float

    total_edge_skew: float
    mean_edge_skew: float
    stdev_edge_skew: float | None
    """``None`` for a single pick. One observation has no spread, and reporting 0.0 would read
    as a disciplined bidder rather than as an absence of evidence."""

    total_market_skew: float | None
    mean_market_skew: float | None
    market_priced: int
    """Picks in this group that had a consensus value. The others contribute to neither."""

    @property
    def dollars_per_projected_point(self) -> float | None:
        """Charter §4.6's per-team efficiency figure. ``None`` when nothing was projected."""
        if self.projected_points <= 0:
            return None
        return round(self.spent / self.projected_points, 4)


class SkewBoard(BaseModel):
    """Every competitive pick's skew, plus the §4.6 aggregations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    picks: tuple[PickSkew, ...]
    overall: SkewAggregate
    by_team: dict[str, SkewAggregate]
    by_position: dict[str, SkewAggregate]
    market_source: str

    def caveats(self) -> list[str]:
        """What a reader must know before trusting these numbers."""
        out: list[str] = []
        estimated = sum(1 for pick in self.picks if pick.market_value_is_estimate)
        unpriced = sum(1 for pick in self.picks if pick.market_value is None)
        if estimated:
            out.append(
                f"{estimated} of {len(self.picks)} picks have an ESTIMATED consensus value "
                f"(source {self.market_source!r}), which borrows this model's own price ladder. "
                "Market skew and edge skew converge by construction on those picks, so the gap "
                "between them is not evidence of anything until real auction values arrive."
            )
        if unpriced:
            out.append(
                f"{unpriced} pick(s) have no consensus value at all; they are excluded from "
                "market skew entirely rather than counted as zero"
            )
        return out

    def biggest_overpays(self, limit: int = 10) -> list[PickSkew]:
        return sorted(self.picks, key=lambda p: p.edge_skew, reverse=True)[:limit]

    def biggest_bargains(self, limit: int = 10) -> list[PickSkew]:
        return sorted(self.picks, key=lambda p: p.edge_skew)[:limit]


def _aggregate(label: str, picks: Sequence[PickSkew]) -> SkewAggregate:
    edge = [pick.edge_skew for pick in picks]
    market = [pick.market_skew for pick in picks if pick.market_skew is not None]
    return SkewAggregate(
        label=label,
        picks=len(picks),
        spent=sum(pick.price_paid for pick in picks),
        projected_points=0.0,
        total_edge_skew=round(sum(edge), 2),
        mean_edge_skew=round(statistics.fmean(edge), 2) if edge else 0.0,
        # `stdev` needs two points and raises on one. Returning 0.0 there would read as a
        # perfectly consistent bidder rather than as a sample of one.
        stdev_edge_skew=round(statistics.stdev(edge), 2) if len(edge) > 1 else None,
        total_market_skew=round(sum(market), 2) if market else None,
        mean_market_skew=round(statistics.fmean(market), 2) if market else None,
        market_priced=len(market),
    )


def skew_board(
    state: DerivedState,
    board: Mapping[str, PlayerValue],
    market: MarketValues,
    *,
    total_budget: int,
    total_slots: int,
    keeper_spend: int,
    keeper_slots: int,
    owners: Mapping[int, str] | None = None,
) -> SkewBoard:
    """Measure every competitive pick against consensus and against our model.

    Args:
        board: ``player_id -> PlayerValue``. A pick naming a player not on the board is skipped
            -- there is no value to measure it against, and inventing one would put a fabricated
            number into an aggregate that reads as measurement.
        market: Consensus values. Supplies ``market_value``; never our own model's field.
        owners: ``draft_slot -> owner name``, for the per-team roll-up. Unmapped slots fall back
            to ``slot N`` rather than being dropped, because a team's skew must not vanish just
            because its manager has not joined the league yet.
    """
    steps = walk_inflation(
        state,
        board,
        total_budget=total_budget,
        total_slots=total_slots,
        keeper_spend=keeper_spend,
        keeper_slots=keeper_slots,
    )
    slot_of = {entry.player_id: team.slot for team in state.teams.values() for entry in team.roster}
    owners = dict(owners or {})

    picks: list[PickSkew] = []
    for step in steps:
        player = board.get(step.player_id)
        if player is None:
            continue
        picks.append(
            PickSkew(
                competitive_seq=step.competitive_seq,
                player_id=step.player_id,
                name=player.name,
                position=player.position,
                slot=slot_of.get(step.player_id),
                price_paid=step.amount,
                market_value=market.get(step.player_id),
                market_value_is_estimate=market.is_estimate_for(step.player_id),
                adjusted_value=step.before.adjusted(player),
                inflation_at_pick=step.before.inflation,
            )
        )

    def group(key: str) -> dict[str, list[PickSkew]]:
        out: dict[str, list[PickSkew]] = {}
        for pick in picks:
            if key == "team":
                name = owners.get(pick.slot) if pick.slot is not None else None
                bucket = name or (f"slot {pick.slot}" if pick.slot is not None else "unassigned")
            else:
                bucket = pick.position
            out.setdefault(bucket, []).append(pick)
        return out

    points = {pid: player.points for pid, player in board.items()}

    def with_points(label: str, group_picks: Sequence[PickSkew]) -> SkewAggregate:
        aggregate = _aggregate(label, group_picks)
        return aggregate.model_copy(
            update={
                "projected_points": round(
                    sum(points.get(pick.player_id, 0.0) for pick in group_picks), 1
                )
            }
        )

    return SkewBoard(
        picks=tuple(picks),
        overall=with_points("all competitive picks", picks),
        by_team={
            name: with_points(name, group_picks) for name, group_picks in group("team").items()
        },
        by_position={
            position: with_points(position, group_picks)
            for position, group_picks in group("position").items()
        },
        market_source=market.source,
    )
