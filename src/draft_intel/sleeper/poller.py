"""Turning raw picks payloads into events by diffing whole snapshots.

Sleeper's picks array is not append-only. Commissioners reverse picks, which makes it
shrink, and correct amounts in place, which changes it without changing its length. Naive
append-only ingestion corrupts state the first time either happens, so every poll diffs the
complete array against the previous one.
"""

from __future__ import annotations

from typing import Any

from draft_intel.models import Event, PickAmended, PickObserved, PickRemoved, PickSnapshot


def parse_amount(raw: Any) -> int:
    """Parse ``metadata.amount``, which is a string and is not always present.

    Returns 0 for null, empty or unparseable values rather than raising. A missing amount
    is a data problem to surface upstream, not a reason to take the poller down mid-draft.
    """
    if raw is None:
        return 0
    if isinstance(raw, int):
        return raw
    try:
        return int(str(raw).strip() or 0)
    except ValueError:
        return 0


def parse_pick(raw: dict[str, Any]) -> PickSnapshot | None:
    """Build a :class:`PickSnapshot` from one element of the picks feed.

    Team identity comes from ``draft_slot``, falling back to ``metadata.slot``. It is
    deliberately never taken from ``roster_id``: mock drafts return null for it (see
    docs/api-findings.md, Finding 4), which would null out every pick in our replay fixture.
    """
    meta = raw.get("metadata") or {}
    slot = raw.get("draft_slot") or meta.get("slot")
    player_id = raw.get("player_id") or meta.get("player_id")
    pick_no = raw.get("pick_no")
    if slot is None or player_id is None or pick_no is None:
        return None
    name = f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip()
    return PickSnapshot(
        pick_no=int(pick_no),
        player_id=str(player_id),
        slot=int(slot),
        amount=parse_amount(meta.get("amount")),
        is_keeper=bool(raw.get("is_keeper")),
        position=str(meta.get("position") or ""),
        name=name,
    )


def parse_picks(payload: list[dict[str, Any]]) -> dict[int, PickSnapshot]:
    """Parse a whole payload, skipping malformed entries rather than failing the poll."""
    out: dict[int, PickSnapshot] = {}
    for raw in payload:
        pick = parse_pick(raw)
        if pick is not None:
            out[pick.pick_no] = pick
    return out


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
        elif before != pick:
            events.append(PickAmended(pick=pick))
    for pick_no in sorted(previous):
        if pick_no not in current:
            events.append(PickRemoved(pick_no=pick_no))
    return events
