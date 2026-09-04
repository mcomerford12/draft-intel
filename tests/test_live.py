"""DI-064 — the draft-night cockpit.

Driven by the real 160-pick fixture served through a fake client, because a cockpit that works
on synthetic picks and falls over on the actual feed is worth nothing on the one night it runs.
No player name is hardcoded: the tests pick whoever the board or the ledger puts in front of
them.

The tests that matter most here are not the happy ones. A cockpit fails by *looking fine* —
numbers frozen four minutes ago, six keepers quietly counted as competitive bids, a threat
ladder computed from a budget that a negative amount already corrupted. Those are the ones
below with the longest docstrings.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from draft_intel.api.live import STALE_AFTER_SECONDS, LiveDraft
from draft_intel.store.overrides import OverrideStore, ValueOverride
from draft_intel.store.seats import SeatAssignment, SeatStore

ROOT = Path(__file__).resolve().parents[1]
PICKS = sorted(
    json.loads((ROOT / "fixtures" / "picks.json").read_text()), key=lambda p: p["pick_no"]
)

# The Sprint 1 gate, restated. These are the observed figures from the user's real mock, and
# the cockpit has to reproduce them through its own polling path or it is reporting fiction.
GOLDEN_SPEND = {1: 199, 2: 200, 3: 195, 4: 200, 5: 200, 6: 200, 7: 200, 8: 200, 9: 185, 10: 200}


# The seating the fixture's 160 picks were actually drafted under, expressed the way the live
# league expresses it: Sleeper display names, resolved through `config/owners.yaml`. The three
# managers with no alias carry their manifest name as their display name, which `build_identity`
# resolves directly.
FIXTURE_SEATING = {
    1: "ajthebeard",
    2: "jswilliams5",
    3: "mattchupiccu",
    4: "MasonWAlpert",
    5: "Connor",
    6: "keenankid17",
    7: "steeveegee300",
    8: "willdeann",
    9: "Burt",
    10: "TD",
}

# The *real* league's seating, which is deliberately different — and is the whole reason the
# cockpit resolves identity from the live feed instead of from `Pipeline.identity`. The mock
# seats AJ at slot 1 and Mason at slot 4; the live league seats Mason at 1 and Steve at 4.
# A cockpit using the mock's map would check every keeper against the wrong seat and still
# look healthy, because the user is slot 3 in both.
LIVE_SEATING = {
    1: "MasonWAlpert",
    2: "ajthebeard",
    3: "mattchupiccu",
    4: "steeveegee300",
    5: "jswilliams5",
    6: "keenankid17",
    7: "willdeann",
}


class FakeClient:
    """The mock draft's picks served as if live, over the *real* league's seating.

    ``fail`` makes the next poll raise. ``seating`` is the slot -> Sleeper display name map the
    roster/user join would return; the real draft object carries no ``slot_name_*`` keys at all
    (Sprint 0, Finding 9), so this fake carries none either.
    """

    def __init__(
        self,
        picks: list[dict[str, Any]],
        *,
        status: str = "drafting",
        seating: dict[int, str] | None = None,
    ) -> None:
        self.picks_payload = picks
        self.status = status
        self.seating = FIXTURE_SEATING if seating is None else seating
        self.fail: Exception | None = None
        self.calls = 0

    async def draft(self, _draft_id: str) -> dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        return {
            "status": self.status,
            "slot_to_roster_id": {str(slot): slot for slot in self.seating},
            "metadata": {},
        }

    async def picks(self, _draft_id: str) -> list[dict[str, Any]]:
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        return self.picks_payload

    async def rosters(self, _league_id: str) -> list[dict[str, Any]]:
        return [{"roster_id": slot, "owner_id": f"u{slot}"} for slot in self.seating]

    async def users(self, _league_id: str) -> list[dict[str, Any]]:
        return [
            {"user_id": f"u{slot}", "display_name": name} for slot, name in self.seating.items()
        ]


def make(picks: list[dict[str, Any]], store: OverrideStore, **kw: Any) -> LiveDraft:
    client = FakeClient(picks, **kw)
    live = LiveDraft(ROOT, league_id="L", draft_id="D", store=store, client=client)
    return live


@pytest.fixture
def store(tmp_path: Path) -> OverrideStore:
    return OverrideStore(tmp_path / "value_overrides.yaml")


# ------------------------------------------------------------------- the ledger


def test_the_cockpit_reproduces_the_golden_ledger_through_its_own_poll(
    store: OverrideStore,
) -> None:
    """Sprint 1's blocking gate, re-run through the path that will actually be used.

    The ledger was proved against `replay_all` in Sprint 1. That proves the fold; it does not
    prove that the cockpit assembles the same events from a live payload, with the same
    classifier and the same league config. A cockpit that drops the manifest classifier reads
    twenty ceremonial keepers as competitive bids and still prints a plausible-looking board.
    """
    live = make(PICKS, store)
    asyncio.run(live.poll_once())
    snap = live.snapshot()

    assert {team.slot: team.spent for team in snap.teams} == GOLDEN_SPEND
    assert snap.total_remaining == 21
    assert snap.picks_seen == 160
    assert snap.competitive_picks == 140, "the 20 ceremonial keepers are not competitive bids"
    assert all(team.keepers == 2 for team in snap.teams)
    assert snap.alerts == ()


def test_every_team_appears_even_before_a_single_pick(store: OverrideStore) -> None:
    """Pre-draft is the state the tool boots into at 6:55pm. Ten teams, full budgets."""
    live = make([], store, status="pre_draft")
    asyncio.run(live.poll_once())
    snap = live.snapshot()

    assert len(snap.teams) == 10
    assert snap.total_remaining == 2000
    assert all(team.remaining == 200 and team.max_bid == 185 for team in snap.teams)
    assert snap.block is None


def test_my_slot_is_derived_from_the_manifest_never_hardcoded(store: OverrideStore) -> None:
    """An earlier version of the report hardcoded slot 3 and contradicted itself by $7."""
    live = make(PICKS, store)
    asyncio.run(live.poll_once())

    mine = [team for team in live.snapshot().teams if team.is_me]
    assert len(mine) == 1
    assert mine[0].slot == live.my_slot
    assert mine[0].owner == live.owner_for(live.my_slot or 0)


# ------------------------------------------------------------------- staleness


def test_a_reading_that_was_never_taken_is_never_presented_as_live(
    store: OverrideStore,
) -> None:
    snap = make(PICKS, store).snapshot()
    assert snap.stale is True
    assert snap.connection == "never connected"
    assert snap.teams == ()


def test_a_failed_poll_keeps_the_last_reading_and_says_the_connection_broke(
    store: OverrideStore,
) -> None:
    """The failure mode this module exists to prevent, and the reason the numbers are *not*
    cleared on error.

    Blanking the board mid-auction throws away the more useful of the two facts. Keeping it
    while reporting the break tells the user both what the board last said and that nothing is
    confirming it any more — which is exactly the position they are in.
    """
    live = make(PICKS, store)
    asyncio.run(live.poll_once())
    assert live.snapshot().total_remaining == 21

    client = live.client
    assert isinstance(client, FakeClient)
    client.fail = ConnectionError("connection reset by peer")
    asyncio.run(live.poll_once())

    snap = live.snapshot()
    assert snap.total_remaining == 21, "the last good reading survives"
    assert "ConnectionError" in snap.connection and "reset" in snap.connection
    assert snap.stale is True, "and it is no longer presented as live"


def test_a_reading_goes_stale_on_age_alone(store: OverrideStore, monkeypatch: Any) -> None:
    """Not just on a raised exception. A poll loop that silently stops — a cancelled task, a
    wedged event loop — leaves a live-looking connection string behind a frozen board."""
    live = make(PICKS, store)
    asyncio.run(live.poll_once())
    assert live.snapshot().stale is False

    now = live._polled_at or 0.0
    monkeypatch.setattr(
        "draft_intel.api.live.time.monotonic", lambda: now + STALE_AFTER_SECONDS + 1
    )

    snap = live.snapshot()
    assert snap.stale is True
    assert snap.connection == "live", "the connection never broke; the reading just aged out"
    assert snap.age_seconds > STALE_AFTER_SECONDS


# ------------------------------------------------------------------- blockers


def test_the_cockpit_never_uses_the_mock_drafts_seating(store: OverrideStore) -> None:
    """The bug this whole identity path exists to prevent, and the one that would have been
    hardest to notice.

    ``Pipeline.identity`` is built from ``fixtures/draft.json`` — the *mock* — because
    ``make prep`` is a report about the mock. The real league seats people differently. The
    keeper classifier keys on ``(slot, player_id)``, so borrowing the mock's map would check
    twenty keepers against the wrong seats, match none, and read all twenty as competitive
    bids: the most expensive picks of the night, silently poisoning inflation, skew and every
    threat read.

    What makes it dangerous rather than obvious is that the user is slot 3 in *both* maps. The
    one seat anybody would check by eye is the one that agrees.
    """
    live = make(PICKS, store, seating=LIVE_SEATING)
    asyncio.run(live.poll_once())

    seating = {team.slot: team.owner for team in live.snapshot().teams}
    mock = {slot: live.pipeline.identity.owner_for(slot) for slot in range(1, 11)}
    assert seating != mock, (
        "the mock and the live league genuinely disagree, or this proves nothing"
    )
    assert seating[1] == "MasonWAlpert" and mock[1] == "AJ"
    assert live.identity is not None and live.identity.slot_to_owner[1] == "MasonWAlpert"


def test_slots_stay_unnamed_until_the_live_join_confirms_them(store: OverrideStore) -> None:
    """An unmapped slot is a manager who has not joined. Labelling them with somebody else's
    name is worse than labelling them with a number, so the cockpit does the latter."""
    live = make(PICKS, store, seating=LIVE_SEATING)
    asyncio.run(live.poll_once())

    named = {team.slot: team.owner for team in live.snapshot().teams}
    assert named[8] == "slot 8", "three managers have not joined; they are numbered, not guessed"
    assert named[3] == "mattchupiccu"


def test_before_any_poll_the_cockpit_refuses_to_name_anybody(store: OverrideStore) -> None:
    """With no live seating, nothing on the page can be trusted — not the keeper classification,
    not the money-to-owner attribution. It says exactly that instead of borrowing the mock."""
    live = make(PICKS, store)
    assert live.identity is None
    assert live.my_slot is None
    assert live.owner_for(1) == "slot 1"
    assert live.unresolved_keepers()[0] == 0

    blockers = live.snapshot().blockers
    assert len(blockers) == 1 and "not been resolved from the live league" in blockers[0]


def test_seating_that_changes_rebuilds_the_keeper_classifier(store: OverrideStore) -> None:
    """Managers are still joining, and each arrival fills a seat and places two more keepers.
    A classifier cached against the old seating would keep checking keepers against seats their
    owners no longer hold."""
    live = make(PICKS, store, seating=LIVE_SEATING)
    asyncio.run(live.poll_once())
    before = live.unresolved_keepers()[0]

    client = live.client
    assert isinstance(client, FakeClient)
    client.seating = FIXTURE_SEATING
    # `-inf`, not `0.0`. `time.monotonic()`'s epoch is arbitrary and starts near zero on a
    # container, so `0.0` reads as "a minute ago" only after the process has been alive a
    # minute -- this line used `0.0` and the test failed whenever the suite ran inside that
    # window. `-inf` is epoch-independent and says what it means.
    live._identity_at = float("-inf")  # force the refresh timer
    asyncio.run(live.poll_once())

    assert live.unresolved_keepers()[0] != before, "new seating, new keys"
    assert live.snapshot().competitive_picks == 140, "and the keepers classify correctly again"


def test_seating_refreshes_on_a_clock_that_starts_near_zero(
    store: OverrideStore, monkeypatch: Any
) -> None:
    """DI-067, the regression. `time.monotonic()`'s epoch is arbitrary — on a container it
    starts near zero at boot, so a young process reports single- or double-digit seconds.

    The test above forced a refresh by setting `_identity_at = 0.0`, which reads as "over a
    minute ago" **only once the process has been alive a minute**. Run the suite inside that
    window and the refresh silently did not happen: seating never changed, keeper keys stayed at
    14, and the assertion failed. Reproduced deterministically at `monotonic() == 30`.

    Pinning a small clock here is what makes the fix hold: `-inf` is epoch-independent, `0.0`
    is not, and nothing else in the suite would tell the difference.
    """
    monkeypatch.setattr("draft_intel.api.live.time.monotonic", lambda: 30.0)

    live = make(PICKS, store, seating=LIVE_SEATING)
    asyncio.run(live.poll_once())
    before = live.unresolved_keepers()[0]

    client = live.client
    assert isinstance(client, FakeClient)
    client.seating = FIXTURE_SEATING
    live._identity_at = float("-inf")
    asyncio.run(live.poll_once())

    assert live.unresolved_keepers()[0] != before, (
        "the refresh must not depend on how long the process has been alive"
    )
    assert live.snapshot().competitive_picks == 140


def test_keepers_that_cannot_be_placed_are_a_blocker_not_a_footnote(tmp_path: Path) -> None:
    """The live condition, reproduced: an owner in the manifest with no seat in the draft.

    Each unplaceable keeper is read as a competitive bid, which moves inflation, skew and every
    threat read on the page — while the page carries on looking healthy. That is why it is a
    blocker and not an alert.

    ``manifest_keys(require=...)`` *raises* on this, which is right for a pre-draft report and
    wrong for a cockpit: a tool that refuses to start at 7pm is worth nothing. So it runs and
    says so, above the numbers it invalidates. ADR-0002's D4, one layer further in.
    """
    import shutil

    import yaml

    root = tmp_path / "repo"
    shutil.copytree(
        ROOT, root, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pyc")
    )
    # Drop one manager's alias so their two keepers cannot be placed -- which is exactly the
    # state of the real league for the three managers who have not joined.
    owners_path = root / "config" / "owners.yaml"
    owners = yaml.safe_load(owners_path.read_text())
    dropped = sorted(owners["aliases"])[0]
    del owners["aliases"][dropped]
    owners["mock_aliases"] = {}
    owners_path.write_text(yaml.safe_dump(owners))

    live = LiveDraft(
        root,
        league_id="L",
        draft_id="D",
        store=OverrideStore(root / "config" / "value_overrides.yaml"),
        client=FakeClient(PICKS),
    )
    asyncio.run(live.poll_once())
    resolved, expected, unmapped = live.unresolved_keepers()
    assert resolved < expected, "the setup did break the mapping, so the path below is live"

    blocker = next(b for b in live.snapshot().blockers if "keeper" in b)
    assert f"{expected - resolved} of {expected}" in blocker
    for owner in unmapped:
        assert owner in blocker, "the blocker names who is missing, not just how many"
    assert "competitive bid" in blocker, "and says what it costs, not just that it happened"


def test_blockers_are_separate_from_alerts(store: OverrideStore) -> None:
    """An alert is something that happened; a blocker is something wrong *now* that makes the
    figures beside it untrustworthy. In one list the invalidating one sits between two that
    are merely informational, and gets read as equally routine."""
    live = make(PICKS, store)
    asyncio.run(live.poll_once())
    snap = live.snapshot()
    assert not set(snap.blockers) & set(snap.alerts)


# ------------------------------------------------------------------- the block


def _undrafted(live: LiveDraft, picks: list[dict[str, Any]]) -> Any:
    taken = {p["player_id"] for p in picks}
    return max(
        (p for p in live.pipeline.board.players if p.in_pool_live and p.player_id not in taken),
        key=lambda p: p.baseline_value,
    )


def test_the_block_answers_what_it_is_worth_and_who_can_outbid_me(
    store: OverrideStore,
) -> None:
    """The whole question the cockpit exists to answer, mid-auction rather than at the end."""
    mid = PICKS[:70]
    live = make(mid, store)
    asyncio.run(live.poll_once())
    target = _undrafted(live, mid)
    live.nominate(target.player_id)

    block = live.snapshot().block
    assert block is not None
    assert block.name == target.name
    assert block.my_value == round(target.baseline_value, 2)
    assert block.already_drafted_by is None
    assert block.my_max_bid > 0
    assert block.ladder, "nine opponents, each with a price above which they drop out"
    assert len(block.ladder) == 9
    assert block.clears_the_field > 0


def test_a_player_already_bought_says_so_rather_than_quoting_a_price(
    store: OverrideStore,
) -> None:
    """Quoting a max bid for somebody already on a roster is an invitation to bid on them."""
    live = make(PICKS[:70], store)
    asyncio.run(live.poll_once())
    bought = PICKS[40]
    live.nominate(bought["player_id"])

    block = live.snapshot().block
    assert block is not None and block.already_drafted_by is not None


def test_nominating_nobody_clears_the_block(store: OverrideStore) -> None:
    live = make(PICKS[:70], store)
    asyncio.run(live.poll_once())
    live.nominate(_undrafted(live, PICKS[:70]).player_id)
    assert live.snapshot().block is not None

    live.nominate(None)
    assert live.snapshot().block is None


def test_the_block_uses_my_overridden_price_not_the_models(store: OverrideStore) -> None:
    """Otherwise the price table is decoration: you retune a value at 7:40pm and the cockpit
    keeps bidding off the model's number."""
    live = make(PICKS[:70], store)
    asyncio.run(live.poll_once())
    target = _undrafted(live, PICKS[:70])

    store.set(
        ValueOverride(player_id=target.player_id, name=target.name, live_value=99.0, note="my read")
    )
    live.nominate(target.player_id)

    block = live.snapshot().block
    assert block is not None
    assert block.my_value == 99.0
    assert block.tier_note == "my read"


