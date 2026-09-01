"""Mapping between draft slots, roster ids and the owner names on the manifest.

``draft_slot`` is the canonical key everywhere in this system. Sleeper returns
``roster_id: null`` and ``picked_by: ""`` on mock drafts (docs/api-findings.md, Finding 4),
so a ledger keyed on ``roster_id`` produces nothing at all on our only real replay fixture.

The mapping is late-bound on purpose. Only four of ten managers have joined the real league,
so slot-to-owner is incomplete today and will keep changing until draft day. Nothing may
cache it as a startup constant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Identity:
    """Resolved slot mappings for one draft."""

    slot_to_roster: dict[int, int]
    slot_to_owner: dict[int, str]
    owner_to_slot: dict[str, int]

    def slot_for(self, owner: str) -> int | None:
        return self.owner_to_slot.get(owner)

    def owner_for(self, slot: int) -> str:
        return self.slot_to_owner.get(slot, f"slot {slot}")


def build_identity(
    draft: dict[str, Any],
    *,
    aliases: dict[str, str] | None = None,
) -> Identity:
    """Resolve slot mappings from a draft object.

    Owner names come from ``draft.metadata.slot_name_{n}``. The manifest uses the user's own
    label for themselves ("Me") while Sleeper carries their display name ("Matt"), so an
    alias table maps manifest owner to draft name.

    Args:
        draft: A ``GET /draft/{id}`` payload.
        aliases: Manifest owner name to draft slot name, e.g. ``{"Me": "Matt"}``.
    """
    aliases = aliases or {}
    metadata = draft.get("metadata") or {}
    raw_slot_to_roster = draft.get("slot_to_roster_id") or {}
    slot_to_roster = {int(k): int(v) for k, v in raw_slot_to_roster.items() if v is not None}

    slot_to_owner: dict[int, str] = {}
    for key, value in metadata.items():
        if key.startswith("slot_name_") and value:
            slot_to_owner[int(key.removeprefix("slot_name_"))] = str(value)

    by_name = {name: slot for slot, name in slot_to_owner.items()}
    owner_to_slot = dict(by_name)
    for manifest_owner, draft_name in aliases.items():
        if draft_name in by_name:
            owner_to_slot[manifest_owner] = by_name[draft_name]
    return Identity(
        slot_to_roster=slot_to_roster,
        slot_to_owner=slot_to_owner,
        owner_to_slot=owner_to_slot,
    )


def manifest_keys(
    resolved: dict[tuple[str, str], Any], identity: Identity
) -> frozenset[tuple[int, str]]:
    """Convert resolved manifest entries into the ``(slot, player_id)`` keys the classifier uses.

    Entries whose owner cannot be mapped to a slot are dropped rather than guessed at - an
    unmapped owner means the manager has not joined yet, and inventing a slot for them would
    misattribute a keeper.
    """
    keys: set[tuple[int, str]] = set()
    for (owner, player_id), _entry in resolved.items():
        slot = identity.slot_for(owner)
        if slot is not None:
            keys.add((slot, player_id))
    return frozenset(keys)
