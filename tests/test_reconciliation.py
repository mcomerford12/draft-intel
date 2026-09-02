"""Keeper reconciliation alerting and the keeper-mode arming switch.

These alerts catch the errors most likely to actually happen on draft night: a wrong price
loaded by the commissioner, a keeper that quietly changed, a team that enters only one.
Each one is quiet, and each one silently corrupts a team's budget for the rest of the
evening. Catching them in the first three minutes is worth more than most of the analytics.
"""

from __future__ import annotations

from draft_intel.domain.classify import KeeperClassifier, keepers_seen, reconcile
from draft_intel.models import PickClass, PickSnapshot


def pick(
    *,
    pick_no: int = 1,
    player_id: str = "100",
    slot: int = 1,
    amount: int = 30,
    is_keeper: bool = False,
) -> PickSnapshot:
    return PickSnapshot(
        pick_no=pick_no, player_id=player_id, slot=slot, amount=amount, is_keeper=is_keeper
    )


# --------------------------------------------------------------------- classifier


def test_manifest_beats_is_keeper_false():
    """The case that actually occurs: ceremonial picks flagged is_keeper false."""
    c = KeeperClassifier(manifest_keys=frozenset({(1, "100")}))
    assert c(pick(is_keeper=False)) is PickClass.KEEPER


def test_is_keeper_true_is_still_honoured():
    """Case A: the commissioner's setup did take."""
    c = KeeperClassifier(manifest_keys=frozenset())
    assert c(pick(is_keeper=True)) is PickClass.KEEPER


def test_unmatched_pick_is_competitive_when_disarmed():
    c = KeeperClassifier(manifest_keys=frozenset())
    assert c(pick(pick_no=5)) is PickClass.COMPETITIVE


def test_armed_mode_flags_unmatched_early_picks_rather_than_assuming():
    """The backstop for a late keeper swap nobody told the user about."""
    c = KeeperClassifier(manifest_keys=frozenset(), armed=True)
    assert c(pick(pick_no=7)) is PickClass.FLAGGED
    assert c(pick(pick_no=21)) is PickClass.COMPETITIVE  # outside the arming window


def test_armed_mode_does_not_flag_manifest_matches():
    c = KeeperClassifier(manifest_keys=frozenset({(1, "100")}), armed=True)
    assert c(pick(pick_no=3)) is PickClass.KEEPER


# ------------------------------------------------------------------ reconciliation


def test_clean_slate_produces_no_alerts():
    state = {1: [("100", 30), ("101", 20)]}
    expected: dict[int, list[tuple[str, int | None]]] = {1: [("100", 30), ("101", 20)]}
    assert reconcile(state, expected) == []


def test_price_divergence_names_both_figures():
    """'Team 6's keeper loaded at $41, manifest says $38' - never a silent correction."""
    alerts = reconcile({1: [("100", 41), ("101", 20)]}, {1: [("100", 38), ("101", 20)]})
    assert any("loaded at $41" in a and "manifest says $38" in a for a in alerts)


def test_missing_keeper_is_reported():
    alerts = reconcile({1: [("100", 30)]}, {1: [("100", 30), ("101", 20)]})
    assert any("101 not recorded" in a for a in alerts)
    assert any("1 keepers recorded, expected 2" in a for a in alerts)


def test_unlisted_keeper_is_reported():
    alerts = reconcile({1: [("100", 30), ("999", 12)]}, {1: [("100", 30)]})
    assert any("999 recorded but not on the manifest" in a for a in alerts)


def test_too_many_keepers_is_reported():
    alerts = reconcile({1: [("100", 30), ("101", 20), ("102", 5)]}, {1: [("100", 30), ("101", 20)]})
    assert any("3 keepers recorded" in a for a in alerts)


def test_unknown_expected_price_skips_the_price_check():
    """Prices are null until read from the draft room; absence is not a divergence."""
    alerts = reconcile({1: [("100", 30), ("101", 20)]}, {1: [("100", None), ("101", None)]})
    assert alerts == []


