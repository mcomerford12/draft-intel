"""Keeper reconciliation alerting and the keeper-mode arming switch.

These alerts catch the errors most likely to actually happen on draft night: a wrong price
loaded by the commissioner, a keeper that quietly changed, a team that enters only one.
Each one is quiet, and each one silently corrupts a team's budget for the rest of the
evening. Catching them in the first three minutes is worth more than most of the analytics.
"""

from __future__ import annotations

from typing import Any

import pytest

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


def test_the_classifier_can_no_longer_return_flagged_at_all():
    """DI-057 moved the backstop into the fold, and this pins that it *left*.

    A `Classifier` sees one pick with no notion of order, so the only window it could express
    was the constant `pick_no <= 20` — a fact about `fixtures/picks.json` and about no league.
    If FLAGGED ever comes back out of here, the constant has come back with it.
    """
    c = KeeperClassifier(manifest_keys=frozenset())
    assert {c(pick(pick_no=n)) for n in (1, 7, 20, 21, 160)} == {PickClass.COMPETITIVE}


def test_a_manifest_match_is_a_keeper_wherever_it_lands():
    c = KeeperClassifier(manifest_keys=frozenset({(1, "100")}))
    assert c(pick(pick_no=3)) is PickClass.KEEPER
    assert c(pick(pick_no=140)) is PickClass.KEEPER


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


def _armed(keepers_per_team: int = 2, teams: int = 10) -> dict[int, int]:
    from draft_intel.domain.classify import keepers_owed

    return keepers_owed(range(1, teams + 1), keepers_per_team=keepers_per_team)


def test_the_product_classifier_ships_disarmed():
    """DI-053 armed the backstop, DI-055 reversed it, DI-057 moved it and kept it off.

    Off is still the default, for a reason that outlived the two DI-055 objections DI-057 fixed:
    arming changes classifications, and a tool that quietly reclassifies picks the first time
    you run it is not one whose numbers you can trust. It is a decision, made once, with
    `make arm ON=1`.
    """
    from draft_intel.store.arming import ArmingStore

    assert ArmingStore(ROOT / "config" / "arming.yaml").load() is False


def test_a_missing_or_broken_arming_file_means_off_rather_than_a_crash(tmp_path: Path) -> None:
    """The switch is optional by construction. Refusing to start over it takes the tool down at
    7pm for a setting that did not have to exist; defaulting to *on* silently reclassifies picks
    because a file had a typo. Off is the only answer that is wrong in no direction."""
    from draft_intel.store.arming import ArmingStore

    assert ArmingStore(tmp_path / "absent.yaml").load() is False
    broken = tmp_path / "broken.yaml"
    broken.write_text("- not a mapping\n")
    assert ArmingStore(broken).load() is False

    store = ArmingStore(tmp_path / "written.yaml")
    assert store.set(True) is True
    assert ArmingStore(store.path).load() is True, "it must survive a fresh reader"


@pytest.mark.parametrize(
    "raw",
    ['armed: "false"', 'armed: "no"', "armed: 1", "armed: [false]", "armed: off", "armed: null"],
)
def test_only_a_real_boolean_arms_the_backstop(tmp_path: Path, raw: str) -> None:
    """`bool("false")` is True. So is `bool("no")`, and `bool([false])` — a file that plainly
    says it is off would have armed the backstop and silently reclassified picks, which is the
    exact outcome defaulting-to-off exists to prevent. Found by adversarial review."""
    from draft_intel.store.arming import ArmingStore

    path = tmp_path / "arming.yaml"
    path.write_text(raw + "\n")
    assert ArmingStore(path).load() is False, f"{raw!r} must not arm anything"


def test_a_real_yaml_true_still_arms_it(tmp_path: Path) -> None:
    """The negative case. Tightening the check must not stop `make arm ON=1` working."""
    from draft_intel.store.arming import ArmingStore

    path = tmp_path / "arming.yaml"
    path.write_text("armed: true\n")
    assert ArmingStore(path).load() is True


