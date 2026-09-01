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
from draft_intel.models import (
    BudgetAdjustment,
    ManualKeeper,
    PickClass,
    PickObserved,
    PickRemoved,
    PickSnapshot,
    Reclassify,
    Revert,
)
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
    """The charter's strongest guarantee that draft night is fine either way.

    Each case gets ONLY the detection mechanism it would really have. Case A carries
    ``is_keeper: true`` and an EMPTY manifest, so `is_keeper` must do all the work. Case B
    carries ``is_keeper: false`` and the full manifest, so the manifest must. Agreement means
    two independent mechanisms reached the same state.

    The earlier version handed the same manifest-backed classifier to both cases. Since
    `is_keeper` never reaches DerivedState, that assertion held no matter what the classifier
    did -- it passed with the classifier replaced by a constant function. See
    `test_the_equivalence_gate_is_not_vacuous` below, which pins that down.
    """
    is_keeper_only = KeeperClassifier(manifest_keys=frozenset())
    case_a = state_for(to_case_a(payload, KEEPER_PICK_NOS), is_keeper_only)
    case_b = state_for(payload, classifier)

    assert case_a.model_dump() == case_b.model_dump()
    assert case_a.keeper_spend() == EXPECTED_KEEPER_SPEND
    assert len(case_a.competitive_seq) == 140


def test_the_equivalence_gate_is_not_vacuous(payload, classifier):
    """Break each mechanism in turn and confirm the gate actually notices.

    Without this, the equivalence assertion above could be satisfied by two identically
    broken halves.
    """
    case_a_payload = to_case_a(payload, KEEPER_PICK_NOS)
    good_a = state_for(case_a_payload, KeeperClassifier(manifest_keys=frozenset()))
    good_b = state_for(payload, classifier)

    # Case A with is_keeper stripped -- nothing left to detect keepers with.
    broken_a = state_for(payload, KeeperClassifier(manifest_keys=frozenset()))
    assert broken_a.model_dump() != good_b.model_dump()
    assert broken_a.keeper_spend() == 0
    assert len(broken_a.competitive_seq) == 160

    # Case B with the manifest emptied -- likewise.
    broken_b = state_for(payload, KeeperClassifier(manifest_keys=frozenset()))
    assert broken_b.model_dump() != good_a.model_dump()

    # A constant classifier must not satisfy the gate.
    const = state_for(case_a_payload, lambda _p: PickClass.COMPETITIVE)
    assert const.model_dump() != good_b.model_dump()


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


# --------------------------------------------------------------------------------------
# Regressions for the blocking findings raised by code-reviewer (DI-040) and evaluator
# (DI-EVAL-1). Each test fails against the implementation as it stood at commit fa4f177.
# --------------------------------------------------------------------------------------


def obs(seq, pick_no, player_id, slot, amount, is_keeper=False):
    return PickObserved(
        seq=seq,
        pick=PickSnapshot(
            pick_no=pick_no, player_id=player_id, slot=slot, amount=amount, is_keeper=is_keeper
        ),
    )


def test_fold_accepts_a_generator(payload, classifier):
    """B1: `events` was iterated twice, so a generator silently produced empty state."""
    events = replay_all(payload)
    from_list = fold(events, slots=SLOTS, classifier=classifier)
    from_gen = fold((e for e in events), slots=SLOTS, classifier=classifier)
    assert from_gen.model_dump() == from_list.model_dump()
    assert from_gen.total_spent == 1979


def test_revert_cannot_delete_a_pick():
    """B2: reverting a PickObserved used to remove the pick and its money."""
    state = fold([obs(1, 1, "A", 1, 50), Revert(seq=2, target_seq=1)], slots=SLOTS)
    assert state.teams[1].spent == 50
    assert any("refused" in a and "revert" in a for a in state.alerts)


def test_revert_of_a_revert_reinstates_the_override():
    """B3: undo-of-undo was a silent no-op."""
    base: list = [BudgetAdjustment(seq=1, slot=1, delta=-25)]
    assert fold(base, slots=SLOTS).teams[1].budget == 175
    once = [*base, Revert(seq=2, target_seq=1)]
    assert fold(once, slots=SLOTS).teams[1].budget == 200
    twice = [*once, Revert(seq=3, target_seq=2)]
    assert fold(twice, slots=SLOTS).teams[1].budget == 175


def test_revert_of_seq_zero_is_refused():
    """B4: seq 0 means 'unstamped'; targeting it detonated every unstamped event."""
    state = fold([obs(0, 1, "A", 1, 50), Revert(seq=1, target_seq=0)], slots=SLOTS)
    assert state.teams[1].spent == 50
    assert any("seq 0" in a for a in state.alerts)


def test_duplicate_sequence_numbers_are_reported():
    state = fold([obs(1, 1, "A", 1, 10), obs(1, 2, "B", 2, 20)], slots=SLOTS)
    assert any("duplicate event seq" in a for a in state.alerts)


