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

**Per-position inflation, and where the charter's formula does not survive contact.**

§4.5 asks for the same ratio "restricted to positional need (allocating FLEX proportionally to
remaining positional demand)", and describes the output as *"RB is inflating at 1.18x while QB
has deflated to 0.91x"*. Those two sentences want different things, and the first one is
degenerate.

The forward formula needs a per-position *money* figure. The money in the room is not labelled
by position -- a manager holding $80 has not decided how much of it is RB money. Any split has
to be assumed, and the only assumption available from the model itself is to allocate money in
proportion to each position's remaining model value. Do that and::

    inflation_pos = money_pos / value_pos
                  = (D x value_pos / Σ value) / value_pos
                  = D / Σ value
                  = the overall inflation, identically, for every position

Every position reports the same number. It is not a positional signal at all; it is the overall
figure wearing five hats, and it would read as "no position is mispriced" in exactly the market
where one is.

So the positional figure here is **realized**: what the room has actually paid at a position
against what the model says those same players were worth::

    realized_pos = Σ price_paid / Σ baseline_value   over COMPETITIVE picks at that position

That is what "RB is inflating at 1.18x" means when a person says it, it is non-circular, and it
is the number that makes money. It needs a sample before it means anything, so it reports
``None`` below :data:`MIN_POSITION_SAMPLE` picks rather than extrapolating from two.

The degenerate forward version is not shipped. :func:`forward_positional_inflation` exists to
*demonstrate* the degeneracy -- it is exercised by a test that asserts every position returns
the overall figure -- so that the finding is pinned in code rather than living in a comment
somebody deletes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from draft_intel.models import DerivedState, PickClass
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


def forward_positional_inflation(
    available: Sequence[PlayerValue],
    *,
    remaining_money: int,
    remaining_slots: int,
    positions: Iterable[str],
) -> dict[str, float]:
    """The charter's §4.5 positional formula, which returns the overall figure for every position.

    **Not a positional signal, and not shipped as one.** This exists so the degeneracy is pinned
    by a test rather than described in a comment. Allocating remaining money in proportion to
    each position's remaining model value gives::

        inflation_pos = (D x value_pos / Σ value) / value_pos = D / Σ value

    which is the overall inflation, identically, for every position. Use
    :func:`realized_positional_inflation` for the figure the charter's own example sentence
    describes.
    """
    overall = market_inflation(
        available, remaining_money=remaining_money, remaining_slots=remaining_slots
    )
    return dict.fromkeys(positions, overall.inflation)
