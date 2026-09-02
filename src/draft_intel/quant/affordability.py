"""DI-034 — opponent max bids and the affordability ladder.

Charter §4.7c calls this "the single most actionable auction display in existence":

    **Who can still afford this player, and at what price does each of them drop out.**

    Rank opponents by (max bid x positional need x their demonstrated aggression at this
    position). This tells the user whether they are bidding against a real threat or against a
    manager who is about to get priced out.

Three quantities, and the whole value is in keeping them apart.

**1. Max bid** — ``budget_remaining - (open_slots - 1)``, §1.1, bounded at the team's budget.
Hard arithmetic: a team must reserve $1 for every roster spot it still has to fill, so this is
the most it can legally bid. The ledger already computes it per team (``TeamState.max_bid``);
this module never recomputes it, because two implementations of the same rule drift and one of
them will be the one on screen.

The bound is why the identity above is "usually" rather than "always": a negative amount in a
ledger makes ``budget_remaining`` exceed the budget, and an unbounded figure would advise a $686
bid in a $200 league. Where the two disagree the team is carrying corrupt input, and
``Opponent.figures_suspect`` says so on the row rather than leaving it to ``state.alerts``,
which nothing on this path reads.

**2. Positional need** — does this team have a *starting* slot open at this position? A team with
both QB slots filled can still bid on a quarterback, and occasionally will, but it is not a
threat in the sense the user cares about. Need is derived from the roster the ledger already
holds, not assumed.

**3. Demonstrated aggression** — how this manager has actually bid at this position tonight,
measured as realized skew. Not a personality label and not a prior: if a manager has spent
nothing at the position there is no evidence, and this reports that rather than guessing.

**Ranking is the product of the three, and it is presented as a rank rather than a score.** The
product's units are meaningless -- dollars times a boolean times a ratio -- so a number like
"38.4" would invite comparisons it cannot support. The ordering is the output.

**Spending power is unequal from pick 1** (§1.1). Every team's ledger starts at $200 and is
decremented uniformly, but keeper costs differ, so remaining budgets diverge immediately. Every
figure here reads the per-team value; none assumes a shared one.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from draft_intel.models import DerivedState, PickClass, TeamState
from draft_intel.quant.skew import SkewBoard
from draft_intel.quant.slots import FLEX, FLEX_ELIGIBLE

# Below this many competitive picks at a position, a manager's aggression there is an anecdote.
# Matches quant.inflation's threshold for the same reason: two picks is a mood, not a pattern.
MIN_AGGRESSION_SAMPLE = 3


class Opponent(BaseModel):
    """One team's ability and appetite to bid on the player currently on the block."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slot: int
    owner: str
    budget_remaining: int
    open_slots: int
    max_bid: int
    """The most this team can bid. Read from the ledger, never recomputed here.

    Usually ``budget_remaining - (open_slots - 1)``, but **not always**: the ledger bounds it at
    the team's budget so a negative amount cannot produce a bid larger than the whole league.
    When the two disagree, :attr:`figures_suspect` is set and the identity above is the thing
    that has stopped being true.
    """

    figures_suspect: bool = False
    """True when this team's ledger contains a negative amount, so none of its money is reliable.

    Carried onto the opponent rather than left in ``state.alerts``, because this class is what
    the bidding decision is made from. A bounded-but-wrong ``max_bid`` is more dangerous than an
    absurd one -- $686 in a $200 league announces itself, $186 does not -- so the flag rides with
    the figure it undermines.
    """

    needs_position: bool
    """A *starting* slot open at this position, counting FLEX for RB/WR/TE."""

    starting_gap: int
    """How many starting slots at this position this team still has to fill."""

    aggression: float | None
    """Mean edge skew at this position tonight, in dollars. ``None`` below the sample floor.

    Positive means this manager has been paying over our model at this position. ``None`` is
    not zero: no evidence is a different statement from evidence of discipline, and rendering
    it as 0.0 would rank an unknown manager as precisely average.
    """

    aggression_picks: int

    @property
    def can_afford(self) -> bool:
        return self.max_bid >= 1 and self.open_slots > 0

    def drops_out_above(self) -> int:
        """The highest bid this team can still make. One dollar more and they are out.

        Returns ``max_bid`` itself, which is a bid they *can* make -- the name reads as the
        threshold above which they drop out, and that is what it is. An earlier docstring said
        "one dollar under its max bid", which the code has never done and which a future caller
        would have implemented against.
        """
        return self.max_bid

    @property
    def threat(self) -> float:
        """``max_bid x need x aggression``, for ordering only.

        The units are meaningless -- dollars times a boolean times a dollar figure -- so this
        is deliberately never displayed. :func:`affordability` returns opponents already
        ordered, and the rank is the output.

        An unknown aggression contributes a neutral 1.0 rather than 0.0: a manager we have no
        read on is an ordinary threat, not a harmless one, and zeroing them would sort every
        quiet manager to the bottom precisely when they are about to spend.

        The explicit ``None`` branch is arithmetically identical to feeding 0.0 through the
        formula, since the multiplier is 1.0 at zero skew. It is kept because the two say
        different things, and because the wrong alternative -- a 0.0 *threat* rather than a 0.0
        *skew* -- is a real and tempting mistake that a test pins.
        """
        if not self.can_afford:
            return 0.0
        need = 1.0 if self.needs_position else 0.25
        appetite = 1.0 if self.aggression is None else max(0.1, 1.0 + self.aggression / 10.0)
        return self.max_bid * need * appetite