def test_the_pipeline_picks_up_an_override_written_while_it_is_running(
    store: OverrideStore,
) -> None:
    """The cockpit caches the priced board because rebuilding it per request is far too slow
    during an auction. Caching it outright would mean an edit on /prices never arrives."""
    live = make(PICKS[:70], store)
    asyncio.run(live.poll_once())
    target = _undrafted(live, PICKS[:70])
    before = live.pipeline

    store.set(ValueOverride(player_id=target.player_id, name=target.name, live_value=77.0))
    after = live.pipeline

    assert after is not before, "the file changed, so the board was rebuilt"
    priced = next(p for p in after.board.players if p.player_id == target.player_id)
    assert priced.baseline_value == 77.0


def test_a_blacklisted_player_is_marked_on_the_block(store: OverrideStore) -> None:
    """ "Never bid" has to survive the trip to the one screen where bidding happens."""
    live = make(PICKS[:70], store)
    asyncio.run(live.poll_once())
    target = _undrafted(live, PICKS[:70])
    store.set(ValueOverride(player_id=target.player_id, name=target.name, blacklisted=True))
    live.nominate(target.player_id)

    block = live.snapshot().block
    assert block is not None and block.blacklisted is True


# ------------------------------------------------------------------- searching


def test_search_finds_a_player_by_part_of_their_name(store: OverrideStore) -> None:
    """Typed in a hurry while the room waits. Names resolve a lookup here and decide nothing."""
    live = make(PICKS, store)
    known = live.pipeline.board.players[0]
    fragment = known.name.split()[-1][:4].lower()

    hits = live.find(fragment)
    assert hits, "a fragment of a real name on the board finds somebody"
    assert all(fragment in hit.name.lower() for hit in hits)
    assert len(hits) <= 12


