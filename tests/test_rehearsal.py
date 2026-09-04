"""DI-065 — the rehearsal harness itself.

A gate that cannot fail is not a gate. The rehearsal reports PASSED on the current tree, and the
only thing that makes that reassuring rather than decorative is evidence that its checks would
have said otherwise. So most of what follows doctors a snapshot until an invariant *should*
break, and asserts that it does — the same discipline DI-054 applied to three tests that turned
out to be incapable of failing.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from draft_intel.api.live import LiveSnapshot, TeamLine, WalkAwayStatus
from tools.rehearsal import GOLDEN_SPEND, ReplayFeed, check

ROOT = Path(__file__).resolve().parents[1]


def team(**kw: object) -> TeamLine:
    base: dict[str, object] = {
        "slot": 1,
        "owner": "someone",
        "is_me": False,
        "spent": 100,
        "remaining": 100,
        "filled_slots": 8,
        "open_slots": 8,
        "max_bid": 93,
        "keepers": 2,
        "figures_suspect": False,
    }
    return TeamLine.model_validate(base | kw)


def snapshot(teams: tuple[TeamLine, ...], **kw: object) -> LiveSnapshot:
    base: dict[str, object] = {
        "polled_at": 1.0,
        "age_seconds": 0.1,
        "stale": False,
        "connection": "live",
        "draft_status": "drafting",
        "picks_seen": sum(t.filled_slots for t in teams),
        "competitive_picks": 0,
        "teams": teams,
        "total_remaining": sum(t.remaining for t in teams),
        "total_open_slots": sum(t.open_slots for t in teams),
        "inflation": 1.0,
        "inflation_detail": "",
        "positions": (),
        "block": None,
        "walkaway": WalkAwayStatus(state="absent", detail=""),
        "alerts": (),
        "blockers": (),
    }
    return LiveSnapshot.model_validate(base | kw)


def rules(snap: LiveSnapshot, pick_no: int | None = None) -> set[str]:
    picks = pick_no if pick_no is not None else sum(t.filled_slots for t in snap.teams)
    return {v.rule for v in check(snap, pick_no=picks, budget=200, rounds=16)}


def clean() -> tuple[TeamLine, ...]:
    return tuple(team(slot=s, spent=100, remaining=100, filled_slots=8) for s in range(1, 11))


# ------------------------------------------------------- the checker holds its peace


def test_a_healthy_snapshot_trips_nothing() -> None:
    """The baseline. Without this the tests below prove only that `check` returns something."""
    assert rules(snapshot(clean())) == set()


# ------------------------------------------------------- ...and can actually fail


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"spent": 101}, "money conservation"),
        ({"remaining": -1}, "no negative budget"),
        ({"max_bid": 101}, "max bid within budget"),
        ({"max_bid": -1}, "max bid non-negative"),
        ({"filled_slots": 17}, "roster capacity"),
        ({"keepers": 3}, "keeper cap"),
        ({"figures_suspect": True}, "figures trustworthy"),
    ],
)
def test_each_team_invariant_catches_its_own_violation(
    mutation: dict[str, object], expected: str
) -> None:
    """One doctored team at a time, so a rule that quietly stopped firing is visible rather than
    masked by the six that still do."""
    teams = (team(slot=1, **mutation), *clean()[1:])
    assert expected in rules(snapshot(teams))


def test_a_pick_that_lands_on_nobody_is_caught() -> None:
    """The one that catches a dropped row: the feed says 80 picks, the rosters hold 79, and the
    missing player's dollars went nowhere. Money can still conserve while this is true."""
    assert "every pick lands" in rules(snapshot(clean()), pick_no=81)


def test_a_short_read_of_the_feed_is_caught() -> None:
    assert "feed read fully" in rules(snapshot(clean(), picks_seen=79))


def test_a_stale_reading_straight_after_a_poll_is_caught() -> None:
    """Fresh after a successful poll is not optional — it is how the whole staleness contract is
    anchored. If this can be true right after polling, the NOT LIVE banner means nothing."""
    assert "fresh after a good poll" in rules(snapshot(clean(), stale=True))


def test_alerts_and_blockers_are_caught_separately() -> None:
    """They are different kinds of thing and the rehearsal must not collapse them."""
    assert "clean fixture" in rules(snapshot(clean(), alerts=("something happened",)))
    assert "no blockers" in rules(snapshot(clean(), blockers=("something is wrong now",)))


# ------------------------------------------------------- the feed, and the whole run


def test_the_replay_feed_serves_a_growing_draft() -> None:
    picks = [{"pick_no": i} for i in range(1, 6)]
    feed = ReplayFeed(picks)
    assert feed.cursor == 0
    feed.cursor = 3
    assert len(asyncio.run(feed.picks("d"))) == 3
    assert asyncio.run(feed.draft("d"))["status"] == "drafting"
    feed.cursor = 5
    assert asyncio.run(feed.draft("d"))["status"] == "complete"


def test_the_golden_file_is_the_one_sprint_1_proved() -> None:
    """Restated in the harness, so a typo there cannot quietly weaken the final assertion."""
    assert sum(GOLDEN_SPEND.values()) == 1979
    assert len(GOLDEN_SPEND) == 10
    assert GOLDEN_SPEND[3] == 195


def test_the_full_rehearsal_passes_and_exits_zero() -> None:
    """The gate contract: a clean run exits 0 so it can block a release. Run as a subprocess
    because the exit code *is* the interface — `make rehearsal` reads nothing else."""
    result = subprocess.run(
        [sys.executable, "tools/rehearsal.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout[-3000:]
    assert "PASSED — 160 picks" in result.stdout
    assert "every poll fitted inside" in result.stdout
    assert result.stdout.count("  ok ") >= 14, "10 ledger rows plus 4 chaos cases"