class Affordability(BaseModel):
    """Who can still afford the player on the block, and where each of them drops out."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: str
    opponents: tuple[Opponent, ...]
    """Every team except the user's, ordered by threat, highest first."""

    my_max_bid: int
    my_open_slots: int
    my_budget_remaining: int

    @property
    def contenders(self) -> tuple[Opponent, ...]:
        """Opponents who both can afford a bid and have a starting slot to fill."""
        return tuple(o for o in self.opponents if o.can_afford and o.needs_position)

    def still_in_at(self, price: int) -> tuple[Opponent, ...]:
        """Opponents whose max bid still covers ``price``."""
        return tuple(o for o in self.opponents if o.max_bid >= price)

    def price_that_clears_the_field(self) -> int:
        """One dollar above the highest opponent max bid: nobody can answer it.

        Not advice -- it is frequently a terrible bid -- but it is the number that bounds every
        bidding war, and it is not otherwise obvious from ten separate budgets.
        """
        highest = max((o.max_bid for o in self.opponents), default=0)
        return highest + 1

    def describe(self) -> list[str]:
        lines: list[str] = []
        for opponent in self.opponents:
            if not opponent.can_afford:
                lines.append(f"{opponent.owner}: out (no money or no slots)")
                continue
            need = (
                f"needs {opponent.starting_gap} more at {self.position}"
                if opponent.needs_position
                else f"{self.position} starters full"
            )
            read = (
                "no read yet"
                if opponent.aggression is None
                else f"{opponent.aggression:+.1f}/pick vs model over {opponent.aggression_picks}"
            )
            # The suspect marker goes first, before the number it undermines. A reader
            # scanning this ladder mid-nomination takes the dollar figure and moves on; a
            # caveat trailing the line would be read after the decision it should have
            # changed.
            suspect = (
                "⚠ FIGURES SUSPECT (negative amount in ledger) " if opponent.figures_suspect else ""
            )
            lines.append(
                f"{opponent.owner}: {suspect}out above ${opponent.max_bid}, {need}, {read}"
            )
        return lines


def _starting_gap(
    team: TeamState,
    position: str,
    starters: Mapping[str, int],
    positions: Mapping[str, str],
) -> int:
    """Starting slots at ``position`` this team still has to fill, counting FLEX.

    Reads the roster the ledger already holds. Every pick counts, keepers included -- §2 is
    explicit that money, roster and slot math use every pick regardless of class, and a keeper
    quarterback occupies a QB slot exactly as a bought one does.

    ``RosterEntry`` deliberately carries no position: the ledger is about money and slots and
    has no business knowing what a player plays. Positions come from the priced board.
    """
    held: dict[str, int] = {}
    for entry in team.roster:
        held_position = positions.get(entry.player_id)
        if held_position is None:
            continue
        held[held_position] = held.get(held_position, 0) + 1

    base = starters.get(position, 0)
    at_position = held.get(position, 0)
    gap = base - at_position
    if gap > 0:
        return gap

    # Base slots at this position are full. FLEX absorbs the overflow from the eligible
    # positions collectively, so the gap there is the FLEX count less everyone's overflow --
    # computing it per position in isolation would report a free FLEX slot to three positions
    # at once.
    if position not in FLEX_ELIGIBLE:
        return 0
    overflow = sum(
        max(0, held.get(eligible, 0) - starters.get(eligible, 0)) for eligible in FLEX_ELIGIBLE
    )
    return max(0, starters.get(FLEX, 0) - overflow)


