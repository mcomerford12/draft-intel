"""League configuration and the boot-time tripwire.

The expected settings are a tripwire, not a source of truth: everything is derived from the
API at boot and validated against the config, because a commissioner changing a setting the
night before the draft is a realistic and catastrophic failure mode.

This league is *already* internally inconsistent. ``league.roster_positions`` says 2 QB, no
DEF, 6 bench, 16 slots; ``draft.settings`` says 1 QB, 1 DEF, 5 bench, 15 rounds. See
docs/api-findings.md, Finding 1. So validation is graded rather than binary, and the grading
turns on a single question: **does this field change what a player costs?**

* Starting slots, budget and team count all scale every price in the model. Disagreement is
  **blocking** - refuse to start.
* ``draft_rounds`` also scales every price, but has no unambiguous API source today, so its
  severity is conditional: it **blocks** when ``draft.settings.rounds`` and
  ``len(roster_positions)`` agree with each other and disagree with the config, and warns when
  the API disagrees with itself. See :func:`_check_draft_rounds`.
* Roster size beyond ``draft_rounds``, bench depth, the stale ``draft.settings`` block and
  a moved ``start_time`` change no price. They are **loud but non-blocking**.

``roster_positions`` wins over ``draft.settings`` because it is corroborated three ways over:
by ``draft.metadata.scoring_type == "2qb"``, by the settings of the user's own mock draft,
and by the commissioner directly. Blocking on the draft-settings mismatch would take the tool
down on draft night over a discrepancy we have already diagnosed.

**``roster_size`` and ``draft_rounds`` are deliberately separate** (ADR-0005). They were one
field, and it was right only by coincidence - this league happens to draft every roster spot.
What scales prices is the number of players *bought*, ``teams * draft_rounds``. Capacity above
that is waiver space: it costs nothing at auction, so it must not be able to move a price, and
it must not be able to refuse the boot either. A commissioner adding two bench spots the night
before the draft is a shrug, not an outage. A ``roster_size`` *below* ``draft_rounds`` is
incoherent - you cannot seat what you drafted - and does block.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


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
    """Expected league shape. Compared against the live API, never trusted over it.

    Load from ``config/league.yaml`` with :func:`load_league_config` rather than editing the
    defaults here. The error message points a commissioner at that file, and it previously
    did not exist.
    """

    teams: int = 10
    budget: int = 200

    draft_rounds: int = 16
    """Players each team buys at auction. ``teams * draft_rounds`` is the priced pool."""

    roster_size: int = 16
    """Total roster capacity. Anything above ``draft_rounds`` is waiver space, not auction."""

    draft_rounds_api_known_stale: int | None = 15
    """The value ``draft.settings.rounds`` is *known* to be wrong with, and why it may warn.

    Finding 1 diagnosed the draft object as holding stale defaults; ``rounds`` is 15 in a
    16-round league. That one discrepancy is understood, so it warns. Any *other* value is
    unexplained, and an unexplained number in the field that scales every price blocks rather
    than joining a list of routine warnings it is indistinguishable from. Set to ``None`` to
    treat every disagreement as undiagnosed.
    """

    keepers_per_team: int = 2
    starters: dict[str, int] = field(
        default_factory=lambda: {"QB": 2, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1}
    )
    bench: int = 6
    draft_start: str | None = None

    @property
    def starting_slots(self) -> int:
        return sum(self.starters.values())

    @property
    def auction_pool(self) -> int:
        """Players bought league-wide. The denominator behind every price."""
        return self.teams * self.draft_rounds


class ConfigMismatch(Exception):
    """Raised at boot when the live league contradicts the expected configuration."""


def load_league_config(path: str | Path = "config/league.yaml") -> LeagueConfig:
    """Load the tripwire values from ``config/league.yaml``."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    config = LeagueConfig(
        teams=int(data["teams"]),
        budget=int(data["budget"]),
        draft_rounds=int(data["draft_rounds"]),
        draft_rounds_api_known_stale=(
            None
            if data.get("draft_rounds_api_known_stale") is None
            else int(data["draft_rounds_api_known_stale"])
        ),
        roster_size=int(data["roster_size"]),
        keepers_per_team=int(data["keepers_per_team"]),
        bench=int(data["bench"]),
        starters={str(k): int(v) for k, v in (data.get("starters") or {}).items()},
        draft_start=_normalise_start(data.get("draft_start")),
    )
    # Caught here rather than at validate(): a config file that contradicts itself is a typo
    # in our own repo, not a league that drifted, and it should never reach the API comparison.
    if config.roster_size < config.draft_rounds:
        raise ConfigMismatch(
            f"config/league.yaml is self-contradictory: roster_size {config.roster_size} is "
            f"smaller than draft_rounds {config.draft_rounds}. A team cannot seat every player "
            "it drafts."
        )
    return config