def test_search_on_nothing_returns_nothing_rather_than_the_whole_board(
    store: OverrideStore,
) -> None:
    live = make(PICKS, store)
    assert live.find("") == []
    assert live.find("   ") == []


# ------------------------------------------------------------------- inflation


def test_inflation_reads_the_money_and_slots_actually_left(store: OverrideStore) -> None:
    """Mid-draft is the only time this figure means anything, and it is the number that says
    whether the room is about to overpay or has run dry."""
    live = make(PICKS[:70], store)
    asyncio.run(live.poll_once())
    snap = live.snapshot()

    assert 0 < snap.inflation < 3, "a plausible multiplier, not a divide-by-zero artefact"
    assert snap.total_open_slots == 160 - 70
    assert snap.total_remaining == 2000 - sum(int(p["metadata"]["amount"]) for p in PICKS[:70])
    assert "discretionary" in snap.inflation_detail


def test_a_position_with_too_few_picks_to_read_is_omitted_not_shown_blank(
    store: OverrideStore,
) -> None:
    """A ratio computed from two picks is not a market reading, and rendering one invites a
    bidding decision built on noise."""
    early = make(PICKS[:24], store)
    asyncio.run(early.poll_once())
    assert early.snapshot().positions == ()

    late = make(PICKS, store)
    asyncio.run(late.poll_once())
    assert late.snapshot().positions, "by the end there is plenty to read"