def affordability(
    state: DerivedState,
    *,
    position: str,
    my_slot: int,
    starters: Mapping[str, int],
    positions: Mapping[str, str],
    owners: Mapping[int, str] | None = None,
    skew: SkewBoard | None = None,
    min_aggression_sample: int = MIN_AGGRESSION_SAMPLE,
) -> Affordability:
    """Rank every other team by whether they are a real threat on this player.

    Args:
        state: The folded ledger. Budgets, open slots and max bids all come from here.
        position: The position of the player on the block.
        my_slot: The user's draft slot, excluded from the opponent list.
        starters: Per-team starting slots, e.g. ``{"QB": 2, ..., "FLEX": 2}``.
        positions: ``player_id -> position``, from the priced board. A rostered player the
            board does not know is not counted toward any positional need; inventing a
            position would report a slot as filled that may not be.
        owners: ``draft_slot -> owner name``. An unmapped slot is labelled by number rather
            than dropped -- six managers have not joined, and a live opponent must not vanish
            from the threat list because of it.
        skew: Tonight's skew board, for demonstrated aggression. Omit before the draft.

    Raises:
        KeyError: if ``my_slot`` is not in the ledger. Silently returning every team as an
            opponent would put the user on their own threat list.
    """
    if my_slot not in state.teams:
        raise KeyError(f"draft slot {my_slot} is not in this league's ledger")

    names = dict(owners or {})
    mine = state.teams[my_slot]

    opponents: list[Opponent] = []
    for slot, team in sorted(state.teams.items()):
        if slot == my_slot:
            continue
        owner = names.get(slot) or f"slot {slot}"
        gap = _starting_gap(team, position, starters, positions)
        aggression, sample = _team_aggression(
            skew, slot, position, min_sample=min_aggression_sample
        )
        opponents.append(
            Opponent(
                slot=slot,
                owner=owner,
                budget_remaining=team.remaining,
                open_slots=team.open_slots,
                max_bid=team.max_bid,
                figures_suspect=team.figures_suspect,
                needs_position=gap > 0,
                starting_gap=gap,
                aggression=aggression,
                aggression_picks=sample,
            )
        )

    opponents.sort(key=lambda o: (-o.threat, -o.max_bid, o.slot))
    return Affordability(
        position=position,
        opponents=tuple(opponents),
        my_max_bid=mine.max_bid,
        my_open_slots=mine.open_slots,
        my_budget_remaining=mine.remaining,
    )


def _team_aggression(
    skew: SkewBoard | None, slot: int, position: str, *, min_sample: int
) -> tuple[float | None, int]:
    """Mean edge skew for one team at one position, or ``None`` below the sample floor.

    Keyed on ``draft_slot``, never on owner name: the name may be unresolved (six managers have
    not joined) and two teams can share a fallback label, while the slot is always present and
    always unique. This is the same rule that governs the rest of the project.
    """
    if skew is None:
        return None, 0
    picks = [pick for pick in skew.picks if pick.slot == slot and pick.position == position]
    if len(picks) < min_sample:
        return None, len(picks)
    return round(sum(pick.edge_skew for pick in picks) / len(picks), 2), len(picks)


def my_max_bid(
    state: DerivedState,
    *,
    my_slot: int,
    adjusted_value: float,
    strategic_premium: float = 0.0,
) -> tuple[int, str]:
    """Charter §4.7a: ``min(budget - (open_slots - 1), adjusted_value + premium)``, labelled.

    Returns ``(bid, binding_constraint)``. The label is required by the charter and it is the
    useful half: "you are out of money" and "this player is not worth more to you" are entirely
    different situations, and a bare number says neither.
    """
    team = state.teams[my_slot]
    budget_cap = team.max_bid
    value_cap = int(adjusted_value + strategic_premium)
    if budget_cap <= value_cap:
        return budget_cap, "budget"
    return value_cap, "value"


def keeper_adjusted_open_slots(team: TeamState) -> int:
    """Open slots counting keepers as filled, which the ledger already does.

    Exists to be pointed at rather than reimplemented: §1.1 warns that ``open_slots`` is 14
    once both keepers are recorded, and every consumer that re-derives it from
    ``draft_rounds - competitive_picks`` gets 16 and computes a max bid $2 too high.
    """
    return team.open_slots


def keeper_count(team: TeamState) -> int:
    return sum(1 for entry in team.roster if entry.pick_class is PickClass.KEEPER)
