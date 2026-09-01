"""The Sprint 1 gate.

Replay the user's real completed mock draft and reproduce every team's final budget and
roster exactly, to the dollar. The expected figures are observed values from
``fixtures/picks.json`` - this is a golden file, not a restatement of the code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from draft_intel.domain.classify import KeeperClassifier, keepers_seen
from draft_intel.domain.identity import build_identity, manifest_keys
from draft_intel.domain.keepers import load_manifest, resolve_manifest
from draft_intel.domain.ledger import fold
from draft_intel.models import BudgetAdjustment, ManualKeeper, PickRemoved
from draft_intel.replay.harness import load_picks, replay_all, to_case_a

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
SLOTS = range(1, 11)

# Observed from fixtures/picks.json. slot -> (picks, spent).
EXPECTED = {
    1: (16, 199),
    2: (16, 200),
    3: (16, 195),
    4: (16, 200),
    5: (16, 200),
    6: (16, 200),
    7: (16, 200),
    8: (16, 200),
    9: (16, 185),
    10: (16, 200),
}
KEEPER_PICK_NOS = set(range(1, 21))
EXPECTED_KEEPER_SPEND = 549


@pytest.fixture(scope="module")
def payload() -> list[dict]:
    return load_picks(FIXTURES / "picks.json")


@pytest.fixture(scope="module")
def classifier() -> KeeperClassifier:
    players = json.loads((FIXTURES / "players_slim.json").read_text())
    draft = json.loads((FIXTURES / "draft.json").read_text())
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    identity = build_identity(draft, aliases={"Me": "Matt"})
    resolved = resolve_manifest(manifest, players)
    return KeeperClassifier(manifest_keys=manifest_keys(resolved, identity))


def state_for(payload, classifier, extra=()):
    events = replay_all(payload)
    events.extend(extra)
    return fold(events, slots=SLOTS, classifier=classifier)


def test_ledger_reproduces_every_budget_exactly(payload, classifier):
    state = state_for(payload, classifier)
    actual = {s: (t.filled_slots, t.spent) for s, t in state.teams.items()}
    assert actual == EXPECTED


def test_totals(payload, classifier):
    state = state_for(payload, classifier)
    assert state.total_spent == 1979
    assert state.total_remaining == 21
    assert state.total_spent + state.total_remaining == 2000
    assert sum(t.filled_slots for t in state.teams.values()) == 160


def test_all_twenty_keepers_classified_from_the_manifest(payload, classifier):
    """The ceremonial picks carry is_keeper false, so only the manifest can catch them."""
    state = state_for(payload, classifier)
    per_team = {s: [(r.player_id, r.amount) for r in t.keepers] for s, t in state.teams.items()}
    assert all(len(v) == 2 for v in per_team.values())
    assert keepers_seen(per_team) == (20, 10)
    assert state.keeper_spend() == EXPECTED_KEEPER_SPEND
    assert all(not p["is_keeper"] for p in payload if p["pick_no"] in KEEPER_PICK_NOS)


def test_competitive_seq_is_dense_and_excludes_keepers(payload, classifier):
    state = state_for(payload, classifier)
    assert sorted(state.competitive_seq.values()) == list(range(1, 141))
    assert not KEEPER_PICK_NOS & set(state.competitive_seq)


def test_case_a_and_case_b_are_bit_identical(payload, classifier):
    """The charter's strongest guarantee that draft night is fine either way."""
    case_b = state_for(payload, classifier)
    case_a = state_for(to_case_a(payload, KEEPER_PICK_NOS), classifier)
    assert case_a.model_dump() == case_b.model_dump()


def test_misclassification_is_detectable(payload, classifier):
    """Prove the COMPETITIVE filter is load-bearing rather than decorative.

    If deliberately mislabelling one ceremonial pick changed nothing, the filter would not
    be doing any work and the Case A/B equality above would be vacuous.
    """
    naive = KeeperClassifier(manifest_keys=frozenset())
    events = replay_all(payload)
    good = fold(events, slots=SLOTS, classifier=classifier)
    bad = fold(events, slots=SLOTS, classifier=naive)
    assert bad.competitive_seq != good.competitive_seq
    assert len(bad.competitive_seq) == 160
    assert bad.keeper_spend() == 0
    # Money is unaffected: the ledger has no keeper branch.
    assert bad.total_spent == good.total_spent


def test_pick_reversal_restores_budget_and_slot(payload, classifier):
    state = state_for(payload, classifier)
    reversed_state = state_for(payload, classifier, extra=[PickRemoved(seq=10_000, pick_no=25)])
    removed = next(p for p in payload if p["pick_no"] == 25)
    slot, amount = removed["draft_slot"], int(removed["metadata"]["amount"])
    before, after = state.teams[slot], reversed_state.teams[slot]
    assert after.spent == before.spent - amount
    assert after.filled_slots == before.filled_slots - 1
    assert after.remaining == before.remaining + amount


def test_budget_correction_persists_under_replay(payload, classifier):
    """A correction must not be fought by the next poll cycle."""
    state = state_for(
        payload,
        classifier,
        extra=[BudgetAdjustment(seq=10_000, slot=3, delta=-15, reason="verbal")],
    )
    assert state.teams[3].budget == 185
    assert state.teams[3].remaining == 185 - 195
    assert state.override_delta == -15
    assert state.total_spent + state.total_remaining == 2000 - 15


def test_manual_keeper_superseded_exactly_once(payload, classifier):
    """The real risk is double-counting, not erasure."""
    keeper = next(p for p in payload if p["pick_no"] == 1)
    manual = ManualKeeper(
        seq=0, slot=keeper["draft_slot"], player_id=keeper["player_id"], amount=32
    )
    baseline = state_for(payload, classifier)
    state = state_for(payload, classifier, extra=[manual])
    assert state.teams[1].spent == baseline.teams[1].spent
    assert state.teams[1].filled_slots == baseline.teams[1].filled_slots
    assert len(state.teams[1].keepers) == 2
    assert state.superseded and "superseded by pick" in state.superseded[0]


def test_manual_keeper_amount_mismatch_raises_a_loud_alert(payload, classifier):
    keeper = next(p for p in payload if p["pick_no"] == 1)
    manual = ManualKeeper(seq=0, slot=1, player_id=keeper["player_id"], amount=38)
    state = state_for(payload, classifier, extra=[manual])
    assert any("AMOUNT MISMATCH" in a for a in state.alerts)
    assert state.teams[1].spent == 199  # the pick won; nothing double-counted


def test_max_bid_never_strands_a_team(payload, classifier):
    """Mid-draft, every team must still be able to fill every remaining slot."""
    partial = [p for p in payload if p["pick_no"] <= 90]
    state = state_for(partial, classifier)
    for team in state.teams.values():
        if team.open_slots > 0:
            assert team.max_bid + (team.open_slots - 1) <= team.remaining
            assert team.max_bid >= 0