def test_fold_orders_by_seq_not_by_list_position():
    """B5: [Removed, Observed] used to resurrect a removed pick."""
    forward = [obs(1, 1, "A", 1, 50), PickRemoved(seq=2, pick_no=1)]
    backward = [PickRemoved(seq=2, pick_no=1), obs(1, 1, "A", 1, 50)]
    assert fold(forward, slots=SLOTS).teams[1].spent == 0
    assert fold(backward, slots=SLOTS).teams[1].spent == 0
    assert fold(backward, slots=SLOTS).model_dump() == fold(forward, slots=SLOTS).model_dump()


def test_manual_keeper_on_the_wrong_slot_is_still_counted_once():
    """B6 / eval B3: a slot mismatch used to charge $60 for one $30 keeper, silently."""
    state = fold(
        [
            ManualKeeper(seq=1, slot=3, player_id="P", amount=30),
            obs(2, 5, "P", 4, 30),
        ],
        slots=SLOTS,
    )
    assert state.teams[3].spent == 0
    assert state.teams[4].spent == 30
    assert state.total_spent == 30
    assert any("SLOT MISMATCH" in a for a in state.alerts)
    assert state.superseded


def test_a_player_on_two_rosters_is_reported():
    state = fold([obs(1, 1, "P", 1, 10), obs(2, 2, "P", 2, 20)], slots=SLOTS)
    assert any("held by slots [1, 2]" in a for a in state.alerts)


def test_competitive_seq_stays_dense_after_reclassification(payload, classifier):
    """B7: renumbering is correct, but must stay coherent and must never be cached."""
    events = replay_all(payload)
    before = fold(events, slots=SLOTS, classifier=classifier)
    after = fold(
        [*events, Reclassify(seq=10_000, pick_no=21, pick_class=PickClass.KEEPER)],
        slots=SLOTS,
        classifier=classifier,
    )
    assert sorted(before.competitive_seq.values()) == list(range(1, 141))
    assert sorted(after.competitive_seq.values()) == list(range(1, 140))
    assert 21 not in after.competitive_seq


def test_budget_adjustment_for_an_unknown_slot_reconciles_and_alerts():
    """Eval B2a: override_delta counted it while no budget received it."""
    state = fold([obs(1, 1, "A", 1, 50), BudgetAdjustment(seq=2, slot=11, delta=-40)], slots=SLOTS)
    assert state.total_spent + state.total_remaining == 200 * len(state.teams) - 40
    assert state.total_spent + state.total_remaining == 2000 + state.override_delta + 200
    assert any("slot 11 is referenced" in a for a in state.alerts)


def test_pick_on_an_unknown_slot_alerts_rather_than_minting_a_silent_team():
    """Eval B2b: an unknown slot used to appear as a fresh $200 team with no warning."""
    state = fold([obs(1, 1, "A", 1, 50), obs(2, 2, "B", 11, 5)], slots=SLOTS)
    assert any("slot 11 is referenced" in a for a in state.alerts)
    assert state.teams[11].spent == 5


def test_over_roster_and_underfunded_teams_alert():
    """Reviewer M3 / eval M2: both were silent."""
    over = fold([obs(i, i, f"P{i}", 1, 1) for i in range(1, 19)], slots=SLOTS)
    assert any("17 roster spots" in a or "16 roster spots" in a for a in over.alerts)
    broke = fold([obs(1, 1, "A", 1, 200)], slots=SLOTS)
    assert any("cannot fill its roster" in a for a in broke.alerts)


def test_keeper_undercount_alerts_when_expected(payload, classifier):
    """Eval M1: only over-counts alerted; an under-count is equally corrupting."""
    short = [
        e for e in replay_all(payload) if not (isinstance(e, PickObserved) and e.pick.pick_no == 1)
    ]
    state = fold(short, slots=SLOTS, classifier=classifier, expect_keepers=True)
    assert any("holds only 1 of 2 keepers" in a for a in state.alerts)


def test_malformed_rows_do_not_stop_the_poll_and_are_surfaced():
    """B8 / B9: an out-of-range slot raised out of parse_picks; drops were silent."""
    from draft_intel.sleeper.poller import parse_picks

    result = parse_picks(
        [
            {"pick_no": 1, "draft_slot": 1, "player_id": "A", "metadata": {"amount": "10"}},
            {"pick_no": 2, "draft_slot": 99, "player_id": "B", "metadata": {"amount": "20"}},
            {"pick_no": 3, "draft_slot": 2, "metadata": {"amount": "30"}},
            {"pick_no": 4, "draft_slot": 2, "player_id": "D", "metadata": {"amount": "oops"}},
        ]
    )
    assert set(result.picks) == {1, 4}
    assert len(result.rejects) == 3
    assert any("99" in r or "validation" in r for r in result.rejects)
    assert any("missing player_id" in r for r in result.rejects)
    assert any("unparseable" in r for r in result.rejects)
