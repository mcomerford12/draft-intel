"""Pick classification.

Every pick carries a class. Money, roster and slot math use all of them; auction analytics
use ``COMPETITIVE`` only. Without that filter, ceremonial keeper picks entered as ordinary
picks would be read as competitive bids and would quietly poison skew, inflation, run
detection and every manager tendency profile - producing a system that looks like it works
while giving bad advice all night.

Priority, highest first:

1. Manual reclassification - applied in the ledger fold, wins over everything here.
2. Manifest match on ``(slot, player_id)``.
3. ``is_keeper`` true.
4. Competitive.

Priority 5 in earlier versions -- the armed backstop, flagging an unmatched pick for
confirmation -- is no longer in this module. It needs pick order, which only the fold has, and
lives there as ``fold(flag_unmatched=...)``. See :func:`keepers_owed`.

Ordering 2 above 3 is not stylistic. In the user's own mock draft all twenty ceremonial
keeper picks arrive with ``is_keeper: false`` (docs/api-findings.md, Finding 5), so the
manifest is the only mechanism that fires on real data.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from draft_intel.models import PickClass, PickSnapshot


@dataclass(frozen=True)
class KeeperClassifier:
    """Classifies picks against the resolved keeper manifest.

    **This classifier never returns FLAGGED, and cannot.** The arming backstop used to live
    here as ``armed`` plus an ``arming_window`` of 20 picks, and DI-055 refused to ship it for
    a reason that was really about *where* it lived rather than whether it should exist: a
    ``Classifier`` is a pure function of one pick, so the only window it can express is a
    constant. ``pick_no <= 20`` is a fact about ``fixtures/picks.json``, not about any league.
    In a room whose ceremonial round sits anywhere else it flags twenty real bids, and in a
    room with no ceremonial round at all it deletes twenty competitive picks outright.

    A window that means "has this slot's ceremonial round happened yet" needs pick *order*,
    which exists only in the fold. So it lives there now, as ``fold(flag_unmatched=...)``,
    keyed on how many keepers each slot still owes. See :func:`draft_intel.domain.ledger.fold`.

    Args:
        manifest_keys: ``(slot, player_id)`` pairs expected to be keepers.
    """

    manifest_keys: frozenset[tuple[int, str]] = field(default_factory=frozenset)

    def __call__(self, pick: PickSnapshot) -> PickClass:
        if (pick.slot, pick.player_id) in self.manifest_keys:
            return PickClass.KEEPER
        if pick.is_keeper:
            return PickClass.KEEPER
        return PickClass.COMPETITIVE


def keepers_owed(slots: Iterable[int], *, keepers_per_team: int) -> dict[int, int]:
    """``slot -> ceremonial keepers expected``, the arming window's own definition.

    Derived from the league's ``keepers_per_team`` rather than from the resolved manifest, and
    the difference is the whole backstop. A manifest-derived count says slot 4 expects one
    keeper when one of its two was swapped after the file was written — so the swapped pick
    arrives with nothing owed and is silently counted as a competitive bid, which is precisely
    the case the backstop exists to catch. The league rule says two, and two is what the room
    will actually do.

    A league with no ceremonial round has ``keepers_per_team = 0``, so every slot expects zero
    and nothing is ever flagged. That is the generalisation the old constant could not express.

    The returned count does double duty in the fold: it is both how many keepers a slot still
    owes and how many of that slot's *own first picks* are candidates for flagging.
    """
    return {slot: keepers_per_team for slot in slots}


def reconcile(
    state_keepers: dict[int, list[tuple[str, int]]],
    expected: dict[int, list[tuple[str, int | None]]],
    *,
    keepers_per_team: int = 2,
) -> list[str]:
    """Compare recorded keepers against the manifest and report every divergence.

    These are the errors most likely to actually occur on draft night, they are quiet, and
    each one silently corrupts a team's budget for the rest of the evening. Catching them in
    the first three minutes is worth more than most of the analytics in the system.

    Args:
        state_keepers: Recorded keepers per slot, as ``(player_id, amount)``.
        expected: Manifest keepers per slot, as ``(player_id, expected_price_or_None)``.
    """
    alerts: list[str] = []
    for slot, want in sorted(expected.items()):
        have = dict(state_keepers.get(slot, []))
        want_ids = {pid for pid, _ in want}
        for pid, price in want:
            if pid not in have:
                alerts.append(f"slot {slot}: manifest keeper {pid} not recorded")
            elif price is not None and have[pid] != price:
                alerts.append(
                    f"slot {slot}: keeper {pid} loaded at ${have[pid]}, manifest says ${price}"
                )
        for pid in have:
            if pid not in want_ids:
                alerts.append(f"slot {slot}: keeper {pid} recorded but not on the manifest")
        if len(have) != keepers_per_team:
            alerts.append(f"slot {slot}: {len(have)} keepers recorded, expected {keepers_per_team}")
    return alerts


def keepers_seen(state_keepers: dict[int, list[tuple[str, int]]]) -> tuple[int, int]:
    """``(keepers recorded, teams with a full complement)`` for the N/20 readout."""
    total = sum(len(v) for v in state_keepers.values())
    complete = sum(1 for v in state_keepers.values() if len(v) == 2)
    return total, complete