# ------------------------------------------------------- DI-066: walk-away curves


def _at(cursor: int, store: OverrideStore, **kw: Any) -> LiveDraft:
    """A cockpit parked at a point in the draft, with precomputation **on**.

    Cursor 100 leaves the user one open slot, where a real board takes a fraction of a second.
    The cost at many open slots is not paid here: at the 16 open slots a user has before any
    pick lands it is 190 seconds, and a test that quietly spends that is the same mistake as
    one that quietly opens a socket.
    """
    live = make(PICKS, store, seating=FIXTURE_SEATING)
    live.precompute = True
    client = live.client
    assert isinstance(client, FakeClient)
    client.picks_payload = PICKS[:cursor]
    return live


async def _poll_and_wait(live: LiveDraft) -> None:
    await live.poll_once()
    task = live._walkaway_task
    if task is not None:
        await task


def test_precomputation_is_off_unless_asked_for(store: OverrideStore) -> None:
    """The same rule as the app's `poll`. Wiring minutes of optimizer work into every
    `poll_once` unconditionally turned this file from 3.6 seconds into 10 minutes — expensive
    work happening because something called a method, not because anybody wanted it."""
    live = make(PICKS, store)
    assert live.precompute is False
    asyncio.run(live.poll_once())
    assert live._walkaway_task is None
    assert live.snapshot().walkaway.state == "absent"


