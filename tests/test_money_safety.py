"""Money-safety regressions: HANDOFF §4.1 D1, D2, D3.

Every test in this file was written against the *old* code and confirmed to fail there
before the fix landed, with ``PYTHONPATH`` forced to a pinned worktree of the previous
commit. The editable install resolves ``draft_intel`` from a ``.pth`` entry, so a
``PYTHONPATH`` prefix genuinely wins -- but a naive worktree run without it silently
imports the *new* source and passes spuriously, which is how earlier rounds shipped
regression tests that could never fail.

The shape each test guards against is the one this project keeps producing: not a crash,
but a plausible-looking number that has been wrong since 7:40pm.
"""

from __future__ import annotations

import copy
import json
import pickle
from pathlib import Path

import pytest

from draft_intel.domain.ledger import fold
from draft_intel.models import (
    DerivedState,
    FrozenDict,
    ManualKeeper,
    PickObserved,
    PickSnapshot,
)
from draft_intel.replay.harness import load_picks
from draft_intel.sleeper.poller import parse_amount, parse_picks

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
SLOTS = range(1, 11)


# ---------------------------------------------------------------------------
# D1 -- a negative amount must never reach a team's ledger unannounced
# ---------------------------------------------------------------------------


def test_manual_keeper_negative_amount_is_alerted():
    """D1, the headline defect: $686 max bid in a $200 league, three rounds running.

    ``ManualKeeper`` is the primary path by which real keeper prices enter the system --
    Sleeper publishes no auction value, so retention prices are typed in by hand. It never
    touches the parser, so every guard added to ``parse_amount`` across three rounds left
    this path wide open.
    """
    state = fold([ManualKeeper(seq=1, slot=1, player_id="P", amount=-500)], slots=SLOTS)
    team = state.teams[1]

    # The money is still recorded as observed -- the fold never silently discards a fact --
    # but it can no longer pass for a real ledger.
    assert team.spent == -500
    assert team.max_bid == 686, "the absurd figure itself is unchanged; what changes is silence"
    assert any("NEGATIVE AMOUNT" in alert for alert in state.alerts), (
        f"a -$500 keeper must be alerted, got alerts={state.alerts}"
    )
    assert any("P" in alert for alert in state.alerts), "the alert must name the entry to fix"


def test_negative_pick_amount_is_alerted():
    """The same guard on the feed path, not only the manual one."""
    pick = PickSnapshot(pick_no=1, player_id="P", slot=4, amount=-40, is_keeper=False)
    state = fold([PickObserved(seq=1, pick=pick)], slots=SLOTS)

    assert any("NEGATIVE AMOUNT" in alert for alert in state.alerts)
    assert any("slot 4" in alert for alert in state.alerts)


def test_a_clean_ledger_raises_no_negative_alert():
    """The guard must not fire on honest input, or it will be tuned out by draft night."""
    pick = PickSnapshot(pick_no=1, player_id="P", slot=4, amount=40, is_keeper=False)
    state = fold(
        [PickObserved(seq=1, pick=pick), ManualKeeper(seq=2, slot=5, player_id="Q", amount=0)],
        slots=SLOTS,
    )
    assert not [a for a in state.alerts if "NEGATIVE AMOUNT" in a]


@pytest.mark.parametrize(
    "raw",
    [
        "-500",  # guarded before this fix
        -500,  # guarded before this fix
        "-500.0",  # silent: the decimal arm never applied the integer arm's sign check
        "-5.0",  # silent
        -5.0,  # silent: the float arm never applied it either
        "$-5.0",
        "-1,200.0",
    ],
)
def test_parse_amount_complains_about_every_negative_form(raw):
    """D1: the sign check lived on one arm of a four-arm function.

    The shipped ``test_negative_amounts_are_flagged`` asserted exactly the two forms that
    had been fixed -- ``"-5"`` and ``-5`` -- while its own docstring named the $686 case
    that still reproduced. Parametrising over every arm is what makes this test able to fail.
    """
    value, complaint = parse_amount(raw)
    assert value < 0, f"{raw!r} should read as a negative number, got {value}"
    assert complaint is not None, f"{raw!r} parsed to {value} with no complaint"
    assert "negative" in complaint


