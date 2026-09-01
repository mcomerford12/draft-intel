"""League configuration and the boot-time tripwire.

The expected settings are a tripwire, not a source of truth: everything is derived from the
API at boot and validated against the config, because a commissioner changing a setting the
night before the draft is a realistic and catastrophic failure mode.

This league is *already* internally inconsistent. ``league.roster_positions`` says 2 QB, no
DEF, 6 bench, 16 slots; ``draft.settings`` says 1 QB, 1 DEF, 5 bench, 15 rounds. See
docs/api-findings.md, Finding 1. So validation is graded rather than binary:

* ``roster_positions`` disagreeing with the config is **blocking** - refuse to start.
* ``draft.settings`` disagreeing with ``roster_positions`` is **loud but non-blocking**.

``roster_positions`` wins because it is corroborated twice over, by
``draft.metadata.scoring_type == "2qb"`` and by the settings of the user's own mock draft.
Blocking on the draft-settings mismatch would take the tool down on draft night over a
discrepancy we have already diagnosed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Severity:
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"


@dataclass(frozen=True)
class ConfigIssue:
    severity: str
    field: str
    expected: Any
    actual: Any
    source: str

    def __str__(self) -> str:
        return (
            f"[{self.severity}] {self.field}: expected {self.expected!r}, "
            f"{self.source} says {self.actual!r}"
        )


@dataclass(frozen=True)
class LeagueConfig:
    """Expected league shape. Compared against the live API, never trusted over it."""

    teams: int = 10
    budget: int = 200
    total_slots: int = 16
    keepers_per_team: int = 2
    starters: dict[str, int] = field(
        default_factory=lambda: {"QB": 2, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1}
    )
    bench: int = 6

    @property
    def starting_slots(self) -> int:
        return sum(self.starters.values())


class ConfigMismatch(Exception):
    """Raised at boot when the live league contradicts the expected configuration."""


def positions_from_roster(roster_positions: list[str]) -> dict[str, int]:
    """Count starting slots from ``league.roster_positions``, excluding bench and IR."""
    return {k: v for k, v in Counter(roster_positions).items() if k not in {"BN", "IR", "TAXI"}}


def validate(
    config: LeagueConfig,
    league: dict[str, Any],
    draft: dict[str, Any],
) -> list[ConfigIssue]:
    """Compare the live league and draft objects against ``config``.

    Returns every issue found. Callers raise on any ``BLOCKING`` entry and surface the
    ``WARNING`` entries as a persistent banner.
    """
    issues: list[ConfigIssue] = []
    roster_positions = list(league.get("roster_positions") or [])
    starters = positions_from_roster(roster_positions)
    bench = Counter(roster_positions).get("BN", 0)

    def blocking(name: str, expected: Any, actual: Any) -> None:
        if expected != actual:
            issues.append(ConfigIssue(Severity.BLOCKING, name, expected, actual, "league"))

    for pos, want in config.starters.items():
        blocking(f"starters.{pos}", want, starters.get(pos, 0))
    for pos in starters:
        if pos not in config.starters:
            issues.append(
                ConfigIssue(Severity.BLOCKING, f"starters.{pos}", 0, starters[pos], "league")
            )
    blocking("bench", config.bench, bench)
    blocking("total_slots", config.total_slots, len(roster_positions))
    blocking("teams", config.teams, league.get("total_rosters"))

    settings = draft.get("settings") or {}
    blocking("budget", config.budget, settings.get("budget"))

    # Non-blocking: the draft object's stale slot settings. Diagnosed in Finding 1.
    draft_slots = {
        "QB": settings.get("slots_qb"),
        "RB": settings.get("slots_rb"),
        "WR": settings.get("slots_wr"),
        "TE": settings.get("slots_te"),
        "FLEX": settings.get("slots_flex"),
        "K": settings.get("slots_k"),
    }
    for pos, actual in draft_slots.items():
        want = starters.get(pos, 0)
        if actual is not None and actual != want:
            issues.append(
                ConfigIssue(Severity.WARNING, f"draft.slots_{pos.lower()}", want, actual, "draft")
            )
    if settings.get("slots_def"):
        issues.append(
            ConfigIssue(Severity.WARNING, "draft.slots_def", 0, settings["slots_def"], "draft")
        )
    if settings.get("rounds") is not None and settings["rounds"] != len(roster_positions):
        issues.append(
            ConfigIssue(
                Severity.WARNING, "draft.rounds", len(roster_positions), settings["rounds"], "draft"
            )
        )
    max_keepers = (league.get("settings") or {}).get("max_keepers")
    if max_keepers is not None and max_keepers != config.keepers_per_team:
        issues.append(
            ConfigIssue(
                Severity.WARNING,
                "league.max_keepers",
                config.keepers_per_team,
                max_keepers,
                "league",
            )
        )
    return issues


def assert_startable(issues: list[ConfigIssue]) -> list[ConfigIssue]:
    """Raise on any blocking issue; return the warnings for the banner."""
    blocking = [i for i in issues if i.severity == Severity.BLOCKING]
    if blocking:
        detail = "\n  ".join(str(i) for i in blocking)
        raise ConfigMismatch(
            f"Live league contradicts the expected configuration:\n  {detail}\n"
            "Refusing to start. Fix the league settings or update config/league.yaml."
        )
    return [i for i in issues if i.severity == Severity.WARNING]
