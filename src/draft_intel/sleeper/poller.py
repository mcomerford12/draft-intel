"""Turning raw picks payloads into events by diffing whole snapshots.

Sleeper's picks array is not append-only. Commissioners reverse picks, which makes it
shrink, and correct amounts in place, which changes it without changing its length. Naive
append-only ingestion corrupts state the first time either happens, so every poll diffs the
complete array against the previous one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from draft_intel.models import Event, PickAmended, PickObserved, PickRemoved, PickSnapshot

# Deliberately strict: a bid is an integer number of dollars. Scientific notation, hex,
# underscores and non-ASCII digits are all refused rather than coerced into a wrong number.
_INTEGER = re.compile(r"[+-]?[0-9]{1,9}")
_DECIMAL = re.compile(r"[+-]?[0-9]{1,9}\.[0-9]{1,9}")


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

    Sleeper sends the winning bid as a string. **This function never raises**, because one
    malformed row must not take the poll cycle down mid-draft, and every value it could not
    read faithfully comes back with a complaint for the caller to surface.

    Only a plain integer is accepted, after stripping a leading ``$`` and any thousands
    commas. Everything else is refused loudly rather than coerced. An earlier version routed
    unparseable text through ``float()``, which both raised on ``"inf"`` / ``"nan"`` /
    ``"1e400"`` and silently accepted ``"1e2"`` as 100 -- a plausible-looking wrong number,
    which is the failure this module exists to prevent.

    The negative guard is applied here, once, to whatever the arms below return. It was
    previously written into the integer arm only, so ``"-500"`` was caught while
    ``"-500.0"``, ``"-5.0"`` and the float ``-5.0`` all passed silently -- and a negative
    keeper price produces a $686 max bid in a $200 league. A single exit is the only version
    of this check that a fifth parsing arm cannot be added around.
    """
    value, complaint = _read_amount(raw)
    if value < 0:
        negative = f"amount is negative ({value})"
        return value, negative if complaint is None else f"{complaint}; {negative}"
    return value, complaint


def _read_amount(raw: Any) -> tuple[int, str | None]:
    """Read a value without judging its sign; see :func:`parse_amount`."""
    if raw is None:
        return 0, "amount is null"
    if isinstance(raw, bool):  # bool is an int subclass; a bool here is never a bid
        return 0, f"amount is a bool ({raw!r})"
    if isinstance(raw, int):
        return raw, None
    if isinstance(raw, float):
        if raw != raw or raw in (float("inf"), float("-inf")):
            return 0, f"amount is not a finite number ({raw!r})"
        if raw != int(raw):
            return int(raw), f"amount {raw!r} is fractional; truncated to {int(raw)}"
        return int(raw), None

    text = str(raw).strip()
    if not text:
        return 0, "amount is empty"
    cleaned = text.removeprefix("$").replace(",", "")
    if _INTEGER.fullmatch(cleaned):
        return int(cleaned), None
    if _DECIMAL.fullmatch(cleaned):
        whole, _, frac = cleaned.partition(".")
        value = int(whole or "0")
        if int(frac or "0") == 0:
            return value, None
        # Truncate toward zero, so "-0.5" stays negative rather than reading as a clean $0
        # and losing the sign the guard above is looking for.
        if cleaned.startswith("-") and value == 0:
            return 0, f"amount {text!r} is negative and fractional; truncated to 0"
        return value, f"amount {text!r} is fractional; truncated to {value}"
    return 0, f"amount {text!r} is unparseable"


def _present(*values: Any) -> Any:
    """The first value that is genuinely present, or ``None``.

    **Sleeper's empty value for a string field is ``""``, not ``null``**, and it uses it
    liberally: in `fixtures/picks.json`, `picked_by`, `team_abbr` and `team_changed_at` are
    empty on all 160 rows and `injury_status` on 122. So "absent" has two spellings, and a
    guard that tests only ``is None`` accepts the other one as real data.

    That was not theoretical. With ``player_id: null`` at the top level and ``metadata.
    player_id: ""``, the fallback selected ``""`` and the missing-field guard let it through:
    a ``PickSnapshot`` with **no player** entered the ledger, complaint-free. The bought player
    was not on anybody's roster, the room still totalled $1,979, and nothing alerted -- so the
    board went on showing a rostered player as available and the tool would have recommended
    bidding on him. Money conservation holding exactly while the ledger is nonsense is the
    charter's named failure mode, and this is it, in the field DI-053 added a cross-check for.

    Whitespace counts as empty for the same reason a hand-typed " " is not a player id.

    **Zero counts as absent too**, which is a judgement rather than an obvious rule. All three
    fields this guards -- ``draft_slot``, ``player_id``, ``pick_no`` -- are 1-based identifiers,
    so ``0`` is never a value any of them can legitimately take; ``Slot`` itself validates
    ``ge=1``. Reading it as present means a ``draft_slot: 0`` row is refused outright and takes
    its dollars with it, when the ``metadata.slot`` beside it says exactly which team bought the
    player. Falling back keeps the pick, keeps the money, and keeps the roster spot. If both
    sources are empty the missing-field guard still fires, which is the case that matters.
    """
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if not value.strip():
                continue
        elif not value:
            continue
        return value
    return None