def test_parse_amount_still_reads_honest_values():
    """Guard against closing D1 by making the parser refuse everything."""
    assert parse_amount("35") == (35, None)
    assert parse_amount("$35") == (35, None)
    assert parse_amount("1,200") == (1200, None)
    assert parse_amount("35.0") == (35, None)
    assert parse_amount(0) == (0, None)


# ---------------------------------------------------------------------------
# D2 -- a duplicate pick number must not eat a pick's money
# ---------------------------------------------------------------------------


def _row(pick_no: int, player_id: str, slot: int, amount: int) -> dict:
    return {
        "pick_no": pick_no,
        "player_id": player_id,
        "draft_slot": slot,
        "is_keeper": False,
        "metadata": {"amount": str(amount), "first_name": "A", "last_name": "B"},
    }


def test_duplicate_pick_no_in_a_payload_is_rejected():
    """D2: the snapshot map is keyed on ``pick_no``, so the second row overwrote the first."""
    result = parse_picks([_row(30, "AAA", 1, 10), _row(30, "BBB", 2, 32)])

    assert len(result.picks) == 1, "the collision itself is inherent to a pick_no-keyed map"
    assert result.rejects, "but losing $10 of a real bid must not be silent"
    reject = " ".join(result.rejects)
    assert "30" in reject and "AAA" in reject and "10" in reject


def test_duplicate_pick_no_against_the_real_fixture_reports_the_lost_money():
    """The handoff's exact reproduction: $32 vanishes, conservation still 'holds'."""
    payload = copy.deepcopy(load_picks(FIXTURES / "picks.json"))
    # Relabel a later pick onto number 30. The payload is in pick order, so the row that
    # legitimately holds 30 is overwritten by it and *that* row's money is what disappears.
    overwritten = next(p for p in payload if p["pick_no"] == 30)
    lost = int(overwritten["metadata"]["amount"])
    assert lost == 32, "the handoff's reproduction turns on this being $32"
    next(p for p in payload if p["pick_no"] == 55)["pick_no"] = 30

    result = parse_picks(payload)

    assert len(result.picks) == 159, "one pick really is gone"
    assert sum(p.amount for p in result.picks.values()) == 1979 - lost == 1947
    assert result.rejects, f"${lost} left the ledger with nothing reported"
    assert any("30" in r and str(lost) in r for r in result.rejects)


def test_duplicate_pick_observed_is_alerted_in_the_fold():
    """Defence in depth: the same collision arriving as two events, not two rows.

    ``parse_picks`` dedupes within one payload, but a spliced or replayed log can carry
    two observations of one pick number. The fold is the choke point every path crosses.
    """
    first = PickSnapshot(pick_no=30, player_id="AAA", slot=1, amount=10, is_keeper=False)
    second = PickSnapshot(pick_no=30, player_id="BBB", slot=2, amount=32, is_keeper=False)
    state = fold(
        [PickObserved(seq=1, pick=first), PickObserved(seq=2, pick=second)],
        slots=SLOTS,
    )
    assert state.total_spent == 32, "the later observation wins, as it always did"
    assert any("twice" in a for a in state.alerts), f"got alerts={state.alerts}"
    assert any("AAA" in a for a in state.alerts), "the alert must name the pick that was lost"


def test_reobserving_an_identical_pick_is_not_an_alert():
    """An idempotent re-poll of an unchanged pick is normal and must stay quiet."""
    pick = PickSnapshot(pick_no=30, player_id="AAA", slot=1, amount=10, is_keeper=False)
    state = fold(
        [PickObserved(seq=1, pick=pick), PickObserved(seq=2, pick=pick)],
        slots=SLOTS,
    )
    assert state.total_spent == 10
    assert not [a for a in state.alerts if "twice" in a]