def test_arming_no_longer_costs_real_competitive_picks_in_a_room_with_no_ceremony():
    """**The DI-055 blocking case, now fixed.** A room that holds no ceremonial round has
    `keepers_per_team: 0`, so no slot owes anything and nothing is flagged. Under the old
    `pick_no <= 20` constant this lost the twenty most expensive picks of the night out of
    `competitive_seq` — and so out of skew, inflation, run detection and every tendency
    profile."""
    import copy

    from draft_intel.domain.classify import KeeperClassifier
    from draft_intel.domain.ledger import fold
    from draft_intel.replay.harness import load_picks, replay_all

    plain = copy.deepcopy(load_picks(FIXTURES / "picks.json"))
    for row in plain:
        row["is_keeper"] = False

    def competitive(flag_unmatched: dict[int, int] | None) -> int:
        state = fold(
            replay_all(plain),
            slots=range(1, 11),
            classifier=KeeperClassifier(manifest_keys=frozenset()),
            flag_unmatched=flag_unmatched,
        )
        return len(state.competitive_seq)

    assert competitive(None) == 160
    assert competitive(_armed(keepers_per_team=0)) == 160, "no ceremony, nothing to flag"


def test_a_real_bid_is_not_flagged_once_that_team_has_its_keepers():
    """**The second DI-055 objection, now fixed.** The old window flagged a genuine $37 bid at
    pick 20 purely because 20 <= 20. The window is per team and closes the moment that team has
    recorded the keepers the league rule says it holds, so its next bid — whenever it lands —
    is competitive."""
    from draft_intel.domain.classify import KeeperClassifier
    from draft_intel.domain.ledger import fold
    from draft_intel.replay.harness import load_picks, replay_all

    payload = load_picks(FIXTURES / "picks.json")
    state = fold(
        replay_all(payload),
        slots=range(1, 11),
        classifier=KeeperClassifier(manifest_keys=_manifest_keys()),
        flag_unmatched=_armed(),
    )
    classes = {
        entry.pick_no: entry.pick_class for team in state.teams.values() for entry in team.roster
    }
    assert classes[20] is PickClass.KEEPER, "the fixture's pick 20 is ceremonial"
    assert classes[21] is PickClass.COMPETITIVE
    assert PickClass.FLAGGED not in classes.values(), "a full manifest flags nothing"


def test_a_slot_is_never_flagged_more_times_than_it_was_expected_to_keep():
    """The bound that stops the backstop becoming a broken team. A manager whose keepers never
    arrive — someone who has not joined — would otherwise have *every* pick they make flagged
    for the rest of the night."""
    from draft_intel.domain.classify import KeeperClassifier
    from draft_intel.domain.ledger import fold
    from draft_intel.replay.harness import load_picks, replay_all

    payload = load_picks(FIXTURES / "picks.json")
    state = fold(
        replay_all(payload),
        slots=range(1, 11),
        # Nothing resolves: the worst case, ten teams owing two keepers each and never
        # recording one.
        classifier=KeeperClassifier(manifest_keys=frozenset()),
        flag_unmatched=_armed(),
    )
    per_slot = {
        slot: sum(1 for e in team.roster if e.pick_class is PickClass.FLAGGED)
        for slot, team in state.teams.items()
    }
    assert set(per_slot.values()) == {2}, "two each, never sixteen"
    assert len(state.competitive_seq) == 140


