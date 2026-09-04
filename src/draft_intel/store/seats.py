"""Seat assignments typed on draft night, when a manager joins under a name nobody predicted.

**This exists because the failure already happened once and cost days.** `keenankid17` and
`willdeann` were sitting in the draft room, drafting, for days — and invisible to the tool,
because `config/owners.yaml` mapped manifest owners to Sleeper *display names* and nobody had
told it those two. Four keepers stayed unresolved the whole time while the page looked healthy.

That is guaranteed to repeat on the night. Burt, Connor and TD have no alias at all: whatever
display names they pick when they join at 6:55pm, the alias table will not know them, six
keepers will classify as competitive bids, and inflation, skew and every threat read inherits
it. The only fix available before this module was to edit YAML and restart the process, in the
middle of an auction.

So a seat assignment is a direct statement — *slot 9 is Burt* — that bypasses display-name
resolution entirely. It is applied **after** :func:`~draft_intel.domain.identity.build_identity`
and wins over it, because a person looking at the draft room knows who is in seat 9 and the API
demonstrably may not.

Persisted, for the same reason overrides are: a restart at 8pm must not lose what you typed at
7:10. Same file idiom, same "every read goes to disk" rule, so a hand edit is never ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from draft_intel.domain.identity import Identity

DEFAULT_PATH = Path("config/seats.yaml")

HEADER = """\
# Seat assignments: which manifest owner is sitting in which draft slot.
#
# Written by the cockpit and safe to edit by hand. Each line overrides whatever the Sleeper
# roster/user join resolved for that slot -- you are looking at the draft room and it is not.
#
# This is the fix for a manager who joins under a display name `config/owners.yaml` does not
# know. Without it their keepers classify as competitive bids, which corrupts inflation, skew
# and every threat read for the rest of the night, with nothing on the page looking wrong.
#
#   slot:  the draft slot, 1..teams. What the picks feed calls `draft_slot`.
#   owner: the name as it appears in config/keepers.yaml -- NOT their Sleeper display name.
#   note:  who confirmed it and how. A wrong seat here hands two keepers to the wrong team.
"""


class SeatAssignment(BaseModel):
    """One slot, claimed by one manifest owner."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slot: int = Field(ge=1)
    owner: str = Field(min_length=1)
    note: str = ""


class SeatStore:
    """Reads and writes ``config/seats.yaml``. Every read goes to disk."""

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)

    def load(self) -> dict[int, SeatAssignment]:
        if not self.path.exists():
            return {}
        raw: Any = yaml.safe_load(self.path.read_text()) or {}
        out: dict[int, SeatAssignment] = {}
        for entry in raw.get("seats") or []:
            seat = SeatAssignment.model_validate(entry)
            out[seat.slot] = seat
        return out

    def assign(self, seat: SeatAssignment) -> dict[int, SeatAssignment]:
        current = self.load()
        current[seat.slot] = seat
        self._write(current)
        return current

    def clear(self, slot: int) -> dict[int, SeatAssignment]:
        current = self.load()
        current.pop(slot, None)
        self._write(current)
        return current

    def _write(self, seats: dict[int, SeatAssignment]) -> None:
        payload = {"seats": [seat.model_dump() for _slot, seat in sorted(seats.items())]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(HEADER + yaml.safe_dump(payload, sort_keys=False, width=100))


def apply_seats(identity: Identity, seats: dict[int, SeatAssignment]) -> Identity:
    """Overlay hand-typed seats onto a resolved identity. The user wins.

    Returns a new :class:`Identity` rather than mutating: the resolved one is what the API
    actually said, and keeping the two separable is what lets the page show that a seat was
    asserted rather than observed.

    **An owner can only sit in one seat.** Assigning somebody to slot 9 removes them from
    whatever seat resolution had put them in, because leaving both would let
    ``owner_to_slot`` and ``slot_to_owner`` disagree — and the keeper classifier reads one
    while the threat ladder reads the other, so they would quietly describe different drafts.
    """
    if not seats:
        return identity

    slot_to_owner = dict(identity.slot_to_owner)

    # Vacate first, assert second. An owner resolution had put in slot 5 who is asserted into
    # slot 8 must *leave* slot 5 -- and slot 5 becomes unknown rather than inheriting anybody,
    # because if the assertion is right then whatever the API said about slot 5 was wrong and
    # there is no second source to fall back on. Saying "slot 5" is honest; leaving the name
    # there puts two teams on the threat ladder under one manager's name while the keeper
    # classifier follows only one of them.
    asserted = {seat.owner for seat in seats.values()}
    for slot in [s for s, owner in slot_to_owner.items() if owner in asserted and s not in seats]:
        del slot_to_owner[slot]
    for slot, seat in seats.items():
        slot_to_owner[slot] = seat.owner

    # Rebuild the reverse map from scratch. Patching it in place is what leaves an owner in two
    # seats: the resolved entry survives alongside the asserted one.
    owner_to_slot = {owner: slot for slot, owner in sorted(slot_to_owner.items())}
    for manifest_owner, resolved_slot in identity.owner_to_slot.items():
        # An alias survives only while the seat it named still exists and was not reassigned.
        # `owner_to_slot` carries both Sleeper display names and manifest owner names, so an
        # alias pointing at a vacated seat is exactly as stale as the seat itself.
        if (
            manifest_owner in owner_to_slot
            or resolved_slot in seats
            or resolved_slot not in slot_to_owner
        ):
            continue
        owner_to_slot[manifest_owner] = resolved_slot

    return Identity(
        slot_to_roster=dict(identity.slot_to_roster),
        slot_to_owner=slot_to_owner,
        owner_to_slot=owner_to_slot,
    )