def test_keepers_seen_counts_progress():
    assert keepers_seen({1: [("a", 1), ("b", 2)], 2: [("c", 3)], 3: []}) == (3, 1)
    assert keepers_seen({}) == (0, 0)


# ------------------------- DI-053: the arming backstop, wired into the product path

import json  # noqa: E402
from pathlib import Path  # noqa: E402

from draft_intel.domain.identity import build_identity, manifest_keys  # noqa: E402
from draft_intel.domain.keepers import load_manifest, resolve_manifest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def _identity():
    draft = json.loads((FIXTURES / "draft.json").read_text())
    return build_identity(draft, aliases={"Me": "Matt"})


def _manifest_keys() -> frozenset[tuple[int, str]]:
    players = json.loads((FIXTURES / "players_slim.json").read_text())
    resolved = resolve_manifest(load_manifest(ROOT / "config" / "keepers.yaml"), players)
    return manifest_keys(resolved, _identity())


def test_the_product_classifier_is_armed():
    """`KeeperClassifier.armed` is the charter's classification mechanism #4 — an unmatched pick
    inside the ceremonial window is FLAGGED for confirmation rather than silently treated as a
    competitive bid. It was set True by nothing outside `tests/`, so the backstop existed and
    never ran.

    What it guards is not hypothetical: the manifest is a file typed in August, the ceremonial
    keeper picks land in the first twenty picks on the night, and a keeper swapped afterwards
    matches nothing. Unarmed, it becomes a COMPETITIVE bid against a player we still show as
    available.
    """
    from draft_intel.cli import _classifier

    built = _classifier(
        json.loads((FIXTURES / "draft.json").read_text()),
        json.loads((FIXTURES / "players_slim.json").read_text()),
        _identity(),
        require=20,
    )
    assert built.armed is True


def test_a_keeper_the_manifest_does_not_know_is_flagged_not_counted_as_competitive():
    """The exact stale-manifest scenario, on the real 160-pick fixture. Dropping one manifest key
    stands for a keeper swapped after the file was written."""
    from draft_intel.domain.classify import KeeperClassifier
    from draft_intel.domain.ledger import fold
    from draft_intel.models import PickClass
    from draft_intel.replay.harness import load_picks, replay_all

    payload = load_picks(FIXTURES / "picks.json")
    keys = _manifest_keys()
    stale = frozenset(sorted(keys)[1:])
    assert len(stale) == len(keys) - 1

    def classes(classifier: KeeperClassifier) -> dict[str, int]:
        state = fold(replay_all(payload), slots=range(1, 11), classifier=classifier)
        counts: dict[str, int] = {}
        for team in state.teams.values():
            for entry in team.roster:
                counts[entry.pick_class.name] = counts.get(entry.pick_class.name, 0) + 1
        return counts

    unarmed = classes(KeeperClassifier(manifest_keys=stale, armed=False))
    armed = classes(KeeperClassifier(manifest_keys=stale, armed=True))

    assert unarmed["COMPETITIVE"] == 141, "the unknown keeper is silently a competitive bid"
    assert armed["COMPETITIVE"] == 140, "armed, the competitive series is restored"
    assert armed[PickClass.FLAGGED.name] == 1


def test_arming_changes_nothing_when_the_manifest_resolves_fully():
    """Or the backstop would be a behaviour change rather than a backstop, and the replay gate's
    exact reproduction would move every time somebody armed or disarmed it."""
    from draft_intel.domain.classify import KeeperClassifier
    from draft_intel.domain.ledger import fold
    from draft_intel.replay.harness import load_picks, replay_all

    payload = load_picks(FIXTURES / "picks.json")
    keys = _manifest_keys()
    states = [
        fold(
            replay_all(payload),
            slots=range(1, 11),
            classifier=KeeperClassifier(manifest_keys=keys, armed=armed),
        )
        for armed in (False, True)
    ]
    assert states[0].model_dump() == states[1].model_dump()