def test_the_app_turns_precomputation_on_exactly_when_it_polls(store: OverrideStore) -> None:
    """Both are only meaningful against a live draft, and both are expensive enough that
    neither should start because something imported the module."""
    from draft_intel.api.app import create_app

    create_app(ROOT, store, poll=False)  # the default: nothing expensive is armed
    quiet = LiveDraft(ROOT, league_id="L", draft_id="D", store=store)
    assert quiet.precompute is False

    armed = LiveDraft(ROOT, league_id="L", draft_id="D", store=store, precompute=True)
    assert armed.precompute is True


def test_the_precompute_runs_off_the_poll_path(store: OverrideStore) -> None:
    """ADR-0006 clause 4. A curve is dozens of optimizer solves and E2 measured one at 11.1s;
    awaiting that inside a poll is the design the amended gate exists to forbid. `poll_once`
    must return with the work merely *started*.

    Held open by a fake that blocks until released, so "still computing" is observable — with a
    real board at one open slot it finishes too fast to catch, and at many open slots the test
    would take minutes.

    The gate is a ``threading.Event`` and it is released in a ``finally``. The fake runs in a
    worker thread via ``asyncio.to_thread``, so an ``asyncio.Event`` would be the wrong
    primitive twice over: it belongs to a loop that thread is not running, and a fake left
    blocked forever leaks a non-daemon thread out of the test.
    """
    import threading

    released = threading.Event()

    async def scenario() -> None:
        def blocking(*_a: Any, **_k: Any) -> Any:
            released.wait(timeout=30)
            raise RuntimeError("released")  # ends the task rather than returning a fake board

        live = _at(100, store)
        try:
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr("draft_intel.api.live.walkaway_board", blocking)
                await live.poll_once()

                assert live._walkaway_task is not None and not live._walkaway_task.done()
                assert live.snapshot().walkaway.state == "computing"
                assert live.snapshot().total_remaining > 0, "the ledger answers while computing"
        finally:
            released.set()
            task = live._walkaway_task
            if task is not None:
                await task  # drains the worker thread rather than orphaning it

    asyncio.run(scenario())


