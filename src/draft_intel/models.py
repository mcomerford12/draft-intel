"""Core domain types.

Two rules govern everything here and are worth stating once:

1. ``draft_slot`` is the canonical team key, never ``roster_id``. Sleeper returns
   ``roster_id: null`` on mock drafts (see docs/api-findings.md, Finding 4), so keying on
   it collapses the ledger on our only real replay fixture.
2. Events are append-only facts. Derived state is a pure fold over them and is never
   mutated in place.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal, NoReturn

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

Slot = Annotated[int, Field(ge=1, le=32)]
PlayerId = str


class PickClass(StrEnum):
    """How a pick is treated by the analytics layer.

    Money, roster and slot math use every pick regardless of class. Auction analytics use
    ``COMPETITIVE`` only, because ceremonial keeper picks were never competitive bids and
    would silently poison skew, inflation and tendency statistics (charter §2).
    """

    KEEPER = "KEEPER"
    COMPETITIVE = "COMPETITIVE"
    FLAGGED = "FLAGGED"


class FrozenDict[K, V](dict[K, V]):
    """A mapping that refuses mutation at runtime.

    ``pydantic``'s ``frozen=True`` only blocks attribute rebinding, so a plain ``dict`` field
    on a frozen model stays fully mutable -- ``state.teams[1] = ...`` silently succeeded,
    which is the standing "never mutate derived state" rule broken by the very type meant to
    enforce it. Derived state only ever changes by appending an event and refolding.

    Two guarantees, and both are load-bearing:

    *Statically*, the fields that hold one of these are annotated ``Mapping``, which has no
    ``__setitem__`` at all, so ``mypy --strict`` rejects item assignment at the call site
    across the whole project. An earlier version annotated them ``FrozenDict`` over
    ``dict[Any, Any]``, which silently gave that up -- ``dict`` *does* declare
    ``__setitem__``, so the type checker stopped objecting anywhere.

    *At runtime*, every mutating operation ``dict`` defines is refused. Enumerating them one
    at a time is how the previous version shipped with a hole: ``__ior__`` was inherited
    unblocked, so ``state.teams |= {...}`` mutated in place and returned self, and only the
    subsequent attribute rebinding raised. The exception was real; the refusal was not.
    ``test_frozendict_guards_exactly_the_mutating_surface_of_dict`` pins the list.

    ``__reduce__`` keeps ``copy``, ``deepcopy`` and ``pickle`` working. Without it they all
    raised, because dict reconstruction goes through ``__setitem__``.
    """

    _MSG = "derived state is immutable; append an event and refold instead"

    def _refuse(self, *_: Any, **__: Any) -> NoReturn:
        raise TypeError(self._MSG)

    # Assigned rather than written out one def at a time, so the guarded set is a single
    # list to audit instead of eight bodies to compare.
    __setitem__ = _refuse
    __delitem__ = _refuse
    __ior__ = _refuse
    clear = _refuse
    pop = _refuse
    popitem = _refuse
    update = _refuse
    setdefault = _refuse

    def __or__(self, other: Any) -> dict[Any, Any]:
        """Non-mutating union, which yields a plain dict rather than a frozen one."""
        return dict(self) | dict(other)

    def __reduce__(self) -> tuple[Any, ...]:
        return (self.__class__, (dict(self),))


def _freeze[K, V](mapping: Mapping[K, V]) -> FrozenDict[K, V]:
    """Re-wrap after validation.

    ``pydantic`` coerces a ``Mapping`` annotation to a plain ``dict``, so without this a
    model built by ``model_validate`` -- the store round-trip, and every cockpit payload in
    Sprint 3 -- would hand back live, mutable derived state.
    """
    return FrozenDict(mapping)


Teams = Annotated[Mapping[int, "TeamState"], AfterValidator(_freeze)]
CompetitiveSeq = Annotated[Mapping[int, int], AfterValidator(_freeze)]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PickSnapshot(Frozen):
    """One pick as observed in ``/draft/{id}/picks``.

    ``amount`` arrives as a string and may be absent or empty; parsing lives in
    :func:`draft_intel.sleeper.poller.parse_pick` so this type is always already clean.
    """

    pick_no: int
    player_id: PlayerId
    slot: Slot
    amount: int
    is_keeper: bool
    position: str = ""
    name: str = ""

    conflicts: tuple[str, ...] = ()
    """Payload disagreements found while parsing this pick, carried **on the pick itself**.

    ``draft_slot`` vs ``metadata.slot``, ``player_id`` vs ``metadata.player_id``. The pick was
    kept and the primary field won, so this is not a rejection -- it is "this row is in the
    ledger and one of its numbers may be the wrong one".

    It rides on the snapshot rather than in a side channel because of how it has to be read. A
    wrong slot debits the wrong team while conservation still reconciles to $2,000 and nothing
    else looks unusual, so the warning has to be impossible to drop: an earlier version put it
    in ``ParseResult.rejects``, which reaches the fold only if the caller remembers to pass
    ``rejects=`` -- and the obvious Sprint 3 poll loop, ``parse_picks -> diff_snapshots ->
    fold``, does not. Travelling on the pick means it survives the event log, crash-restart and
    replay, and :func:`~draft_intel.domain.ledger.fold` raises it as an alert automatically."""


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


UNSTAMPED = 0
"""Sequence number of an event that has not yet been through the store.