def test_a_keeper_the_manifest_does_not_know_is_flagged_not_counted_as_competitive():
    """The exact stale-manifest scenario, on the real 160-pick fixture. Dropping one manifest key
    stands for a keeper swapped after the file was written.

    Note *which* key is dropped matters to the old design and not to this one: the window is the
    slot's own obligation, so the swapped pick is caught whether it lands first or second in
    that team's ceremonial round."""
    from draft_intel.domain.classify import KeeperClassifier
    from draft_intel.domain.ledger import fold
    from draft_intel.replay.harness import load_picks, replay_all

    payload = load_picks(FIXTURES / "picks.json")
    keys = _manifest_keys()
    stale = frozenset(sorted(keys)[1:])
    assert len(stale) == len(keys) - 1

    def classes(flag_unmatched: dict[int, int] | None) -> dict[str, int]:
        state = fold(
            replay_all(payload),
            slots=range(1, 11),
            classifier=KeeperClassifier(manifest_keys=stale),
            flag_unmatched=flag_unmatched,
        )
        counts: dict[str, int] = {}
        for team in state.teams.values():
            for entry in team.roster:
                counts[entry.pick_class.name] = counts.get(entry.pick_class.name, 0) + 1
        return counts

    disarmed = classes(None)
    armed = classes(_armed())

    assert disarmed["COMPETITIVE"] == 141, "the unknown keeper is silently a competitive bid"
    assert armed["COMPETITIVE"] == 140, "armed, the competitive series is restored"
    assert armed[PickClass.FLAGGED.name] == 1


def test_a_pick_the_user_has_ruled_on_is_never_flagged_back():
    """Someone who answers "that was a real bid" and watches it come back FLAGGED will stop
    answering. A manual reclassification is the last word, in both directions."""
    from draft_intel.domain.classify import KeeperClassifier
    from draft_intel.domain.ledger import fold
    from draft_intel.models import Reclassify
    from draft_intel.replay.harness import load_picks, replay_all

    payload = load_picks(FIXTURES / "picks.json")
    keys = _manifest_keys()
    stale = frozenset(sorted(keys)[1:])
    events = list(replay_all(payload))

    def flagged(extra: list[Any]) -> set[int]:
        state = fold(
            [*events, *extra],
            slots=range(1, 11),
            classifier=KeeperClassifier(manifest_keys=stale),
            flag_unmatched=_armed(),
        )
        return {
            e.pick_no
            for team in state.teams.values()
            for e in team.roster
            if e.pick_class is PickClass.FLAGGED and e.pick_no is not None
        }

    victim = next(iter(flagged([])))
    assert (
        flagged([Reclassify(seq=1_000_001, pick_no=victim, pick_class=PickClass.COMPETITIVE)])
        == set()
    )
    assert (
        flagged([Reclassify(seq=1_000_001, pick_no=victim, pick_class=PickClass.KEEPER)]) == set()
    )


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
            classifier=KeeperClassifier(manifest_keys=keys),
            flag_unmatched=flag_unmatched,
        )
        for flag_unmatched in (None, _armed())
    ]
    assert states[0].model_dump() == states[1].model_dump()


def test_the_window_holds_when_the_ceremonial_round_is_not_at_picks_1_to_20():
    """**DI-057's last criterion, and the one the old design could not have passed.**

    Every fixture in this repo puts the ceremonial round at picks 1-20, which is exactly why
    `pick_no <= 20` looked correct for two cards. So this synthesises a draft where it is not:
    ten teams, each opening with two ordinary bids and *then* taking its two keepers, at picks
    21-40. Under the old constant that payload flags twenty genuine bids and misses all twenty
    keepers — the failure inverted, twice over.

    Here the window is each team's own first two picks, so the twenty opening bids are exactly
    what gets asked about and the keepers land as keepers on the manifest match. That is the
    right answer for the wrong-looking layout, which is the whole point.
    """
    from draft_intel.domain.classify import KeeperClassifier
    from draft_intel.domain.ledger import fold
    from draft_intel.models import PickObserved, PickSnapshot

    keepers = {slot: (f"K{slot}a", f"K{slot}b") for slot in range(1, 11)}
    picks: list[PickSnapshot] = []
    pick_no = 0
    for round_no in range(4):
        for slot in range(1, 11):
            pick_no += 1
            # Rounds 0-1 are ordinary bids; rounds 2-3 are the ceremonial round, late.
            player = keepers[slot][round_no - 2] if round_no >= 2 else f"P{pick_no}"
            picks.append(
                PickSnapshot(
                    pick_no=pick_no, player_id=player, slot=slot, amount=5, is_keeper=False
                )
            )
    events = [PickObserved(seq=i + 1, pick=p) for i, p in enumerate(picks)]
    keys = frozenset((slot, pid) for slot, pair in keepers.items() for pid in pair)

    state = fold(
        events,
        slots=range(1, 11),
        classifier=KeeperClassifier(manifest_keys=keys),
        flag_unmatched=_armed(),
    )
    classes = {
        entry.pick_no: entry.pick_class for team in state.teams.values() for entry in team.roster
    }

    assert all(classes[n] is PickClass.FLAGGED for n in range(1, 21)), (
        "each team's first two picks are its window, wherever the ceremony actually falls"
    )
    assert all(classes[n] is PickClass.KEEPER for n in range(21, 41)), (
        "the manifest still matches keepers at picks 21-40; the window never gated that"
    )
    assert len(state.competitive_seq) == 0