def test_a_finished_precompute_reports_current_and_states_its_cost(
    store: OverrideStore,
) -> None:
    """The cost statement is not decoration: ADR-0006 requires it on the page, because at many
    open slots the honest answer is "still computing, the last one took three minutes"."""
    live = _at(100, store)
    asyncio.run(_poll_and_wait(live))

    status = live.snapshot().walkaway
    assert status.state == "current"
    assert status.curves > 0
    assert status.seconds is not None and status.seconds >= 0
    assert "took" in status.detail


def test_the_block_reads_a_precomputed_curve_rather_than_solving(
    store: OverrideStore,
) -> None:
    """The O(1) promise. The number comes off the board by dictionary lookup; there is
    deliberately no fallback that solves a missing curve, because that fallback fires exactly
    when the room is bidding."""
    live = _at(100, store)
    asyncio.run(_poll_and_wait(live))
    board = live._walkaway
    assert board is not None

    covered = board.curves[0]
    live.nominate(covered.player_id)
    block = live.snapshot().block
    assert block is not None
    assert block.walk_away == covered.walk_away_price
    assert block.curve, "the curve points come through for the chart"
    assert block.curve_trustworthy == covered.monotone


def test_a_player_outside_the_precomputed_set_says_so_rather_than_reading_as_worthless(
    store: OverrideStore,
) -> None:
    """ "No curve" and "not worth bidding on" are opposite conclusions, and a blank cannot tell
    them apart. Only twelve players get curves; the other 128 must not read as zeroes."""
    live = _at(100, store)
    asyncio.run(_poll_and_wait(live))
    board = live._walkaway
    assert board is not None

    outside = next(
        p.player_id
        for p in live.pipeline.board.players
        if p.in_pool_live and not board.covers(p.player_id)
    )
    live.nominate(outside)
    block = live.snapshot().block
    assert block is not None
    assert block.walk_away is None
    assert "not the same as not worth bidding on" in block.walk_away_note


def test_curves_are_priced_against_who_is_still_available(store: OverrideStore) -> None:
    """`ValueBoard.available()` drops keepers and nothing else. A curve computed against a pool
    still holding everyone sold in the last hour prices the user against players they cannot
    have — so the precompute filters the drafted set out itself.

    Asserted on the candidates handed to the solver rather than on the curves that come back,
    because the filtering is the thing under test and a `top`-limited output could hide a
    drafted player simply by ranking them low.
    """
    seen: list[list[Any]] = []

    async def scenario() -> None:
        def capture(candidates: Any, **kw: Any) -> Any:
            seen.append(list(candidates))
            from draft_intel.quant.walkaway import WalkAwayBoard

            return WalkAwayBoard(budget=kw["budget"], slots=kw["slots"], curves=())

        live = _at(100, store)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr("draft_intel.api.live.walkaway_board", capture)
            await _poll_and_wait(live)

    asyncio.run(scenario())

    assert seen, "the solver was called"
    drafted = {p["player_id"] for p in PICKS[:100]}
    offered = {c.player_id for c in seen[0]}
    assert offered, "and offered a pool"
    assert not offered & drafted, "nobody already bought is offered as a candidate"


