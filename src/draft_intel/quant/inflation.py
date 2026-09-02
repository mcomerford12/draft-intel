"""DI-032 — live market inflation, overall and per position.

Charter §4.5, recomputed after every settled pick::

    remaining_money         = Σ (200 - all_spend_t)        # all_spend includes keeper picks
    remaining_slots         = Σ (16 - all_picks_t)         # keeper picks count as filled slots
    discretionary_remaining = remaining_money - remaining_slots
    remaining_pool          = top `remaining_slots` available players by baseline_value
    remaining_value         = Σ (baseline_value_i - 1) over remaining_pool
    inflation               = discretionary_remaining / remaining_value
    adjusted_value_i        = 1 + (baseline_value_i - 1) x inflation

``baseline_value`` already prices in the keeper effect, so this starts at **exactly 1.0000**
before a competitive bid is made -- not "near" 1.0, exactly it, and :func:`market_inflation`
has a test proving the identity rather than asserting a tolerance. Kept permanently distinct
from ``keeper_inflation`` (DI-031), which is structural and fixed. ADR-0001; two quantities,
two labels, never merged.

**Every input here is filtered to ``COMPETITIVE`` picks.** The twenty ceremonial keeper picks
were not competitive bids. Charter §2 is blunt about what happens otherwise: they "will poison
skew statistics, inflation calibration, run detection, and every manager tendency profile --
and they will do so silently, producing a system that looks like it is working while giving bad
advice for the entire night."

Time series key on ``competitive_seq``, never ``pick_no``. In Case B the ceremonial picks occupy
``pick_no`` 1-20 and shift every competitive pick's number by 20, so a curve drawn against
``pick_no`` is a different curve in the two cases and the blocking Case A/B equivalence gate
cannot pass. See ADR-0001 and D3.

----

**Per-position inflation. Two figures, because §4.5 asks two questions.**

*Forward* (:func:`forward_positional_inflation`) is §4.5's formula, restricted to positional
need: money and slots allocated by **demand**, FLEX split proportionally, and the ratio taken
against the value still on the board at that position::

    slots_pos     = remaining base slots + this position's share of FLEX
    money_pos     = remaining money x slots_pos / total remaining slots
    value_pos     = Σ (baseline_value - 1) over the top `slots_pos` available at that position
    inflation_pos = (money_pos - slots_pos) / value_pos

**An earlier version of this module claimed this formula was degenerate and refused to build
it.** The argument was that allocating money in proportion to each position's remaining *model
value* makes ``value_pos`` cancel, leaving the overall figure for every position. The algebra
was right and it was about the wrong formula: §4.5 says *"restrict money and slots to positional
**need**"* and *"allocating FLEX proportionally to remaining positional **demand**"*. Need and
demand are slots, not value. Under slot-proportional allocation ``value_pos`` appears only in
the denominator, nothing cancels, and the positions genuinely separate -- on this league's
board, 0.78x at QB against 0.42x at RB.

The forward figure has one real pathology and it is reported rather than printed: a position
whose remaining value is near zero divides a real slot allocation by almost nothing. Kickers do
this every time -- ten slots must be filled by players worth nothing over replacement, so the
formula says the room "should" spend a hundred dollars there. That is a property of allocating
money by slot count when slots are not equally valuable, and :attr:`PositionForward.reliable`
carries it.

*Realized* (:func:`realized_positional_inflation`) is what the room has actually paid at a
position against what the model says those players were worth::

    realized_pos = Σ price_paid / Σ baseline_value   over COMPETITIVE picks at that position

Backward-looking, non-circular, and the thing §4.5's own example sentence describes when it
says *"RB is inflating at 1.18x while QB has deflated to 0.91x"*. It needs a sample, so it
reports ``None`` below :data:`MIN_POSITION_SAMPLE` picks rather than extrapolating from two.

They answer different questions -- what the room *should* pay for what is left, and what it
*has* paid -- and the gap between them is itself a signal. Neither replaces the other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from draft_intel.models import DerivedState, PickClass
from draft_intel.quant.slots import allocate_flex
from draft_intel.quant.valuation import MIN_BID, PlayerValue

# Below this many competitive picks at a position, a realized ratio is an anecdote. Two RBs
# going for double is a bidding war between two managers, not a market.
MIN_POSITION_SAMPLE = 3


class Inflation(BaseModel):
    """The overall live inflation figure and every input needed to check it by hand."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    remaining_money: int
    remaining_slots: int
    discretionary_remaining: int
    remaining_value: float
    pool_size: int
    inflation: float

    def adjusted(self, player: PlayerValue) -> float:
        """``1 + (baseline_value - 1) x inflation``. What this player should cost right now."""
        return round(MIN_BID + (player.baseline_value - MIN_BID) * self.inflation, 2)


