"""Persisted value overrides — the file behind the price table's edit box.

Charter §4.8 already defines what an override *is* (:mod:`draft_intel.quant.overrides`): the
user's number replaces the model's for pricing, and the model's is kept alongside it
permanently, because "the model said $26 and I said $40" is a different fact from "$40".

What was missing is somewhere to keep it. This is that, and it is a **YAML file rather than a
row in the event log**, deliberately:

.. note::

   This module lives under ``store/`` rather than ``api/`` because :mod:`draft_intel.prep`
   reads it. Overrides are a *pipeline input*, not a web-layer concern: the priced board
   ``make prep`` prints and the table ``/prices`` renders must be the same board, and that is
   only true if both read the overrides from the same place. It moved here in DI-062, when
   ``build_pipeline`` started applying them.

* the user asked to come back and change these later, and a file they can open in an editor at
  11pm is a better answer than a table they need the app running to reach;
* every other authored input in this project is a config file -- ``keepers.yaml``,
  ``owners.yaml``, ``auction_values.csv`` -- and a second idiom for the same kind of thing is a
  thing to learn rather than a thing to use;
* it diffs. An override is a judgement, and judgements are worth seeing in a commit.

The trade is that these are *not* events: no revert, no seq, no replay. That is the right trade
for a standing correction to a projection, and the wrong one for anything that happens during
the draft — money and picks stay in the event log where reversal is free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from draft_intel.quant.overrides import PlayerOverride

DEFAULT_PATH = Path("config/value_overrides.yaml")

HEADER = """\
# Manual value overrides. Written by the price table at /prices, and safe to edit by hand.
#
# Each entry replaces the model's number for that player. The model's own figure is never
# overwritten -- it is kept and shown beside yours, so a correction stays legible as a
# correction. Delete an entry to fall back to the model.
#
#   points:       projected points. Applied UPSTREAM, before replacement level is computed, so
#                 it moves VORP and every dollar figure derived from it -- including this
#                 player's live value, and (very slightly) everybody else's, because it moves
#                 the replacement baseline they are all measured against.
#   live_value:   what the player should cost in THIS auction. The number you bid against.
#                 Replaces whatever the model derived, points override included. Meaningless
#                 for a keeper: they are off the board and cannot be bid on.
#   market_value: full-market value -- a keeper-free $2,000 auction. This is the number the
#                 league's floor(0.75 x auction value) keeper rule reads, so overriding it for
#                 a keeper changes their rule price, their surplus, and the keeper inflation
#                 figure. It is also how you clear the ESTIMATE badge one player at a time
#                 without assembling the whole auction_values.csv.
#   blacklisted:  never bid, whatever the model says. Zeroes both dollar figures.
#   note:         why. Worth having at 9pm on draft night when the reason has gone.
#
# Anything you leave out keeps the model's value for that field. Values are NOT renormalised
# after an edit: one correction must not silently move every other price. The board's total
# will stop matching the money in the room, and that deviation is displayed rather than hidden.
"""


class ValueOverride(BaseModel):
    """One player's overridden values, as stored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    player_id: str
    name: str = ""
    """Carried for readability of the file itself; never used to resolve anybody."""

    live_value: float | None = Field(default=None, ge=0)
    market_value: float | None = Field(default=None, ge=0)
    points: float | None = Field(default=None)
    blacklisted: bool = False
    note: str = ""

    @property
    def is_empty(self) -> bool:
        """True when this entry would change nothing, so writing it is just noise."""
        return (
            self.live_value is None
            and self.market_value is None
            and self.points is None
            and not self.blacklisted
        )

    def as_player_override(self) -> PlayerOverride:
        """Convert to the §4.8 type the valuation layer already understands.

        ``live_value`` maps to ``baseline_value``: the two names are the same quantity seen from
        two sides. The quant layer calls it the baseline because it is what a bid is measured
        against; the page calls it the live value because that is what the user is typing.
        """
        return PlayerOverride(
            baseline_value=self.live_value,
            market_value=self.market_value,
            points=self.points,
            blacklisted=self.blacklisted,
            note=self.note,
        )


class OverrideStore:
    """Reads and writes ``config/value_overrides.yaml``.

    Every read goes to disk. That is deliberate rather than lazy: the file is small, and the
    user was promised they could edit it by hand, so a cached copy would quietly ignore them.
    """

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, ValueOverride]:
        """Every stored override, keyed by ``player_id``. Missing file means none."""
        if not self.path.exists():
            return {}
        raw: Any = yaml.safe_load(self.path.read_text()) or {}
        entries = raw.get("overrides") or []
        out: dict[str, ValueOverride] = {}
        for entry in entries:
            override = ValueOverride.model_validate(entry)
            out[override.player_id] = override
        return out

    def set(self, override: ValueOverride) -> dict[str, ValueOverride]:
        """Add or replace one player's override, and persist. Returns the new full set.

        An override that would change nothing is stored as a *removal*, so clearing every field
        in the UI does what it looks like it does rather than leaving an inert entry behind.
        """
        current = self.load()
        if override.is_empty and not override.note:
            current.pop(override.player_id, None)
        else:
            current[override.player_id] = override
        self._write(current)
        return current

    def clear(self, player_id: str) -> dict[str, ValueOverride]:
        current = self.load()
        current.pop(player_id, None)
        self._write(current)
        return current

    def as_player_overrides(self) -> dict[str, PlayerOverride]:
        """The form :func:`draft_intel.quant.overrides.apply_overrides` takes."""
        return {pid: entry.as_player_override() for pid, entry in self.load().items()}

    def _write(self, entries: dict[str, ValueOverride]) -> None:
        # Sorted by player_id so the file has a stable order and a diff shows the edit rather
        # than a reshuffle. Written whole rather than appended: this is a set of standing
        # corrections, not a log.
        payload = {
            "overrides": [
                entry.model_dump(exclude_defaults=False) for _pid, entry in sorted(entries.items())
            ]
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(HEADER + yaml.safe_dump(payload, sort_keys=False, width=100))
