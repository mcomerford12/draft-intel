"""The keeper backstop's on/off switch, and the file it lives in.

Charter §2 asks for a *prominent pre-draft arming toggle*. This is it, and the reason it is a
file rather than a flag is that the two processes that need to agree about it — the CLI and the
cockpit — do not share memory, and the person flipping it is doing so ten minutes before the
draft in a different terminal from the one the cockpit is running in.

**What arming does.** While a slot still owes ceremonial keepers, a pick by that slot that the
manifest does not recognise is ``FLAGGED`` for confirmation rather than silently counted as a
competitive bid. It is the backstop for a keeper swapped after ``config/keepers.yaml`` was
written — which nobody will remember to tell you about, and which otherwise puts a retention
price into the competitive series as though somebody had bid it.

**Why it defaults to off, still.** DI-055 refused to arm this and was right at the time: a
``FLAGGED`` pick could not be confirmed or denied by any product path, so arming turned a
recoverable mistake into a one-way trap. DI-073 shipped the answer path. The trap is gone, but
the default stays off because arming changes classifications, and a tool that quietly
reclassifies picks the first time you run it is not one you can trust the numbers of. Turning
it on is a decision, made once, before the draft::

    make arm            # what is it now
    make arm ON=1       # arm it
    make arm ON=0       # disarm it

Every read goes to disk, exactly as ``SeatStore`` and ``CorrectionStore`` do, so flipping the
switch mid-draft takes effect on the very next poll rather than at the next restart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path("config/arming.yaml")

HEADER = """\
# The keeper backstop. Written by `make arm`, safe to edit by hand.
#
# armed: true   While a slot still owes ceremonial keepers, a pick by that slot that the
#               manifest does not recognise is FLAGGED rather than counted as a competitive
#               bid. Confirm or deny each one from the cockpit's `recount it` form -- a
#               FLAGGED pick is a question, and leaving it unanswered keeps real money out of
#               inflation, skew and every tendency profile.
#
# armed: false  The manifest and `is_keeper` decide, and an unrecognised pick is a bid. This
#               is the default and the behaviour every gate in the project was measured under.
#
# The window is NOT a pick-number range. It is per slot, and it closes as soon as that slot has
# recorded the keepers the league rule says it holds -- so a real bid at pick 20 by a team whose
# ceremonial round is done stays competitive. A league with keepers_per_team: 0 flags nothing.
"""


class ArmingStore:
    """Reads and writes ``config/arming.yaml``. Every read goes to disk."""

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)

    def load(self) -> bool:
        """Whether the backstop is armed. A missing or unreadable file means **off**.

        Defaulting to off on a malformed file is deliberate. The alternative — refusing to
        start — takes the tool down over a setting whose whole purpose is to be optional, and
        the alternative to *that* — defaulting to on — silently reclassifies picks because a
        file had a typo in it.
        """
        if not self.path.exists():
            return False
        raw: Any = yaml.safe_load(self.path.read_text()) or {}
        return bool(raw.get("armed", False)) if isinstance(raw, dict) else False

    def set(self, armed: bool) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(HEADER + yaml.safe_dump({"armed": armed}, sort_keys=False))
        return armed