def _utc_iso(epoch_millis: int) -> str:
    """Sleeper's ``start_time`` in milliseconds, rendered as the UTC instant we compare on."""
    return datetime.fromtimestamp(epoch_millis / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalise_start(raw: Any) -> str | None:
    """Reduce whatever the YAML gave us to the one canonical spelling we compare on.

    The comparison is between formatted strings, so every equivalent spelling of the same
    instant has to collapse to one. Three arrive in practice and all three mean draft night:

    * a quoted ``"2026-09-06T01:00:00Z"`` -- the intended form;
    * the same value unquoted, which ``yaml.safe_load`` silently parses into a ``datetime``
      and which would then never equal a ``str``, warning permanently about a draft that has
      not moved;
    * an explicit ``+00:00`` offset, or a local offset like ``-06:00``, which names the same
      instant in different words.

    A value that is none of those is returned untouched, so it surfaces as a mismatch the user
    can see and fix rather than as a silent ``None``.
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        moment = raw if raw.tzinfo else raw.replace(tzinfo=UTC)
        return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw
        moment = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(raw)


def positions_from_roster(roster_positions: list[str]) -> dict[str, int]:
    """Count starting slots from ``league.roster_positions``, excluding bench and IR."""
    return {k: v for k, v in Counter(roster_positions).items() if k not in {"BN", "IR", "TAXI"}}


def _check_draft_rounds(
    config: LeagueConfig, draft_rounds: Any, roster_size: int
) -> list[ConfigIssue]:
    """Grade ``draft_rounds`` against the two API fields that speak to the auction pool size.

    ``draft_rounds`` scales every price in the model -- get it wrong and ``pool_full`` excludes
    players who will actually be bought, ``discretionary`` is off by the difference, and the
    §4.3 sum invariants still pass because they are self-consistent against the wrong pool. A
    wrong-priced board with no error. So this cannot be a warning in general.

    But it also cannot be a hard block against ``draft.settings.rounds``, which says 15 today
    while the league is a 16-round league (Finding 1); blocking on that takes the tool down on
    draft night over a discrepancy already diagnosed. And roster length is not corroboration on
    its own -- the whole point of ADR-0005 is that a roster may be larger than the draft.

    So the severity turns on **whether the API agrees with itself**:

    * ``settings.rounds == roster_size`` -- the two independent API fields corroborate each
      other. That agreed value is authoritative and disagreeing with it **blocks**. This is the
      state the league reaches once DI-004 lands, and it is the case where a silently wrong
      pool size would otherwise be shipped.
    * they disagree -- the API is internally inconsistent, which is today. Nothing is
      authoritative, so warn on each and let the tool boot.

    The check is deliberately two-sided. A ``draft_rounds`` that is too *large* is the more
    dangerous direction and the one the ledger's per-team slot cap can never catch: that cap
    fires only when a team takes one pick too many, which is the end of the draft, and never
    fires at all when the configured figure exceeds reality.
    """
    if draft_rounds is None:
        return []
    if not isinstance(draft_rounds, int) or isinstance(draft_rounds, bool):
        return [
            ConfigIssue(
                Severity.WARNING, "draft.rounds", config.draft_rounds, draft_rounds, "draft"
            )
        ]
    if draft_rounds == config.draft_rounds:
        return []
    if draft_rounds == roster_size:
        return [
            ConfigIssue(
                Severity.BLOCKING,
                "draft_rounds",
                config.draft_rounds,
                draft_rounds,
                "draft.settings.rounds, corroborated by roster_positions",
            )
        ]
    if draft_rounds != config.draft_rounds_api_known_stale:
        # Neither our value nor the one we diagnosed as stale. We have no account of this
        # number, and "it is probably stale too" is a guess about the field that scales every
        # price. An undiagnosed `rounds` of 14 against a configured 16 is indistinguishable, in
        # a warning, from the known-stale 15 -- and it would price a 160-spot pool for a
        # 140-pick draft, moving the top of the board by roughly 30% with all three §4.3
        # invariants still passing, because they are self-consistent against whatever pool they
        # are handed. So an unexplained value blocks, and the fix is one line of config: either
        # correct `draft_rounds` or record the new number as diagnosed-stale.
        return [
            ConfigIssue(
                Severity.BLOCKING,
                "draft_rounds",
                f"{config.draft_rounds}, or the diagnosed-stale "
                f"{config.draft_rounds_api_known_stale}",
                draft_rounds,
                "draft.settings.rounds (undiagnosed)",
            )
        ]
    return [
        ConfigIssue(Severity.WARNING, "draft.rounds", config.draft_rounds, draft_rounds, "draft")
    ]


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
    blocking("teams", config.teams, league.get("total_rosters"))

    # Roster capacity. Bench depth and total roster size change no price -- the auction buys
    # `teams * draft_rounds` players whatever the bench looks like -- so these warn. The one
    # case that blocks is a roster too small to seat what gets drafted, which is incoherent
    # rather than merely surprising.
    roster_size = len(roster_positions)
    if roster_size and roster_size < config.draft_rounds:
        issues.append(
            ConfigIssue(
                Severity.BLOCKING,
                "roster_size",
                f"{config.roster_size} (and at least draft_rounds, {config.draft_rounds})",
                roster_size,
                "league",
            )
        )
    if roster_size != config.roster_size:
        issues.append(
            ConfigIssue(Severity.WARNING, "roster_size", config.roster_size, roster_size, "league")
        )
    if bench != config.bench:
        issues.append(ConfigIssue(Severity.WARNING, "bench", config.bench, bench, "league"))

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
    issues.extend(_check_draft_rounds(config, settings.get("rounds"), roster_size))
    # A moved draft invalidates every "how long do I have" answer the tool gives, but it must
    # never keep the tool from starting -- a commissioner nudging the start time by an hour is
    # routine, and refusing to boot over it on the night is the worst possible trade.
    start_time = draft.get("start_time")
    if config.draft_start is not None and start_time is not None:
        # Not `int(start_time)`: Sleeper has returned a string here before, and a start time
        # that cannot be parsed must warn like any other drift rather than take the boot down
        # over a field that changes no price.
        actual = (
            _utc_iso(int(start_time))
            if isinstance(start_time, int | float) and not isinstance(start_time, bool)
            else f"unparseable ({start_time!r})"
        )
        if actual != config.draft_start:
            issues.append(
                ConfigIssue(
                    Severity.WARNING, "draft.start_time", config.draft_start, actual, "draft"
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