# ---------------------------------------------------------------------------
# D3 -- derived state must refuse mutation on every path, not seven of eight
# ---------------------------------------------------------------------------

# Every mutating operation `dict` defines. The previous guard covered seven of these and
# the shipped test exercised three, which is how `__ior__` shipped unblocked.
DICT_MUTATORS = [
    "__setitem__",
    "__delitem__",
    "__ior__",
    "clear",
    "pop",
    "popitem",
    "setdefault",
    "update",
]

_ARGS = {
    "__setitem__": (99, "z"),
    "__delitem__": (1,),
    "__ior__": ({99: "z"},),
    "clear": (),
    "pop": (1,),
    "popitem": (),
    "setdefault": (99, "z"),
    "update": ({99: "z"},),
}


def test_frozendict_guards_exactly_the_mutating_surface_of_dict():
    """A hole in this list is a hole in the guarantee, so assert the list is complete.

    Enumerated against ``dict``'s own API rather than against what the class happens to
    override, so adding a method to the guard cannot make this test agree with itself.
    """
    guarded = {name for name in DICT_MUTATORS if name in FrozenDict.__dict__}
    assert guarded == set(DICT_MUTATORS), f"unguarded: {set(DICT_MUTATORS) - guarded}"


@pytest.mark.parametrize("name", DICT_MUTATORS)
def test_frozendict_refuses_and_does_not_mutate(name):
    """Refusing is not enough: `__ior__` mutated in place *and* raised downstream."""
    frozen = FrozenDict({1: "a"})
    with pytest.raises(TypeError, match="immutable"):
        getattr(frozen, name)(*_ARGS[name])
    assert dict(frozen) == {1: "a"}, f"{name} raised but mutated anyway"


def test_ior_on_derived_state_neither_succeeds_nor_mutates():
    """D3 exactly as reported: the operation raises and the mutation persists.

    ``state.teams |= {...}`` is ``state.teams = state.teams.__ior__({...})``. The inherited
    ``__ior__`` mutated the dict in place and returned it; the *rebinding* then raised
    because the model is frozen. So the exception was real, the refusal was not, and a
    test that only asserted ``pytest.raises`` certified the hole as closed.
    """
    state = fold([], slots=SLOTS)
    before = dict(state.teams)

    # `mypy --strict` now rejects this line outright, which is the static half of the fix
    # working: `Mapping` has no `__ior__`. The ignore is deliberate -- the runtime guard has
    # to hold for the dynamic paths a type checker never sees, and that is what this asserts.
    with pytest.raises((TypeError, ValueError)):
        state.teams |= {99: None}  # type: ignore[operator]

    assert dict(state.teams) == before, "the mutation persisted through the raise"
    assert 99 not in state.teams


def test_derived_state_survives_copy_deepcopy_pickle_and_revalidation():
    """Blocking `pop`/`update` broke every dict reconstruction path, including pickle.

    That mattered beyond tidiness: the store round-trip and the Sprint 3 cockpit both need
    a `DerivedState` to survive serialisation, and `mypy --strict` had been given
    `dict[Any, Any]` in exchange -- a real static guarantee traded for a runtime guard
    with a hole in it.
    """
    state = fold([ManualKeeper(seq=1, slot=1, player_id="P", amount=30)], slots=SLOTS)

    assert dict(copy.copy(state.teams)) == dict(state.teams)
    assert dict(copy.deepcopy(state.teams)) == dict(state.teams)
    assert dict(pickle.loads(pickle.dumps(state.teams))) == dict(state.teams)

    for clone in (copy.copy(state), copy.deepcopy(state), pickle.loads(pickle.dumps(state))):
        assert clone.total_spent == state.total_spent
        assert isinstance(clone.teams, FrozenDict), "a clone must stay immutable"

    revalidated = DerivedState.model_validate(json.loads(state.model_dump_json()))
    assert revalidated.total_spent == state.total_spent
    assert isinstance(revalidated.teams, FrozenDict), "validation must not hand back a live dict"
    with pytest.raises(TypeError, match="immutable"):
        revalidated.teams[99] = None