class PositionInflation(BaseModel):
    """What the room has actually paid at one position, against what the model says it is worth.

    ``ratio`` is ``None`` below :data:`MIN_POSITION_SAMPLE` picks. A number computed from two
    picks is not a market reading, and presenting one invites a bidding decision built on noise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: str
    picks: int
    spent: int
    model_value: float
    ratio: float | None

    @property
    def is_reportable(self) -> bool:
        return self.ratio is not None

    def describe(self) -> str:
        if self.ratio is None:
            return (
                f"{self.position}: {self.picks} competitive pick(s), too few to read "
                f"(need {MIN_POSITION_SAMPLE})"
            )
        direction = "inflating at" if self.ratio >= 1.0 else "deflated to"
        return f"{self.position} is {direction} {self.ratio:.2f}x over {self.picks} picks"


def market_inflation(
    available: Sequence[PlayerValue],
    *,
    remaining_money: int,
    remaining_slots: int,
) -> Inflation:
    """Charter §4.5, exactly as written.

    Args:
        available: Players still on the board. Keepers and drafted players must already be
            excluded -- passing a drafted player leaves money chasing value that is gone.
        remaining_money: ``Σ (budget - all_spend_t)``, including keeper spend.
        remaining_slots: ``Σ (draft_rounds - all_picks_t)``, keeper picks counting as filled.

    Returns 1.0 when there is nothing left to price, rather than dividing by zero: a board with
    no remaining value has no inflation to report, and every ``adjusted`` call then returns the
    baseline unchanged, which is the right behaviour at the end of a draft.
    """
    discretionary = remaining_money - remaining_slots
    pool = sorted(available, key=lambda p: p.baseline_value, reverse=True)[
        : max(0, remaining_slots)
    ]
    remaining_value = sum(p.baseline_value - MIN_BID for p in pool)
    return Inflation(
        remaining_money=remaining_money,
        remaining_slots=remaining_slots,
        discretionary_remaining=discretionary,
        remaining_value=round(remaining_value, 2),
        pool_size=len(pool),
        inflation=round(discretionary / remaining_value, 4) if remaining_value > 0 else 1.0,
    )


def competitive_picks(state: DerivedState) -> list[tuple[int, str, int]]:
    """``(competitive_seq, player_id, amount)`` for every COMPETITIVE pick, in sequence order.

    The single filter every analytic in this module goes through. Ceremonial keeper picks are
    excluded here once, rather than in each caller where one will eventually be forgotten.
    """
    out: list[tuple[int, str, int]] = []
    for team in state.teams.values():
        for entry in team.roster:
            if entry.pick_class is not PickClass.COMPETITIVE or entry.pick_no is None:
                continue
            seq = state.competitive_seq.get(entry.pick_no)
            if seq is not None:
                out.append((seq, entry.player_id, entry.amount))
    out.sort()
    return out


def realized_positional_inflation(
    state: DerivedState,
    board: Mapping[str, PlayerValue],
    *,
    min_sample: int = MIN_POSITION_SAMPLE,
) -> dict[str, PositionInflation]:
    """What the room paid at each position against what the model said those players were worth.

    Args:
        state: The folded ledger. Only ``COMPETITIVE`` picks are read.
        board: ``player_id -> PlayerValue``. A pick naming a player not on the board is skipped
            and does not distort the ratio -- it contributes to neither numerator nor
            denominator, which is the only treatment that leaves the ratio meaning what it says.
        min_sample: Competitive picks needed at a position before a ratio is reported.

    A player bought at the $1 minimum whose ``baseline_value`` is 0 -- off the priced pool
    entirely -- contributes their dollar to the spend and nothing to the value. That is correct:
    the room really did spend that money, and the model really does say the player is worth
    nothing above replacement.
    """
    spent: dict[str, int] = {}
    value: dict[str, float] = {}
    picks: dict[str, int] = {}
    for _seq, player_id, amount in competitive_picks(state):
        player = board.get(player_id)
        if player is None:
            continue
        position = player.position
        spent[position] = spent.get(position, 0) + amount
        value[position] = value.get(position, 0.0) + player.baseline_value
        picks[position] = picks.get(position, 0) + 1

    out: dict[str, PositionInflation] = {}
    for position, count in picks.items():
        model_value = value[position]
        reportable = count >= min_sample and model_value > 0
        out[position] = PositionInflation(
            position=position,
            picks=count,
            spent=spent[position],
            model_value=round(model_value, 2),
            ratio=round(spent[position] / model_value, 4) if reportable else None,
        )
    return out


class InflationStep(BaseModel):
    """One competitive pick, with the room's state on both sides of it.

    The two are different numbers and confusing them biases every downstream figure in one
    direction. ``before`` is what the room was actually bidding against when this player was on
    the block; ``after`` is the state the pick left behind. A skew figure judged against
    ``after`` measures the pick partly against its own effect, which flatters an overpay and
    penalises a bargain.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    competitive_seq: int
    player_id: str
    amount: int
    before: Inflation
    after: Inflation


