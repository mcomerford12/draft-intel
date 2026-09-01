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

**Every anomaly raises an alert.** The failure mode this module exists to prevent is not a
crash, it is a plausible-looking number that has been wrong since 7:40pm. Where the fold
cannot know the right answer it records what it saw and says so loudly, rather than picking
a silent default.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from draft_intel.models import (
    OVERRIDE_KINDS,
    UNSTAMPED,
    BudgetAdjustment,
    DerivedState,
    Event,
    FrozenDict,
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


def _ordered(events: Iterable[Event], alerts: list[str]) -> list[Event]:
    """Materialise and order the log by sequence number.

    Three defects are closed here. The input is consumed exactly once, so a generator folds
    the same as a list -- previously it was iterated twice and silently produced empty state.
    Ordering is by ``seq`` rather than list position, so an out-of-order splice (a replayed
    batch, a retry, a merge) cannot resurrect a removed pick. And ``UNSTAMPED`` events sort
    **last**, not first.

    That last point is subtle and cost a defect. ``seq == 0`` means "not yet through the
    store", which makes such an event *newer* than anything the store has numbered -- it was
    appended to an already-stamped log. Sorting zero first, as a naive numeric sort does, made
    an unstamped ``PickRemoved`` a silent no-op that then blamed a feed divergence which had
    not happened. Among themselves, unstamped events keep their arrival order.
    """
    materialised = list(events)
    seen: set[int] = set()
    for event in materialised:
        if event.seq == UNSTAMPED:
            continue
        if event.seq in seen:
            alerts.append(f"duplicate event seq {event.seq} ({event.kind}) - log is corrupt")
        seen.add(event.seq)

    def order(pair: tuple[int, Event]) -> tuple[int, int]:
        arrival, event = pair
        return (1, arrival) if event.seq == UNSTAMPED else (0, event.seq)

    return [event for _, event in sorted(enumerate(materialised), key=order)]


def _resolve_reverts(events: list[Event], alerts: list[str]) -> set[int]:
    """Work out which event sequence numbers are neutralised.

    A revert may target an override, or another revert (reinstating what that one undid).
    A revert aimed at a pick event is refused: the picks feed is the authority for money, and
    honouring it would let an override silently delete a team's spend.
    """
    by_seq = {e.seq: e for e in events if e.seq != UNSTAMPED}
    reverts = sorted((e for e in events if isinstance(e, Revert)), key=lambda e: e.seq)

    # Cancellation must be resolved transitively, to a fixed point, not in one flat pass.
    # A revert is active unless some *active* revert targets it. Because a revert can only
    # target something that already exists, every canceller has a higher seq than its target,
    # so walking from the highest seq down settles each one before it is needed.
    #
    # The previous single-pass version cancelled every revert that was targeted at all,
    # regardless of whether the canceller itself survived. That was correct at chain depths
    # 0-2 and silently wrong at every odd depth from 3 up: the override simply stayed applied.
    active: dict[int, bool] = {r.seq: True for r in reverts}
    for revert in sorted(reverts, key=lambda e: e.seq, reverse=True):
        if any(
            active[other.seq]
            for other in reverts
            if other.target_seq == revert.seq and other.seq > revert.seq
        ):
            active[revert.seq] = False

    reverted: set[int] = set()
    for revert in reverts:
        if not active[revert.seq]:
            continue
        if revert.target_seq == revert.seq:
            alerts.append(f"revert at seq {revert.seq} targets itself - ignored")
            continue
        if revert.target_seq == UNSTAMPED:
            alerts.append(
                "revert targets seq 0, which means 'unstamped' and is never a real event - ignored"
            )
            continue
        target = by_seq.get(revert.target_seq)
        if target is None:
            alerts.append(f"revert targets seq {revert.target_seq}, which is not in the log")
            continue
        if isinstance(target, Revert):
            continue  # its cancellation is carried by the `active` map above
        if target.kind not in OVERRIDE_KINDS:
            alerts.append(
                f"refused: revert of seq {revert.target_seq} ({target.kind}). Only "
                f"{sorted(OVERRIDE_KINDS)} may be reverted; the picks feed is authoritative"
            )
            continue
        reverted.add(target.seq)
    return reverted


def fold(
    events: Iterable[Event],
    *,
    slots: Iterable[int],
    budget: int = 200,
    total_slots: int = 16,
    classifier: Classifier | None = None,
    max_keepers: int = 2,
    expect_keepers: bool = False,
    rejects: Iterable[str] | None = None,
) -> DerivedState:
    """Replay ``events`` into a :class:`DerivedState`.

    Args:
        events: The log. Consumed once and ordered by ``seq``, so generators are safe.
        slots: Every draft slot in the league, so empty teams still appear. Any event naming
            a slot outside this set raises an alert.
        budget: Starting budget per team.
        total_slots: Draftable roster spots per team.
        classifier: Maps a pick to its class before any manual reclassification. Defaults to
            trusting ``is_keeper``, which on real Sleeper data classifies nothing -- callers
            pass the manifest-backed classifier.
        max_keepers: A team may hold no more than this many keepers.
        expect_keepers: When true, alert on teams holding *fewer* than ``max_keepers``. Set
            once the keeper phase should be complete; an under-count is as corrupting as an
            over-count and was previously invisible.
        rejects: Ingestion complaints from :func:`~draft_intel.sleeper.poller.parse_picks`,
            carried through so a dropped row and its lost dollars surface where a consumer
            looks. This channel existed and was fed by nothing.
    """
    classify = classifier or _default_classifier
    alerts: list[str] = []

    ordered_events = _ordered(events, alerts)
    reverted = _resolve_reverts(ordered_events, alerts)

    picks: dict[int, PickSnapshot] = {}
    reclass: dict[int, PickClass] = {}
    manual: dict[tuple[int, str], ManualKeeper] = {}
    adjustments: dict[int, int] = {}

    for event in ordered_events:
        if event.seq in reverted and event.seq != UNSTAMPED:
            continue
        match event:
            case PickObserved() | PickAmended():
                existing = picks.get(event.pick.pick_no)
                if isinstance(event, PickAmended) and existing is None:
                    alerts.append(
                        f"amendment for pick {event.pick.pick_no}, which was never observed - "
                        "the feed and the log have diverged"
                    )
                # A second *observation* of a pick number that already holds different
                # contents is not an amendment - nothing declared a correction. One of the
                # two is spurious and the loser's money silently leaves the ledger. An
                # identical re-observation is just an idempotent poll and stays quiet.
                elif (
                    isinstance(event, PickObserved)
                    and existing is not None
                    and existing != event.pick
                ):
                    alerts.append(
                        f"pick {event.pick.pick_no} observed twice with different contents: "
                        f"{existing.player_id} at ${existing.amount} then "
                        f"{event.pick.player_id} at ${event.pick.amount} - the later "
                        f"observation wins and ${existing.amount} leaves the ledger"
                    )
                picks[event.pick.pick_no] = event.pick
            case PickRemoved():
                if picks.pop(event.pick_no, None) is None:
                    alerts.append(
                        f"removal of pick {event.pick_no}, which is not in the log - "
                        "the feed and the log have diverged"
                    )
            case Reclassify():
                reclass[event.pick_no] = event.pick_class
            case ManualKeeper():
                manual[(event.slot, event.player_id)] = event
            case BudgetAdjustment():
                adjustments[event.slot] = adjustments.get(event.slot, 0) + event.delta
            case Revert():
                pass  # resolved above

    superseded: list[str] = []

    # Supersession keys on player_id alone, never on (slot, player_id). Slot-to-owner mapping
    # is late-bound and changes until draft day, so a manual entry and the feed can disagree
    # about the slot for the same player. Matching on the pair left both records alive: the
    # player on two rosters, the money charged twice, silently. Player identity is the thing
    # that is actually stable.
    # Lowest pick_no wins when a player somehow appears twice. Building the map in event
    # order made the winner depend on arrival order, so the same facts in a different sequence
    # produced a different supersession message.
    picks_by_player: dict[str, PickSnapshot] = {}
    for pick in sorted(picks.values(), key=lambda p: p.pick_no):
        picks_by_player.setdefault(pick.player_id, pick)
    for key, entry in list(manual.items()):
        actual = picks_by_player.get(entry.player_id)
        if actual is None:
            continue
        del manual[key]
        superseded.append(
            f"slot {entry.slot} / {entry.player_id} - manual ${entry.amount} "
            f"superseded by pick at ${actual.amount}"
        )
        if actual.slot != entry.slot:
            alerts.append(
                f"SLOT MISMATCH {entry.player_id}: entered manually for slot {entry.slot}, "
                f"pick landed on slot {actual.slot} - the pick wins"
            )
        if actual.amount != entry.amount:
            alerts.append(
                f"AMOUNT MISMATCH slot {actual.slot} / {entry.player_id}: "
                f"manual ${entry.amount} vs pick ${actual.amount} - the pick wins"
            )

    # A player may sit on exactly one roster. Nothing detected this before.
    owners: dict[str, list[int]] = {}
    for pick in picks.values():
        owners.setdefault(pick.player_id, []).append(pick.slot)
    for entry in manual.values():
        owners.setdefault(entry.player_id, []).append(entry.slot)
    for player_id, holders in sorted(owners.items()):
        if len(holders) > 1:
            alerts.append(
                f"player {player_id} is held by slots {sorted(holders)} - counted more than once"
            )

    ordered_picks = sorted(picks.values(), key=lambda p: p.pick_no)
    # A manual reclassification always wins. Tested with `is not None` rather than `or`
    # because relying on every PickClass member being truthy is a trap waiting for the day
    # someone adds a falsy one.
    classes: dict[int, PickClass] = {}
    for pick in ordered_picks:
        override = reclass.get(pick.pick_no)
        classes[pick.pick_no] = override if override is not None else classify(pick)

    competitive_seq = {
        p.pick_no: i
        for i, p in enumerate(
            (p for p in ordered_picks if classes[p.pick_no] is PickClass.COMPETITIVE), start=1
        )
    }

    # A slot outside the declared league gets NO team and NO budget. Minting one made the
    # conservation identity meaningless, because bad input controlled the team count and the
    # pot grew $200 at a time; counting its adjustment in override_delta broke reconciliation
    # the other way. Its money is reported in `orphans` and alerted, never silently absorbed.
    declared = set(slots)
    referenced = (
        {p.slot for p in picks.values()} | {e.slot for e in manual.values()} | set(adjustments)
    )
    orphans: list[str] = []
    for slot in sorted(referenced - declared):
        money = sum(p.amount for p in picks.values() if p.slot == slot)
        money += sum(e.amount for e in manual.values() if e.slot == slot)
        detail = f"${money} of picks" if money else "no picks"
        adjustment = adjustments.get(slot)
        if adjustment:
            detail += f" and a ${adjustment} budget adjustment"
        orphans.append(
            f"slot {slot} is not one of the league's {len(declared)} slots ({detail}) - "
            "not applied to any team; check for a mistyped slot"
        )
        alerts.append(orphans[-1])
    applied_adjustments = {s: d for s, d in adjustments.items() if s in declared}

    rosters: dict[int, list[RosterEntry]] = {slot: [] for slot in declared}
    for pick in ordered_picks:
        if pick.slot not in declared:
            continue
        rosters[pick.slot].append(
            RosterEntry(
                player_id=pick.player_id,
                amount=pick.amount,
                pick_class=classes[pick.pick_no],
                pick_no=pick.pick_no,
            )
        )
    for entry in manual.values():
        if entry.slot not in declared:
            continue
        rosters[entry.slot].append(
            RosterEntry(
                player_id=entry.player_id,
                amount=entry.amount,
                pick_class=PickClass.KEEPER,
                manual=True,
            )
        )

    teams_built: dict[int, TeamState] = {}
    for slot, roster in sorted(rosters.items()):
        state = TeamState(
            slot=slot,
            budget=budget + applied_adjustments.get(slot, 0),
            spent=sum(r.amount for r in roster),
            roster=tuple(roster),
            total_slots=total_slots,
        )
        teams_built[slot] = state
        # A negative amount is never a real price, on any path. The parser guards the feed,
        # but `ManualKeeper` -- the *primary* route by which real keeper prices enter, since
        # Sleeper publishes no auction value -- never touches the parser at all. A single
        # -$500 entry yielded spent -500, remaining 700 and a max bid of $686 in a $200
        # league, with no alert. The fold is the one point every path crosses, so the guard
        # belongs here rather than on each ingestion route.
        for held in roster:
            if held.amount < 0:
                # Prefixed like the other money alerts rather than "slot N holds ...", which
                # is already the prefix of both the keeper-limit and over-roster alerts. A
                # test in the suite matched on that shared prefix and would have started
                # passing for a third unrelated reason.
                alerts.append(
                    f"NEGATIVE AMOUNT slot {slot} / {held.player_id}: ${held.amount} is a "
                    "negative price, which is never real; every figure for this team is suspect"
                )
        keepers = len(state.keepers)
        if keepers > max_keepers:
            alerts.append(f"slot {slot} holds {keepers} keepers, limit is {max_keepers}")
        if expect_keepers and keepers < max_keepers:
            alerts.append(f"slot {slot} holds only {keepers} of {max_keepers} keepers")
        if state.remaining < 0:
            alerts.append(f"slot {slot} is overdrawn by ${-state.remaining}")
        if state.filled_slots > total_slots:
            alerts.append(
                f"slot {slot} holds {state.filled_slots} players, {total_slots} roster spots exist"
            )
        if state.open_slots > 0 and state.remaining < state.open_slots:
            alerts.append(
                f"slot {slot} has ${state.remaining} for {state.open_slots} open spots - "
                "cannot fill its roster at $1 each"
            )

    return DerivedState(
        teams=FrozenDict(teams_built),
        competitive_seq=FrozenDict(competitive_seq),
        # Every adjustment now lands on a team, so this is exactly the amount by which the
        # ledger legitimately departs from the full pot.
        override_delta=sum(applied_adjustments.values()),
        superseded=tuple(superseded),
        alerts=tuple(alerts),
        rejects=tuple(rejects or ()),
        orphans=tuple(orphans),
    )
