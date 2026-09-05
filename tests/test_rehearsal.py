"""DI-065 — the rehearsal harness itself.

A gate that cannot fail is not a gate. The rehearsal reports PASSED on the current tree, and the
only thing that makes that reassuring rather than decorative is evidence that its checks would
have said otherwise. So most of what follows doctors a snapshot until an invariant *should*
break, and asserts that it does — the same discipline DI-054 applied to three tests that turned
out to be incapable of failing.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from draft_intel.api.live import LiveSnapshot, TeamLine, WalkAwayStatus
from tools import rehearsal
from tools.rehearsal import (
    GOLDEN_SPEND,
    ReplayFeed,
    _mock_slots,
    _owner_at,
    _reattribute,
    check,
)

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
    assert result.stdout.count("  ok ") >= 17, "10 ledger rows plus 7 chaos cases"


# ------------------------------------------------------- re-attribution, for --live
#
# `--live` replays the mock's 160 picks against the live league's seating. The identity join
# and the network fetch belong to production code that has its own tests; what is new here, and
# what got three things wrong before it got them right, is the re-attribution itself. Each of
# the tests below pins one of those three.


class _Seating:
    """A stand-in for the resolved live identity — ``_reattribute`` consults only ``slot_for``."""

    def __init__(self, seats: dict[str, int]) -> None:
        self._seats = seats

    def slot_for(self, owner: str) -> int | None:
        return self._seats.get(owner)


def picks_fixture() -> list[dict[str, Any]]:
    picks: list[dict[str, Any]] = json.loads((ROOT / "fixtures" / "picks.json").read_text())
    return picks


def mirrored() -> _Seating:
    """A live seating that puts everyone somewhere else: slot n becomes slot 11-n."""
    return _Seating({owner: 11 - slot for owner, slot in _mock_slots().items()})


def test_every_pick_moves_to_the_seat_its_owner_holds_live() -> None:
    """The point of the mode. Replaying raw slot numbers would test a draft nobody will play —
    mock slot 1 is AJ, live slot 1 is Mason — so what has to carry over is *who paid*."""
    picks = picks_fixture()
    moved, placed, assumed = _reattribute(picks, mirrored(), teams=10)

    assert assumed == [], "everyone is seated, so nothing should be assumed"
    assert len(moved) == len(picks), "re-attribution must not drop a pick"
    assert placed == {owner: 11 - slot for owner, slot in _mock_slots().items()}
    for before, after in zip(picks, moved, strict=True):
        assert after["draft_slot"] == 11 - int(before["draft_slot"])


def test_metadata_slot_is_rewritten_in_lockstep_with_draft_slot() -> None:
    """The harness first rewrote ``draft_slot`` alone, and the poller's cross-check (DI-053)
    reported 224 PAYLOAD CONFLICTs. The tool was right: that payload is one Sleeper would never
    emit. Rewriting one field and not the other must never come back."""
    moved, _placed, _assumed = _reattribute(picks_fixture(), mirrored(), teams=10)
    assert moved, "guard against an empty list making this vacuous"
    assert all(int(pick["metadata"]["slot"]) == pick["draft_slot"] for pick in moved)


def test_owners_who_have_not_joined_take_the_leftover_seats_and_are_reported() -> None:
    """Three managers had not joined when this was written, and the run still has to happen.
    Filling their seats is an assumption; returning it separately is what lets the run print it
    rather than bury it."""
    seven = {o: s for o, s in _mock_slots().items() if o not in {"Burt", "Connor", "TD"}}
    _moved, placed, assumed = _reattribute(picks_fixture(), _Seating(seven), teams=10)

    assert assumed == ["Burt", "Connor", "TD"]
    assert placed | seven == placed, "a seated owner is never moved to make room"
    assert sorted(placed.values()) == list(range(1, 11)), "ten owners, ten distinct seats"


def test_re_attribution_preserves_what_each_person_bought() -> None:
    """Money follows the person, not the seat. If this drifts, the by-owner ledger comparison at
    the end of a live run is checking two different drafts against each other."""
    picks = picks_fixture()
    mock_slot = _mock_slots()
    moved, placed, _assumed = _reattribute(picks, mirrored(), teams=10)

    for owner in mock_slot:
        was = [p for p in picks if int(p["draft_slot"]) == mock_slot[owner]]
        now = [p for p in moved if int(p["draft_slot"]) == placed[owner]]
        assert len(was) == len(now) == 16
        assert {p["player_id"] for p in was} == {p["player_id"] for p in now}


def test_owner_at_reads_the_seating_backwards() -> None:
    assert _owner_at({"AJ": 1, "Mason": 2}, 2) == "Mason"
    assert _owner_at({"AJ": 1}, 9) is None


def test_the_mock_seating_still_covers_all_ten_managers() -> None:
    """If a manifest owner ever stops resolving against the mock fixture, their picks vanish from
    the re-attributed feed silently — ``_reattribute`` skips slots it cannot name."""
    assert sorted(_mock_slots().values()) == list(range(1, 11))


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], (False, None)),
        (["--live"], (True, None)),
        (["--seats=/tmp/x.yaml"], (False, "/tmp/x.yaml")),
        (["--live", "--seats=/tmp/x.yaml"], (True, "/tmp/x.yaml")),
    ],
)
def test_the_flags_reach_the_run(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], expected: tuple[bool, str | None]
) -> None:
    """``--seats`` exists so a rehearsal can try a seating without writing it into the real
    config. A flag that parses but never reaches ``run`` would silently rehearse the wrong one —
    which is how ``--seats`` reached the re-attribution but not the cockpit's own seat store."""
    seen: list[tuple[bool, str | None]] = []

    def spy(live_league: bool = False, _seats_override: str | None = None) -> int:
        seen.append((live_league, _seats_override))
        return 0

    monkeypatch.setattr(rehearsal, "run", spy)
    assert rehearsal.main(argv) == 0
    assert seen == [expected]