def test_a_board_stops_being_current_the_moment_the_user_buys_somebody(
    store: OverrideStore,
) -> None:
    """Every price on a stale board answers a question about a roster you no longer have. The
    project keeps finding plausible figures that have been wrong since 7:40pm; this is that
    failure mode for the one number a user acts on fastest."""
    live = _at(100, store)
    asyncio.run(_poll_and_wait(live))
    assert live.snapshot().walkaway.state == "current"

    client = live.client
    assert isinstance(client, FakeClient)
    client.picks_payload = PICKS[:104]  # more picks land under the board
    live.precompute = False  # freeze it, so staleness is what is observed rather than a race
    asyncio.run(live.poll_once())

    status = live.snapshot().walkaway
    assert status.state == "stale"
    assert status.picks_since == 4
    assert "STALE" in status.detail


def test_nothing_is_precomputed_for_a_full_roster(store: OverrideStore) -> None:
    """With no open slots there is nothing to buy, so a curve is not merely stale — it is a
    question that no longer exists. Spending three minutes on it would be worse than useless."""
    live = _at(120, store)  # the user's roster is full by here
    asyncio.run(live.poll_once())

    mine = live.snapshot().my_team
    assert mine is not None and mine.open_slots == 0
    assert live._walkaway_task is None


def test_a_failed_precompute_is_reported_and_does_not_take_the_cockpit_down(
    store: OverrideStore, monkeypatch: Any
) -> None:
    """The cockpit's job is to keep answering the ledger question even when the expensive
    optional one fails."""

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("solver exploded")

    monkeypatch.setattr("draft_intel.api.live.walkaway_board", boom)
    live = _at(100, store)
    asyncio.run(_poll_and_wait(live))

    snap = live.snapshot()
    assert snap.walkaway.state == "absent"
    assert "solver exploded" in snap.walkaway.detail
    assert snap.total_remaining > 0, "the ledger still reports"


# ------------------------------------------------------- DI-068: live seat assignment


# Three managers joining under display names `config/owners.yaml` has never seen. This is the
# Saturday scenario, not a hypothetical: `keenankid17` and `willdeann` were in the draft room
# and invisible to the tool for days for exactly this reason, and Burt, Connor and TD have no
# alias at all.
UNKNOWN_SEATING = {
    1: "ajthebeard",
    2: "jswilliams5",
    3: "mattchupiccu",
    4: "MasonWAlpert",
    5: "someguy_92",
    6: "keenankid17",
    7: "steeveegee300",
    8: "willdeann",
    9: "bigburt2011",
    10: "td_the_legend",
}


def _unseated(store: OverrideStore, tmp_path: Path) -> LiveDraft:
    live = make(PICKS, store, seating=UNKNOWN_SEATING)
    live.seats = SeatStore(tmp_path / "seats.yaml")
    return live


def test_a_manager_under_an_unknown_display_name_leaves_their_keepers_unplaced(
    store: OverrideStore, tmp_path: Path
) -> None:
    """The baseline the fix exists for. Without it the page is correct and useless: it names
    the three managers and offers nothing to do about them."""
    live = _unseated(store, tmp_path)
    asyncio.run(live.poll_once())

    resolved, expected, unplaced = live.unresolved_keepers()
    assert (resolved, expected) == (14, 20)
    assert set(unplaced) == {"Burt", "Connor", "TD"}
    assert live.owner_for(9) == "bigburt2011", "the display name, which resolves to nobody"


def test_assigning_seats_places_every_keeper_without_a_restart(
    store: OverrideStore, tmp_path: Path
) -> None:
    """The whole point. Three assertions from a person looking at the draft room, and the
    blocker clears on the next poll — no YAML edit, no restart, mid-auction."""
    live = _unseated(store, tmp_path)
    asyncio.run(live.poll_once())
    assert live.snapshot().blockers, "there is a blocker to clear"

    for slot, owner in ((5, "Connor"), (9, "Burt"), (10, "TD")):
        live.seats.assign(SeatAssignment(slot=slot, owner=owner, note="confirmed in the room"))
    asyncio.run(live.poll_once())

    assert live.unresolved_keepers()[0] == 20
    assert live.snapshot().blockers == ()
    assert live.owner_for(9) == "Burt"
    assert live.snapshot().competitive_picks == 140, "and the keepers classify correctly"


