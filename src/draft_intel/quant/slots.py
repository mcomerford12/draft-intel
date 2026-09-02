"""DI-028 — league slot demand, and what the keepers have already taken out of it.

Charter §4.2 is emphatic about this and it is the single easiest place to be wrong:

    Keeper adjustment - do this first, it is easy to get wrong. Replacement level must be
    computed on the post-keeper universe, adjusting *both* sides of the equation. Supply:
    remove the 20 keepers from the player pool entirely. Demand: reduce league-wide positional
    slot demand by the slots the keepers already occupy [...] Both shifts matter and they push
    in opposite directions. A naive implementation that does one and not the other will produce
    plausible-looking but badly wrong prices.

This module owns the demand half. Supply is handled in :mod:`draft_intel.quant.replacement`
by excluding keeper ``player_id``s from the pool.

Each keeper is assigned to a slot the way it will actually be started: base slot for its
position first, then FLEX. That ordering is not cosmetic -- a team keeping two wide receivers
fills both WR slots, while a team keeping three would push one into FLEX, and the resulting
demand reduction differs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict

FLEX = "FLEX"
FLEX_ELIGIBLE = frozenset({"RB", "WR", "TE"})


class SlotDemand(BaseModel):
    """League-wide slot counts, before and after the keepers are seated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base: dict[str, int]
    flex: int
    keeper_base: dict[str, int]
    keeper_flex: int
    keeper_bench: int

    @property
    def total_starting(self) -> int:
        return sum(self.base.values()) + self.flex

    @property
    def remaining_base(self) -> dict[str, int]:
        return {pos: count - self.keeper_base.get(pos, 0) for pos, count in self.base.items()}

    @property
    def remaining_flex(self) -> int:
        return self.flex - self.keeper_flex

    @property
    def remaining_starting(self) -> int:
        """Starting slots still to be bought.

        Charter §4.2 requires asserting this *and* remaining roster spots separately: they are
        different numbers (80 and 140 for this league) and are easy to transpose.
        """
        return sum(self.remaining_base.values()) + self.remaining_flex

    @property
    def keeper_starting(self) -> int:
        return sum(self.keeper_base.values()) + self.keeper_flex


def allocate_flex(flex_slots: int, remaining_base: Mapping[str, int]) -> dict[str, int]:
    """Split FLEX across the eligible positions in proportion to their remaining demand.

    Charter §4.5: *"allocating FLEX proportionally to remaining positional demand"*. Largest
    remainder, so the parts sum to ``flex_slots`` exactly -- flooring an even three-way split
    threw two of twenty slots away and made a report disagree with its own total.
    """
    weights = {pos: remaining_base.get(pos, 0) for pos in sorted(FLEX_ELIGIBLE)}
    total = sum(weights.values())
    if total <= 0 or flex_slots <= 0:
        return dict.fromkeys(weights, 0)

    exact = {pos: flex_slots * weight / total for pos, weight in weights.items()}
    share = {pos: int(value) for pos, value in exact.items()}
    for pos, _remainder in sorted(
        ((pos, exact[pos] - share[pos]) for pos in share), key=lambda kv: -kv[1]
    )[: flex_slots - sum(share.values())]:
        share[pos] += 1
    return share


def seat_keepers(
    keeper_positions_by_team: Mapping[int, Iterable[str]],
    *,
    starters: Mapping[str, int],
    teams: int,
) -> SlotDemand:
    """Seat every team's keepers into slots, greedily: base slot first, then FLEX.

    Args:
        keeper_positions_by_team: Positions of each team's keepers, keyed by draft slot.
        starters: Per-team starting slots, e.g. ``{"QB": 2, "RB": 2, ..., "FLEX": 2}``.
        teams: Number of teams in the league.

    A keeper that fits neither a base slot nor FLEX is counted as bench. That cannot happen
    with the current slate, but a team keeping two tight ends in a one-TE league would do it,
    and silently dropping such a keeper would understate demand reduction.
    """
    base_per_team = {pos: count for pos, count in starters.items() if pos != FLEX}
    flex_per_team = starters.get(FLEX, 0)

    keeper_base: dict[str, int] = dict.fromkeys(base_per_team, 0)
    keeper_flex = 0
    keeper_bench = 0

    for _team, positions in sorted(keeper_positions_by_team.items()):
        used_base: dict[str, int] = dict.fromkeys(base_per_team, 0)
        used_flex = 0
        for position in positions:
            if used_base.get(position, 0) < base_per_team.get(position, 0):
                used_base[position] += 1
                keeper_base[position] += 1
            elif position in FLEX_ELIGIBLE and used_flex < flex_per_team:
                used_flex += 1
                keeper_flex += 1
            else:
                keeper_bench += 1

    return SlotDemand(
        base={pos: count * teams for pos, count in base_per_team.items()},
        flex=flex_per_team * teams,
        keeper_base=keeper_base,
        keeper_flex=keeper_flex,
        keeper_bench=keeper_bench,
    )
