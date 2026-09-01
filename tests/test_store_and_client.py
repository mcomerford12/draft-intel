"""Persistence, crash-restart recovery, and client resilience."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from draft_intel.domain.classify import KeeperClassifier
from draft_intel.domain.identity import build_identity, manifest_keys
from draft_intel.domain.keepers import load_manifest, resolve_manifest
from draft_intel.domain.ledger import fold
from draft_intel.models import BudgetAdjustment, ManualKeeper, PickClass, Reclassify
from draft_intel.replay.harness import load_picks, replay_all
from draft_intel.sleeper.client import API_V1, Breaker, CircuitOpen, SleeperClient
from draft_intel.store.db import EventStore, make_engine

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
SLOTS = range(1, 11)


@pytest.fixture(scope="module")
def classifier() -> KeeperClassifier:
    players = json.loads((FIXTURES / "players_slim.json").read_text())
    draft = json.loads((FIXTURES / "draft.json").read_text())
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    identity = build_identity(draft, aliases={"Me": "Matt"})
    return KeeperClassifier(
        manifest_keys=manifest_keys(resolve_manifest(manifest, players), identity)
    )


def test_crash_restart_recovers_identical_state_including_overrides(tmp_path, classifier):
    """Kill the process mid-draft and the resumed state must be bit-identical."""
    payload = load_picks(FIXTURES / "picks.json")
    events = replay_all(payload)
    overrides: list = [
        BudgetAdjustment(slot=4, delta=-12, reason="verbal correction"),
        ManualKeeper(slot=7, player_id="99999", amount=8),
        Reclassify(pick_no=30, pick_class=PickClass.KEEPER),
    ]

    db = tmp_path / "draft.db"
    store = EventStore(make_engine(db))
    stored = store.append([*events, *overrides])
    before = fold(stored, slots=SLOTS, classifier=classifier)

    # Simulate a crash: drop everything in memory, reopen from disk alone.
    del store
    reopened = EventStore(make_engine(db))
    after = fold(reopened.load(), slots=SLOTS, classifier=classifier)

    assert after.model_dump() == before.model_dump()
    assert reopened.count() == len(events) + len(overrides)
    assert after.override_delta == -12
    assert after.teams[7].filled_slots == 17  # the manual keeper survived the restart


def test_sequence_numbers_are_monotonic(tmp_path):
    store = EventStore(make_engine(tmp_path / "d.db"))
    first = store.append([BudgetAdjustment(slot=1, delta=1)])
    second = store.append([BudgetAdjustment(slot=2, delta=2)])
    assert first[0].seq < second[0].seq
    assert [e.seq for e in store.load()] == [first[0].seq, second[0].seq]


@respx.mock
async def test_client_retries_then_succeeds():
    route = respx.get(f"{API_V1}/draft/1/picks").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json=[{"pick_no": 1}])]
    )
    async with httpx.AsyncClient() as http:
        client = SleeperClient(client=http, backoff_base=0.0)
        assert await client.picks("1") == [{"pick_no": 1}]
    assert route.call_count == 2


@respx.mock
async def test_404_is_an_answer_not_a_failure():
    """The undocumented endpoints are allowed to simply not exist."""
    respx.get(f"{API_V1}/draft/9/picks").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as http:
        client = SleeperClient(client=http, backoff_base=0.0)
        assert await client.picks("9") is None
        assert client.breaker.failures == 0


@respx.mock
async def test_breaker_opens_and_stops_hammering_the_api():
    """The failure that matters is not one bad response, it is getting IP blocked."""
    route = respx.get(f"{API_V1}/draft/2/picks").mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as http:
        client = SleeperClient(
            client=http, backoff_base=0.0, breaker=Breaker(threshold=2, cooldown=60)
        )
        for _ in range(2):
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_json(f"{API_V1}/draft/2/picks", throttle=False)
        calls = route.call_count
        with pytest.raises(CircuitOpen):
            await client.get_json(f"{API_V1}/draft/2/picks", throttle=False)
        assert route.call_count == calls  # no further calls once open


def test_breaker_recovers_after_cooldown():
    b = Breaker(threshold=1, cooldown=10)
    b.record_failure(now=100.0)
    assert b.is_open(now=105.0)
    assert not b.is_open(now=111.0)
