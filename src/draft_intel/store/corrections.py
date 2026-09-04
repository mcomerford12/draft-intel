"""Corrections typed during the draft: a team's money, and a keeper the feed never delivered.

The ledger has taken :class:`~draft_intel.models.BudgetAdjustment`,
:class:`~draft_intel.models.ManualKeeper` and :class:`~draft_intel.models.Revert` since Sprint 1.
**Nothing on the live path emitted any of them.** So when the tool said AJ had $47 and the room
said $42, there was no way to say so — and charter §2 makes manual entry the *primary* price
path, not a fallback, because Sleeper publishes no auction value at all (Finding 3).

Two rules shape everything here.

**A budget correction is a delta, never a pin.** §4.8: an absolute would fight the next poll —
you set AJ to $42, he buys somebody for $10, and a pin drags him back to $42 while the feed
says $37. A delta of -$5 rides along correctly: $47 → $37 from the feed, -$5 applied, $32,
which is what the room sees. The *interface* still asks for the absolute, because "AJ has $42"
is what a person says at a table; the delta is computed once, at the moment you say it, and
never recomputed.

**Sequence numbers must be stable across folds.** Feed picks are numbered 1..N and N grows with
every pick, so a correction numbered after them would change identity every poll and a
``Revert`` aimed at one would drift onto a different event. Corrections are therefore numbered
from :data:`CORRECTION_SEQ_BASE`, well above any pick, from an id that is assigned once and
never reused. That also puts them after every pick in fold order, which is right: a correction
is the user's last word on a team, not a competitor with the feed.

Reverting emits a real :class:`~draft_intel.models.Revert` rather than deleting the row. The
ledger already implements and tests that path, and the record of *"I corrected this and then
undid it"* is worth keeping at 9pm when somebody asks why a number moved twice.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from draft_intel.models import BudgetAdjustment, Event, ManualKeeper, Revert

DEFAULT_PATH = Path("config/corrections.yaml")

CORRECTION_SEQ_BASE = 1_000_000
"""Sequence numbers for corrections start here, above any conceivable pick number.

A 16-round, 10-team draft settles 160 picks. Numbering corrections after the picks would make
their sequence -- and therefore their identity to a ``Revert`` -- change on every poll.
"""

HEADER = """\
# Corrections typed during the draft. Written by the cockpit, safe to edit by hand.
#
# Each row is the user overruling the ledger about something the picks feed cannot tell it.
# They are applied AFTER every pick, so a correction is your last word on a team.
#
#   kind: budget    a +/- dollar adjustment to a team's money. Stored as a DELTA, never as an
#                   absolute -- an absolute would fight the next poll, dragging the team back
#                   to a figure that was only true before their next purchase.
#   kind: keeper    a keeper the feed has not delivered, with the price you typed. Sleeper
#                   publishes no auction value, so this is the primary path for keeper prices,
#                   not a fallback. Superseded automatically if a matching real pick arrives.
#
#   reverted: true  neutralises the row without deleting it, so "corrected then undone" stays
#                   legible. Emits a real Revert event into the ledger.
#
# `reason` is not decoration. At 9pm, "why is AJ $5 light?" needs an answer.
"""


class Correction(BaseModel):
    """One thing the user told the ledger that the feed could not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(ge=1)
    """Stable and never reused. The ledger sequence is :data:`CORRECTION_SEQ_BASE` plus this."""

    kind: Literal["budget", "keeper"]
    slot: int = Field(ge=1)
    reason: str = ""
    at: float = 0.0
    """Unix time, for the audit trail. Not used in any calculation."""

    reverted: bool = False

    delta: int | None = None
    """``budget`` only: the adjustment, in dollars. Signed."""

    observed: int | None = None
    """``budget`` only: the absolute figure the user typed, kept beside the delta it produced.

    §4.8's rule applied to a correction: the number the user actually said is retained next to
    the number the system derived from it, so "I told it AJ had $42" stays recoverable from
    "-$5".
    """

    player_id: str | None = None
    """``keeper`` only."""

    amount: int | None = None
    """``keeper`` only: the retention price, typed from the draft room."""

    def describe(self) -> str:
        undone = " (reverted)" if self.reverted else ""
        if self.kind == "budget":
            said = f", you said ${self.observed}" if self.observed is not None else ""
            return f"slot {self.slot}: {self.delta:+d}{said}{undone}"
        return f"slot {self.slot}: keeper {self.player_id} at ${self.amount}{undone}"


class CorrectionStore:
    """Reads and writes ``config/corrections.yaml``. Every read goes to disk."""

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)

    def load(self) -> list[Correction]:
        if not self.path.exists():
            return []
        raw: Any = yaml.safe_load(self.path.read_text()) or {}
        return [Correction.model_validate(row) for row in raw.get("corrections") or []]

    def add(self, **fields: Any) -> Correction:
        """Append a correction with the next id. Ids are never reused, even after a revert."""
        current = self.load()
        entry = Correction(id=max((c.id for c in current), default=0) + 1, at=time.time(), **fields)
        self._write([*current, entry])
        return entry

    def revert(self, correction_id: int) -> Correction | None:
        """Mark one reverted. Returns ``None`` if there is no such correction."""
        current = self.load()
        found = next((c for c in current if c.id == correction_id), None)
        if found is None:
            return None
        undone = found.model_copy(update={"reverted": True})
        self._write([undone if c.id == correction_id else c for c in current])
        return undone

    def events(self) -> list[Event]:
        """The ledger events these corrections produce, at stable sequence numbers.

        A reverted correction still emits its original event **and** a :class:`Revert` aimed at
        it, rather than being silently omitted. That is the path the ledger implements and
        tests, and it keeps the fold's own accounting of what was neutralised — which is what
        surfaces in ``superseded`` and the alerts rather than simply vanishing.
        """
        out: list[Event] = []
        for entry in self.load():
            seq = CORRECTION_SEQ_BASE + entry.id
            if entry.kind == "budget":
                out.append(
                    BudgetAdjustment(
                        seq=seq, slot=entry.slot, delta=entry.delta or 0, reason=entry.reason
                    )
                )
            elif entry.player_id is not None:
                out.append(
                    ManualKeeper(
                        seq=seq,
                        slot=entry.slot,
                        player_id=entry.player_id,
                        amount=entry.amount or 0,
                    )
                )
            if entry.reverted:
                # Reverts sort after every correction, so one aimed at the highest-numbered
                # correction still lands after it.
                out.append(Revert(seq=CORRECTION_SEQ_BASE * 2 + entry.id, target_seq=seq))
        return out

    def _write(self, entries: list[Correction]) -> None:
        payload = {"corrections": [entry.model_dump() for entry in sorted(entries, key=_key)]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(HEADER + yaml.safe_dump(payload, sort_keys=False, width=100))


def _key(entry: Correction) -> int:
    return entry.id
