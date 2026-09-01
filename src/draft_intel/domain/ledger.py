"""Derived state as a pure fold over the event log.

The whole design rests on one equation::

    derived_state = f(api_events + override_events)

Nothing is ever patched in place. A full refold of a 160-pick draft costs microseconds, and
buying that recomputation makes the hard guarantees free rather than hard-won: pick
reversal, restart recovery, retroactive reclassification and override commutativity are all
automatic because there is no incremental state left to corrupt.

Money is uniform. Every team's ledger starts at the same budget and is decremented by the
amount of every pick attributed to them, keeper or competitive alike. There is deliberately
no keeper branch in this module.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from draft_intel.models import (
    BudgetAdjustment,
    DerivedState,
    Event,
    ManualKeeper,
    PickAmended,
    PickClass,
    PickObserved,
    PickRemoved,
    PickSnapshot,
    Reclassify,
    Revert,
    RosterEntry,
    TeamState,
)

Classifier = Callable[[PickSnapshot], PickClass]


def _default_classifier(pick: PickSnapshot) -> PickClass:
    return PickClass.KEEPER if pick.is_keeper else PickClass.COMPETITIVE


def fold(
    events: Iterable[Event],
    *,
    slots: Iterable[int],
    budget: int = 200,
    total_slots: int = 16,
    classifier: Classifier | None = None,
    max_keepers: int = 2,
) -> DerivedState:
    """Replay ``events`` into a :class:`DerivedState`.

    Args:
        events: The full log, in sequence order.
        slots: Every draft slot in the league, so empty teams still appear.
        budget: Starting budget per team.
        total_slots: Draftable roster spots per team.
        classifier: Maps a pick to its class before any manual reclassification. Defaults
            to trusting ``is_keeper``, which on real Sleeper data classifies nothing -
            callers pass the manifest-backed classifier.
        max_keepers: Alert threshold; a team may never hold more than this many keepers.
    """
    classify = classifier or _default_classifier

    reverted = {e.target_seq for e in events if isinstance(e, Revert)}

    picks: dict[int, PickSnapshot] = {}
    reclass: dict[int, PickClass] = {}
    manual: dict[tuple[int, str], ManualKeeper] = {}
    adjustments: dict[int, int] = {}

    for event in events:
        if event.seq in reverted or isinstance(event, Revert):
            continue
        match event:
            case PickObserved() | PickAmended():
                picks[event.pick.pick_no] = event.pick
            case PickRemoved():
                picks.pop(event.pick_no, None)
            case Reclassify():
                reclass[event.pick_no] = event.pick_class
            case ManualKeeper():
                # Re-entering the same keeper replaces it rather than double-counting.
                manual[(event.slot, event.player_id)] = event
            case BudgetAdjustment():
                adjustments[event.slot] = adjustments.get(event.slot, 0) + event.delta

    # Supersession: a real pick always beats a manual assertion of the same player for the
    # same team. The risk here is never erasure, it is double-counting.
    superseded: list[str] = []
    alerts: list[str] = []
    real_keys = {(p.slot, p.player_id) for p in picks.values()}
    for key, entry in list(manual.items()):
        if key not in real_keys:
            continue
        del manual[key]
        actual = next(p for p in picks.values() if (p.slot, p.player_id) == key)
        superseded.append(
            f"slot {entry.slot} / {entry.player_id} - manual ${entry.amount} "
            f"superseded by pick at ${actual.amount}"
        )
        if actual.amount != entry.amount:
            alerts.append(
                f"AMOUNT MISMATCH slot {entry.slot} / {entry.player_id}: "
                f"manual ${entry.amount} vs pick ${actual.amount} - the pick wins"
            )

    ordered = sorted(picks.values(), key=lambda p: p.pick_no)
    classes = {p.pick_no: reclass.get(p.pick_no) or classify(p) for p in ordered}

    # Time-series analytics key on this dense index over competitive picks only. Using
    # pick_no instead would make Case A and Case B diverge, because ceremonial keeper picks
    # occupy the first 20 pick numbers in Case B and shift everything after them.
    competitive_seq = {
        p.pick_no: i
        for i, p in enumerate(
            (p for p in ordered if classes[p.pick_no] is PickClass.COMPETITIVE), start=1
        )
    }

    rosters: dict[int, list[RosterEntry]] = {slot: [] for slot in slots}
    for pick in ordered:
        rosters.setdefault(pick.slot, []).append(
            RosterEntry(
                player_id=pick.player_id,
                amount=pick.amount,
                pick_class=classes[pick.pick_no],
                pick_no=pick.pick_no,
            )
        )
    for entry in manual.values():
        rosters.setdefault(entry.slot, []).append(
            RosterEntry(
                player_id=entry.player_id,
                amount=entry.amount,
                pick_class=PickClass.KEEPER,
                manual=True,
            )
        )

    teams: dict[int, TeamState] = {}
    for slot, roster in sorted(rosters.items()):
        state = TeamState(
            slot=slot,
            budget=budget + adjustments.get(slot, 0),
            spent=sum(r.amount for r in roster),
            roster=tuple(roster),
            total_slots=total_slots,
        )
        teams[slot] = state
        if len(state.keepers) > max_keepers:
            alerts.append(f"slot {slot} holds {len(state.keepers)} keepers, limit is {max_keepers}")
        if state.remaining < 0:
            alerts.append(f"slot {slot} is overdrawn by ${-state.remaining}")

    return DerivedState(
        teams=teams,
        competitive_seq=competitive_seq,
        override_delta=sum(adjustments.values()),
        superseded=tuple(superseded),
        alerts=tuple(alerts),
    )
