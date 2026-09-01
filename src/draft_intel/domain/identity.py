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

    def is_complete(self, teams: int) -> bool:
        """Whether every draft slot resolved to an owner."""
        return len(self.slot_to_owner) >= teams

    def unmapped_slots(self, teams: int) -> list[int]:
        return [s for s in range(1, teams + 1) if s not in self.slot_to_owner]


def build_identity(
    draft: dict[str, Any],
    *,
    rosters: list[dict[str, Any]] | None = None,
    users: list[dict[str, Any]] | None = None,
    aliases: dict[str, str] | None = None,
) -> Identity:
    """Resolve slot mappings from a draft object, with a roster/user fallback.

    Two independent sources, because relying on either alone is not safe:

    1. ``draft.metadata.slot_name_{n}``. Present on mock drafts. **Absent entirely on the
       real league draft object**, which carries only description, league_type, name and
       scoring_type.
    2. ``slot_to_roster_id`` joined through ``/league/{id}/rosters`` (roster_id to owner_id)
       and ``/league/{id}/users`` (user_id to display_name). Populated on the real league.

    Source 1 alone was a draft-night defect: against the real draft it resolves no owners at
    all, so the keeper manifest matches nothing and every ceremonial keeper is classified as
    a competitive bid. Callers must check :meth:`Identity.is_complete`.

    Args:
        draft: A ``GET /draft/{id}`` payload.
        rosters: ``GET /league/{id}/rosters``, for the fallback.
        users: ``GET /league/{id}/users``, for the fallback.
        aliases: Manifest owner name to Sleeper display name, e.g. ``{"Me": "Matt"}``.
    """
    aliases = aliases or {}
    metadata = draft.get("metadata") or {}
    raw_slot_to_roster = draft.get("slot_to_roster_id") or {}
    slot_to_roster = {int(k): int(v) for k, v in raw_slot_to_roster.items() if v is not None}

    slot_to_owner: dict[int, str] = {}
    for key, value in metadata.items():
        if key.startswith("slot_name_") and value:
            slot_to_owner[int(key.removeprefix("slot_name_"))] = str(value)

    if rosters and users:
        display = {
            str(u["user_id"]): str(u.get("display_name") or "") for u in users if u.get("user_id")
        }
        owner_of_roster = {
            int(r["roster_id"]): str(r["owner_id"])
            for r in rosters
            if r.get("roster_id") is not None and r.get("owner_id")
        }
        for slot, roster_id in slot_to_roster.items():
            if slot in slot_to_owner:
                continue  # draft metadata wins where it exists
            name = display.get(owner_of_roster.get(roster_id, ""))
            if name:
                slot_to_owner[slot] = name

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


class UnresolvedManifest(Exception):
    """Raised when the keeper manifest cannot be fully mapped onto draft slots."""


def manifest_keys(
    resolved: dict[tuple[str, str], Any],
    identity: Identity,
    *,
    require: int | None = None,
) -> frozenset[tuple[int, str]]:
    """Convert resolved manifest entries into the ``(slot, player_id)`` keys the classifier uses.

    Entries whose owner cannot be mapped to a slot are dropped rather than guessed at - an
    unmapped owner means the manager has not joined yet, and inventing a slot for them would
    misattribute a keeper to the wrong team.

    Dropping them silently was a draft-night defect. With ``require`` set, an incomplete
    resolution raises instead: a partial manifest means some ceremonial keepers will be read
    as competitive bids, which corrupts every auction statistic for the night while the tool
    continues to look healthy.

    Args:
        require: Expected number of keys, normally ``teams * keepers_per_team``. Raises
            :class:`UnresolvedManifest` naming the unmapped owners if fewer resolve.
    """
    keys: set[tuple[int, str]] = set()
    unmapped: set[str] = set()
    for (owner, player_id), _entry in resolved.items():
        slot = identity.slot_for(owner)
        if slot is None:
            unmapped.add(owner)
        else:
            keys.add((slot, player_id))
    if require is not None and len(keys) != require:
        raise UnresolvedManifest(
            f"resolved {len(keys)} of {require} keeper keys; "
            f"owners with no draft slot: {sorted(unmapped)}. "
            "Every unmapped keeper would be classified as a competitive bid and would poison "
            "skew, inflation and tendency statistics for the whole draft."
        )
    return frozenset(keys)
