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
4. Armed keeper mode with an unmatched early pick, flagged for confirmation.
5. Competitive.

Ordering 2 above 3 is not stylistic. In the user's own mock draft all twenty ceremonial
keeper picks arrive with ``is_keeper: false`` (docs/api-findings.md, Finding 5), so the
manifest is the only mechanism that fires on real data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from draft_intel.models import PickClass, PickSnapshot


@dataclass(frozen=True)
class KeeperClassifier:
    """Classifies picks against the resolved keeper manifest.

    Args:
        manifest_keys: ``(slot, player_id)`` pairs expected to be keepers.
        armed: Whether keeper mode is armed. While armed, an unmatched pick inside the
            arming window is flagged for confirmation rather than silently treated as a
            competitive bid - the backstop for a late keeper swap nobody told the user about.
        arming_window: How many early picks the arming switch covers. Defaults to two per
            team, the size of a full ceremonial round.
    """

    manifest_keys: frozenset[tuple[int, str]] = field(default_factory=frozenset)
    armed: bool = False
    arming_window: int = 20

    def __call__(self, pick: PickSnapshot) -> PickClass:
        if (pick.slot, pick.player_id) in self.manifest_keys:
            return PickClass.KEEPER
        if pick.is_keeper:
            return PickClass.KEEPER
        if self.armed and pick.pick_no <= self.arming_window:
            return PickClass.FLAGGED
        return PickClass.COMPETITIVE


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
