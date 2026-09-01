"""Turning raw picks payloads into events by diffing whole snapshots.

Sleeper's picks array is not append-only. Commissioners reverse picks, which makes it
shrink, and correct amounts in place, which changes it without changing its length. Naive
append-only ingestion corrupts state the first time either happens, so every poll diffs the
complete array against the previous one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from draft_intel.models import Event, PickAmended, PickObserved, PickRemoved, PickSnapshot


@dataclass
class ParseResult:
    """Parsed picks plus a record of everything that could not be parsed.

    The rejects channel exists because silence here loses money. A row dropped for a missing
    ``player_id`` takes its dollars with it, and an unparseable amount books a real bid as $0.
    Neither should be inferable only from a total that looks slightly wrong.
    """

    picks: dict[int, PickSnapshot] = field(default_factory=dict)
    rejects: list[str] = field(default_factory=list)


def parse_amount(raw: Any) -> tuple[int, str | None]:
    """Parse ``metadata.amount`` into ``(dollars, complaint)``.

    Sleeper sends the winning bid as a string. Never raises -- a malformed amount must not
    take the poller down mid-draft -- but every value it could not read faithfully comes back
    with a complaint so the caller can surface it.

    ``"35.0"``, ``"$35"`` and ``"1e2"`` all previously parsed to ``$0`` in silence. They now
    parse to their real value where that is unambiguous, and complain where it is not.
    """
    if raw is None:
        return 0, "amount is null"
    if isinstance(raw, bool):  # bool is an int subclass; a bool here is never a bid
        return 0, f"amount is a bool ({raw!r})"
    if isinstance(raw, int):
        return raw, None
    text = str(raw).strip()
    if not text:
        return 0, "amount is empty"
    cleaned = text.removeprefix("$").replace(",", "")
    try:
        return int(cleaned), None
    except ValueError:
        pass
    try:
        value = float(cleaned)
    except ValueError:
        return 0, f"amount {text!r} is unparseable"
    if value != int(value):
        return int(value), f"amount {text!r} is fractional; truncated to {int(value)}"
    return int(value), None


def parse_pick(raw: dict[str, Any]) -> tuple[PickSnapshot | None, str | None]:
    """Build a :class:`PickSnapshot` from one element of the picks feed.

    Returns ``(pick, complaint)``. Never raises: one malformed row must not stop a poll cycle
    mid-draft, so validation failures come back as a complaint for the caller to surface.

    Team identity comes from ``draft_slot``, falling back to ``metadata.slot``. It is
    deliberately never taken from ``roster_id``: mock drafts return null for it (see
    docs/api-findings.md, Finding 4), which would null out every pick in our replay fixture.
    """
    meta = raw.get("metadata") or {}
    slot = raw.get("draft_slot") or meta.get("slot")
    player_id = raw.get("player_id") or meta.get("player_id")
    pick_no = raw.get("pick_no")
    missing = [
        name
        for name, value in (("draft_slot", slot), ("player_id", player_id), ("pick_no", pick_no))
        if value is None
    ]
    if missing or slot is None or player_id is None or pick_no is None:
        return None, f"pick {raw.get('pick_no', '?')} is missing {', '.join(missing)}"

    amount, complaint = parse_amount(meta.get("amount"))
    name = f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip()
    try:
        pick = PickSnapshot(
            pick_no=int(pick_no),
            player_id=str(player_id),
            slot=int(slot),
            amount=amount,
            is_keeper=bool(raw.get("is_keeper")),
            position=str(meta.get("position") or ""),
            name=name,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        return None, f"pick {pick_no} failed validation: {exc}"
    if complaint:
        return pick, f"pick {pick.pick_no} ({name or player_id}): {complaint}"
    return pick, None


def parse_picks(payload: list[dict[str, Any]]) -> ParseResult:
    """Parse a whole payload, recording rather than swallowing every malformed entry."""
    result = ParseResult()
    for raw in payload:
        pick, complaint = parse_pick(raw)
        if complaint:
            result.rejects.append(complaint)
        if pick is not None:
            result.picks[pick.pick_no] = pick
    return result


def diff_snapshots(
    previous: dict[int, PickSnapshot], current: dict[int, PickSnapshot]
) -> list[Event]:
    """Emit the events that carry ``previous`` to ``current``.

    Keyed on ``pick_no``. New numbers are observations, vanished numbers are reversals, and
    numbers whose contents changed are amendments.
    """
    events: list[Event] = []
    for pick_no in sorted(current):
        pick = current[pick_no]
        before = previous.get(pick_no)
        if before is None:
            events.append(PickObserved(pick=pick))
        elif before.player_id != pick.player_id:
            # The same pick number now names a different player. That is a renumbering, not
            # an amendment: treating it as one would silently re-point the pick's identity,
            # so any earlier reclassification of pick_no would land on the wrong player.
            events.append(PickRemoved(pick_no=pick_no))
            events.append(PickObserved(pick=pick))
        elif before != pick:
            events.append(PickAmended(pick=pick))
    for pick_no in sorted(previous):
        if pick_no not in current:
            events.append(PickRemoved(pick_no=pick_no))
    return events