def walk_inflation(
    state: DerivedState,
    board: Mapping[str, PlayerValue],
    *,
    total_budget: int,
    total_slots: int,
    keeper_spend: int,
    keeper_slots: int,
) -> list[InflationStep]:
    """Replay the competitive picks, recomputing inflation on both sides of each one.

    Keyed on ``competitive_seq`` and never on ``pick_no``. In Case B the ceremonial picks hold
    ``pick_no`` 1-20 and shift every competitive pick by 20, so a series drawn against
    ``pick_no`` differs between the two cases and the blocking Case A/B equivalence gate fails.
    Recomputed wholesale on every fold; ``competitive_seq`` values are never persisted.

    Args:
        keeper_spend: ΣK. Charter §4.5 counts keeper money as spent and keeper picks as filled
            slots, so both are subtracted from the starting position rather than ignored.
        keeper_slots: Roster spots the keepers occupy.
    """
    money = total_budget - keeper_spend
    slots = total_slots - keeper_slots
    taken: set[str] = set()

    def remaining() -> list[PlayerValue]:
        return [
            player
            for player_id, player in board.items()
            if player_id not in taken and not player.is_keeper
        ]

    steps: list[InflationStep] = []
    for seq, player_id, amount in competitive_picks(state):
        before = market_inflation(remaining(), remaining_money=money, remaining_slots=slots)
        money -= amount
        slots -= 1
        taken.add(player_id)
        steps.append(
            InflationStep(
                competitive_seq=seq,
                player_id=player_id,
                amount=amount,
                before=before,
                after=market_inflation(remaining(), remaining_money=money, remaining_slots=slots),
            )
        )
    return steps


def inflation_curve(
    state: DerivedState,
    board: Mapping[str, PlayerValue],
    *,
    total_budget: int,
    total_slots: int,
    keeper_spend: int,
    keeper_slots: int,
) -> list[tuple[int, float]]:
    """``(competitive_seq, inflation)`` after each competitive pick, for charting.

    The *after* figure, because a chart of the room's state should show where each pick left it.
    Skew uses :attr:`InflationStep.before` instead; see :class:`InflationStep`.
    """
    return [
        (step.competitive_seq, step.after.inflation)
        for step in walk_inflation(
            state,
            board,
            total_budget=total_budget,
            total_slots=total_slots,
            keeper_spend=keeper_spend,
            keeper_slots=keeper_slots,
        )
    ]