def parse_pick(raw: dict[str, Any]) -> tuple[PickSnapshot | None, str | None]:
    """Build a :class:`PickSnapshot` from one element of the picks feed.

    Returns ``(pick, complaint)``. Never raises: one malformed row must not stop a poll cycle
    mid-draft, so validation failures come back as a complaint for the caller to surface.

    Team identity comes from ``draft_slot``, falling back to ``metadata.slot``. It is
    deliberately never taken from ``roster_id``: mock drafts return null for it (see
    docs/api-findings.md, Finding 4), which would null out every pick in our replay fixture.

    **Both duplicated fields are cross-checked, not merely fallen back on.** The Sprint 1 design
    said ``metadata.slot`` "duplicates ``draft_slot`` and is used as a cross-check"; what shipped
    was ``a or b``, which takes the primary and never looks at the duplicate again. A payload
    where the two disagree parsed clean and silent.

    Both disagreements are the failure mode the charter cares about, because neither shows up in
    money conservation. A wrong ``slot`` debits the wrong team -- the total still reconciles to
    $2,000 while two managers' budgets, max bids and affordability figures are all wrong. A wrong
    ``player_id`` leaves the player who was actually bought sitting on our available board, so
    the tool goes on recommending bids for somebody already rostered, and a keeper stops matching
    the manifest on ``(player_id, slot)``.

    The pick is kept and the primary field wins, rather than being dropped. We cannot tell which
    side of a conflict is right, and dropping loses a roster spot and its dollars *as well as*
    being wrong -- whereas a kept pick with a complaint is visible in ``state.rejects``, which
    ``cli.replay`` prints. Being wrong loudly beats being wrong quietly.
    """
    meta = raw.get("metadata") or {}
    slot = _present(raw.get("draft_slot"), meta.get("slot"))
    player_id = _present(raw.get("player_id"), meta.get("player_id"))
    pick_no = _present(raw.get("pick_no"))
    # The conflict test must use the same truthiness rule as the fallback two lines above, or
    # the two disagree about which value won. ``or`` falls through on any falsy primary, so
    # ``player_id: ""`` and ``draft_slot: 0`` take the metadata value -- while an
    # ``is not None`` test called them a conflict and reported "the primary field wins", which
    # was the opposite of what happened. Sleeper does send ``""`` for ``player_id`` on some
    # rows, so that was a spurious complaint on every poll, carrying a message that misstated
    # which number was in effect.
    conflicts = [
        f"{field} is {primary!r} but metadata says {duplicate!r}"
        for field, primary, duplicate in (
            ("draft_slot", _present(raw.get("draft_slot")), _present(meta.get("slot"))),
            ("player_id", _present(raw.get("player_id")), _present(meta.get("player_id"))),
        )
        if primary is not None and duplicate is not None and str(primary) != str(duplicate)
    ]
    # Same rule as `_present` above, or the guard disagrees with the selection it is guarding.
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
            conflicts=tuple(conflicts),
        )
    except (ValidationError, ValueError, TypeError) as exc:
        return None, f"pick {pick_no} failed validation: {exc}"
    grumbles = [*conflicts]
    if complaint:
        grumbles.append(complaint)
    if grumbles:
        return pick, f"pick {pick.pick_no} ({name or player_id}): {'; '.join(grumbles)}"
    return pick, None


def parse_picks(payload: list[dict[str, Any]]) -> ParseResult:
    """Parse a whole payload, recording rather than swallowing every malformed entry.

    The map is keyed on ``pick_no``, so two rows claiming one pick number collapse to the
    later of them. That collision is inherent to the key and is not itself the defect -- the
    defect was that it happened in silence, taking a real bid's dollars out of the ledger
    while conservation still appeared to hold. Two rows at ``pick_no`` 30 moved the fixture's
    total from $1,979 to $1,947 with zero rejects, zero orphans and zero alerts.
    """
    result = ParseResult()
    for raw in payload:
        pick, complaint = parse_pick(raw)
        if complaint:
            result.rejects.append(complaint)
        if pick is None:
            continue
        existing = result.picks.get(pick.pick_no)
        if existing is not None and existing != pick:
            result.rejects.append(
                f"pick {pick.pick_no} appears twice in one payload: "
                f"{existing.player_id} at ${existing.amount} (slot {existing.slot}), then "
                f"{pick.player_id} at ${pick.amount} (slot {pick.slot}) - the later row wins "
                f"and ${existing.amount} leaves the ledger"
            )
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