def test_a_seat_lands_on_the_next_poll_not_a_minute_later(
    store: OverrideStore, tmp_path: Path
) -> None:
    """Identity is re-resolved on a 60s timer, which is right for managers drifting in and
    wrong for a seat the user just typed while staring at the blocker naming that manager."""
    live = _unseated(store, tmp_path)
    asyncio.run(live.poll_once())
    assert live.unresolved_keepers()[0] == 14

    live.seats.assign(SeatAssignment(slot=9, owner="Burt"))
    asyncio.run(live.poll_once())  # well inside the 60s refresh window

    assert live.unresolved_keepers()[0] == 16, "the file changed, so the timer was bypassed"


def test_the_projected_count_moves_immediately_and_the_live_one_does_not(
    store: OverrideStore, tmp_path: Path
) -> None:
    """Both figures are needed and neither substitutes for the other.

    Report only the live one and a correct assignment looks like it failed — the count cannot
    move until the classifier is rebuilt a poll later. Report only the projected one and the
    blocker clears before the classifier agrees, which is the optimistic direction and the one
    that lies about what the ledger is currently doing.
    """
    live = _unseated(store, tmp_path)
    asyncio.run(live.poll_once())

    live.seats.assign(SeatAssignment(slot=9, owner="Burt"))
    assert live.keepers_if_seated() == 16, "what you just asserted"
    assert live.unresolved_keepers()[0] == 14, "what the ledger is still classifying against"

    asyncio.run(live.poll_once())
    assert live.unresolved_keepers()[0] == 16, "and now they agree"


def test_an_assigned_owner_does_not_also_keep_their_resolved_seat(
    store: OverrideStore, tmp_path: Path
) -> None:
    """Moving somebody must not leave them in two places. `owner_to_slot` and `slot_to_owner`
    are read by different consumers — the keeper classifier one, the threat ladder the other —
    so a disagreement between them means the two describe different drafts."""
    live = make(PICKS, store, seating=FIXTURE_SEATING)
    live.seats = SeatStore(tmp_path / "seats.yaml")
    asyncio.run(live.poll_once())
    identity = live.identity
    assert identity is not None and identity.slot_for("Connor") == 5

    live.seats.assign(SeatAssignment(slot=8, owner="Connor"))
    asyncio.run(live.poll_once())

    moved = live.identity
    assert moved is not None
    assert moved.slot_for("Connor") == 8, "the assertion wins"
    assert moved.slot_to_owner[8] == "Connor"
    assert list(moved.owner_to_slot.values()).count(8) == 1, "one owner in that seat"
    assert moved.slot_to_owner.get(5) != "Connor", "and not still in the old one"


def test_seats_survive_a_restart(store: OverrideStore, tmp_path: Path) -> None:
    """Typed at 7:10, still true at 8:00 after the process died. Same promise the price
    overrides make, for the same reason."""
    live = _unseated(store, tmp_path)
    live.seats.assign(SeatAssignment(slot=9, owner="Burt", note="he confirmed"))

    reopened = SeatStore(tmp_path / "seats.yaml").load()
    assert reopened[9].owner == "Burt"
    assert reopened[9].note == "he confirmed"

    fresh = _unseated(store, tmp_path)
    asyncio.run(fresh.poll_once())
    assert fresh.owner_for(9) == "Burt"


def test_the_seat_file_is_editable_by_hand(tmp_path: Path) -> None:
    """It is an interface, so it explains itself and a hand-written entry loads."""
    seats = SeatStore(tmp_path / "seats.yaml")
    seats.assign(SeatAssignment(slot=9, owner="Burt"))
    text = seats.path.read_text()

    assert "edit by hand" in text
    assert "NOT their Sleeper display name" in text
    assert seats.load()[9].owner == "Burt"


def test_no_seats_leaves_the_resolved_identity_untouched(
    store: OverrideStore, tmp_path: Path
) -> None:
    """`apply_seats` on an empty map must be the identity function, not a rebuild that happens
    to agree — the rebuild is where an owner could silently lose their seat."""
    live = make(PICKS, store, seating=FIXTURE_SEATING)
    live.seats = SeatStore(tmp_path / "absent.yaml")
    asyncio.run(live.poll_once())

    identity = live.identity
    assert identity is not None
    assert identity.slot_to_owner[3] == "mattchupiccu"
    assert live.unresolved_keepers()[0] == 20