# ------------------------- DI-078: the armed backstop meets manual keeper entry
#
# Two features built four cards apart, whose intersection is the case that matters most.
# A manager who never joins has no ceremonial picks in the feed, so their keepers can only
# arrive through the manual form (charter §2 makes that the primary price path) — and arming is
# exactly what gets recommended when that happens.


def _typed_and_bid(manual_per_slot: int, bids_per_slot: int = 4) -> Any:
    """N keepers typed by hand per team, then genuine competitive bids from everybody."""
    from draft_intel.domain.classify import KeeperClassifier
    from draft_intel.domain.ledger import fold
    from draft_intel.models import ManualKeeper, PickObserved

    events: list[Any] = []
    seq = pick_no = 0
    for slot in range(1, 11):
        for k in range(manual_per_slot):
            seq += 1
            events.append(ManualKeeper(seq=seq, slot=slot, player_id=f"K{slot}{k}", amount=20))
    for _round in range(bids_per_slot):
        for slot in range(1, 11):
            pick_no += 1
            seq += 1
            events.append(
                PickObserved(
                    seq=seq,
                    pick=PickSnapshot(
                        pick_no=pick_no,
                        player_id=f"P{pick_no}",
                        slot=slot,
                        amount=15,
                        is_keeper=False,
                    ),
                )
            )
    return fold(
        events,
        slots=range(1, 11),
        classifier=KeeperClassifier(manifest_keys=frozenset()),
        flag_unmatched=_armed(),
    )


def _flagged(state: Any) -> list[int]:
    return [
        entry.amount
        for team in state.teams.values()
        for entry in team.roster
        if entry.pick_class is PickClass.FLAGGED
    ]


def test_a_keeper_typed_by_hand_settles_the_slots_debt_like_one_from_the_feed():
    """**The blocking defect.** `owed` was decremented only inside the pick loop, and a manual
    keeper is not a pick — so a slot that visibly held both its keepers still owed two, and its
    first two *real bids* were flagged out of the competitive series. Twenty bids worth $300, no
    alert, every team reading "2 keepers held"."""
    state = _typed_and_bid(manual_per_slot=2)

    assert _flagged(state) == [], "the debt is settled; nothing to ask about"
    assert len(state.competitive_seq) == 40, "every genuine bid stays in the series"
    assert sum(len(t.keepers) for t in state.teams.values()) == 20


def test_the_window_shrinks_with_the_debt_rather_than_over_asking():
    """One keeper outstanding earns one question, not two. Leaving the window at its full width
    asks twice as many as there are missing keepers, and every unanswered question holds a real
    bid out of inflation, skew and every tendency profile."""
    assert len(_flagged(_typed_and_bid(manual_per_slot=1))) == 10, "ten teams, one each"
    assert len(_flagged(_typed_and_bid(manual_per_slot=0))) == 20, "nothing typed, two each"


def test_manual_entry_does_not_disarm_the_backstop_for_what_is_still_missing():
    """The other direction. Settling one keeper must not stop the tool asking about the other —
    that would turn a partial correction into a silent disarm."""
    state = _typed_and_bid(manual_per_slot=1)
    per_slot = {
        slot: sum(1 for e in team.roster if e.pick_class is PickClass.FLAGGED)
        for slot, team in state.teams.items()
    }
    assert set(per_slot.values()) == {1}, "every team still asked about its one missing keeper"