class PositionForward(BaseModel):
    """§4.5's forward figure for one position: what the room should pay for what is left."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: str
    slots: int
    """Remaining base slots plus this position's proportional share of FLEX."""

    money: float
    """This position's share of the remaining money, allocated by slots."""

    value: float
    """``Σ (baseline_value - 1)`` over the top ``slots`` players still available here."""

    pool_size: int
    inflation: float | None
    """``None`` when there is no value left to divide into -- not 1.0, which would read as
    "correctly priced" at a position where nothing is priced at all."""

    reliable: bool
    """False when the remaining value is small enough that the ratio is an artifact.

    Kickers trip this on every board: ten slots must be filled by players worth nothing over
    replacement, so a slot-proportional money allocation divides a real hundred dollars by
    almost nothing and reports an enormous number. That is a property of allocating money by
    slot count when slots are not equally valuable, not a finding about the kicker market.
    """

    def describe(self) -> str:
        if self.inflation is None:
            return f"{self.position}: no value left to price"
        flag = "" if self.reliable else "  (artifact: almost no value left at this position)"
        direction = "should clear over" if self.inflation >= 1.0 else "should clear under"
        return f"{self.position} {direction} book at {self.inflation:.2f}x{flag}"


# Below this share of the *overall* remaining value, a position's forward ratio is dividing by
# near-nothing and is reported as unreliable rather than as a signal.
MIN_FORWARD_VALUE_SHARE = 0.02


def forward_positional_inflation(
    available: Sequence[PlayerValue],
    *,
    remaining_money: int,
    remaining_base: Mapping[str, int],
    remaining_flex: int,
) -> dict[str, PositionForward]:
    """Charter §4.5's positional formula: money and slots restricted to positional need.

    Args:
        available: Players still on the board.
        remaining_money: ``Σ (budget - all_spend_t)`` across the league.
        remaining_base: Remaining base starting slots per position, keepers already removed.
        remaining_flex: Remaining FLEX slots, split proportionally across RB/WR/TE.

    Money is allocated **by slots**, which is what §4.5's "restrict money and slots to positional
    need" says and is the reason the figure is not degenerate: ``value_pos`` appears only in the
    denominator. Allocating by *value* instead would cancel it and hand every position the
    overall number -- see the module docstring for why an earlier version got this wrong.
    """
    share = allocate_flex(remaining_flex, remaining_base)
    slots = {
        position: count + share.get(position, 0)
        for position, count in remaining_base.items()
        if count + share.get(position, 0) > 0
    }
    total_slots = sum(slots.values())
    if total_slots <= 0:
        return {}

    by_position: dict[str, list[PlayerValue]] = {}
    for player in available:
        by_position.setdefault(player.position, []).append(player)

    values: dict[str, tuple[float, int]] = {}
    for position, count in slots.items():
        pool = sorted(by_position.get(position, []), key=lambda p: p.baseline_value, reverse=True)[
            :count
        ]
        values[position] = (sum(p.baseline_value - MIN_BID for p in pool), len(pool))

    overall_value = sum(value for value, _size in values.values())
    out: dict[str, PositionForward] = {}
    for position, count in sorted(slots.items()):
        value, pool_size = values[position]
        money = remaining_money * count / total_slots
        out[position] = PositionForward(
            position=position,
            slots=count,
            money=round(money, 2),
            value=round(value, 2),
            pool_size=pool_size,
            inflation=round((money - count) / value, 4) if value > 0 else None,
            reliable=(
                value > 0 and overall_value > 0 and value / overall_value >= MIN_FORWARD_VALUE_SHARE
            ),
        )
    return out