Zero is deliberately not a usable target: a ``Revert`` aimed at it would neutralise every
event that had not yet been stamped. :func:`draft_intel.domain.ledger.fold` rejects such a
revert with an alert rather than honouring it.
"""


class _Event(Frozen):
    seq: int = UNSTAMPED
    ts: float = 0.0


class PickObserved(_Event):
    kind: Literal["pick_observed"] = "pick_observed"
    pick: PickSnapshot


class PickRemoved(_Event):
    """A commissioner reversed a pick; the feed shrank."""

    kind: Literal["pick_removed"] = "pick_removed"
    pick_no: int


class PickAmended(_Event):
    """A pick changed in place - usually a corrected amount."""

    kind: Literal["pick_amended"] = "pick_amended"
    pick: PickSnapshot


class BudgetAdjustment(_Event):
    """A correction of +/- N dollars against a team's ledger.

    Modelled as a delta rather than an absolute pin so the next poll cycle cannot fight
    the user's correction (charter §4.8). "Reset baseline" is computed into a delta by the
    caller before it reaches the log.
    """

    kind: Literal["budget_adjustment"] = "budget_adjustment"
    slot: Slot
    delta: int
    reason: str = ""


class ManualKeeper(_Event):
    """The user asserting a keeper the feed has not delivered.

    Sleeper publishes no auction value (Finding 3), so retention prices are typed in from
    the draft room. This is the primary path by which real keeper prices enter the system,
    not a fallback. Automatically superseded by a matching real pick.
    """

    kind: Literal["manual_keeper"] = "manual_keeper"
    slot: Slot
    player_id: PlayerId
    amount: int


class Reclassify(_Event):
    """Retroactive reclassification of a pick. Wins over every automatic mechanism."""

    kind: Literal["reclassify"] = "reclassify"
    pick_no: int
    pick_class: PickClass


class Revert(_Event):
    """Neutralise an earlier override event by sequence number.

    Only the kinds in :data:`OVERRIDE_KINDS` may be reverted. A revert aimed at a pick event
    is refused with an alert: the picks feed is the authority for money, and letting an
    override event delete a settled pick would silently destroy a team's spend.

    A ``Revert`` may itself be reverted, which reinstates the override it had neutralised.
    """

    kind: Literal["revert"] = "revert"
    target_seq: int


Event = (
    PickObserved | PickRemoved | PickAmended | BudgetAdjustment | ManualKeeper | Reclassify | Revert
)

OVERRIDE_KINDS = frozenset({"budget_adjustment", "manual_keeper", "reclassify"})


# ---------------------------------------------------------------------------
# Derived state
# ---------------------------------------------------------------------------


class RosterEntry(Frozen):
    player_id: PlayerId
    amount: int
    pick_class: PickClass
    pick_no: int | None = None
    manual: bool = False


class TeamState(Frozen):
    slot: Slot
    budget: int
    spent: int
    roster: tuple[RosterEntry, ...]
    total_slots: int

    @property
    def remaining(self) -> int:
        return self.budget - self.spent

    @property
    def filled_slots(self) -> int:
        return len(self.roster)

    @property
    def open_slots(self) -> int:
        return self.total_slots - self.filled_slots

    @property
    def figures_suspect(self) -> bool:
        """True when a negative amount is in this team's roster, so its money cannot be trusted.

        A negative price is never real. Once one is in the ledger, ``spent`` is too small,
        ``remaining`` too large, and :attr:`max_bid` is derived from both -- the whole team's
        arithmetic is downstream of a number that cannot happen.

        This exists because clamping alone was not enough. The fold alerts on the negative
        amount, but the consumers that act on the figures read the numbers and not
        ``state.alerts``. Those consumers are :mod:`draft_intel.quant.affordability` and
        ``cli.replay`` -- **not** the optimizer, which an earlier version of this note claimed
        and which takes a plain ``budget: int`` and never sees a ``TeamState`` at all.
        A bounded-but-wrong figure is *more* dangerous than an absurd one: ``$686`` in a $200
        league announces itself, ``$186`` does not. So the suspicion travels with the figures.
        """
        return any(held.amount < 0 for held in self.roster)

    @property
    def max_bid(self) -> int:
        """Most this team can bid while still reserving $1 for every other open slot.

        Zero when the roster is full; never negative; **never more than the team's whole
        budget**, whatever the ledger says was spent.

        That last clause bounds corrupt input rather than describing arithmetic. A negative
        amount -- a sign-flipped correction, a hand-typed ``-500`` -- makes ``spent`` negative
        and ``remaining`` larger than the budget, and this returned **$686 in a $200 league**.

        **The bound is a floor on the damage, not a repair, and it is deliberately paired with
        :attr:`figures_suspect`.** It only binds when the negative amount dominates the whole
        roster sum; with $100 of real spend and a -$40 entry the ledger reports $60 spent and
        this returns $127 against a true $47, and no clamp can recover that -- the information
        was destroyed at ingestion. Reading the bound as a fix is the mistake; what makes the
        figure safe to publish is that it arrives labelled.

        ``spent`` and ``remaining`` still report exactly what the ledger folded. Hiding the
        corruption is how it survives to draft night.
        """
        if self.open_slots <= 0:
            return 0
        return max(0, min(self.remaining, self.budget) - (self.open_slots - 1))

    @property
    def keepers(self) -> tuple[RosterEntry, ...]:
        return tuple(r for r in self.roster if r.pick_class is PickClass.KEEPER)


class DerivedState(Frozen):
    """The complete result of folding the event log. Always recomputed, never patched.

    ``teams`` and ``competitive_seq`` are annotated ``Mapping``, so ``mypy --strict`` refuses
    item assignment statically, and hold a :class:`FrozenDict`, which refuses every mutating
    operation at runtime. Neither guarantee is sufficient alone: the annotation cannot see
    dynamic access, and the runtime guard is only ever as complete as its method list.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    teams: Teams
    competitive_seq: CompetitiveSeq
    """Dense 1..N index over COMPETITIVE picks, in pick order.

    **Recomputed on every fold and deliberately not stable across folds.** Reclassifying or
    reversing a pick renumbers every competitive pick after it, which is semantically correct
    -- a pick that is no longer competitive should not occupy a position in the competitive
    sequence. The constraint this places on consumers is absolute: **never persist, cache or
    key long-lived state on a ``competitive_seq`` value.** Recompute time series wholesale
    from the current fold. See ADR-0001.
    """

    override_delta: int
    superseded: tuple[str, ...]
    alerts: tuple[str, ...]

    rejects: tuple[str, ...] = ()
    """Rows the poller could not parse faithfully, carried through from ingestion.

    Wired end to end: a dropped row takes its dollars with it, so the loss must be visible
    somewhere a consumer actually looks. Previously this field existed and was assigned by
    nothing.
    """

    orphans: tuple[str, ...] = ()
    """Events naming a draft slot outside the league.

    Their money is deliberately NOT applied to any team -- minting a phantom $200 team made
    the conservation identity meaningless, since bad input controlled the team count. The
    money is reported here and alerted instead of being silently absorbed.
    """

    @property
    def total_spent(self) -> int:
        return sum(t.spent for t in self.teams.values())

    @property
    def total_remaining(self) -> int:
        return sum(t.remaining for t in self.teams.values())

    def keeper_spend(self) -> int:
        return sum(
            r.amount
            for t in self.teams.values()
            for r in t.roster
            if r.pick_class is PickClass.KEEPER
        )
