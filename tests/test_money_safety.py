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
    assert team.remaining == 700

    # **This assertion changed in DI-053, and the earlier decision it replaces was deliberate.**
    # The round that added the alert pinned `max_bid == 686` with "the absurd figure itself is
    # unchanged; what changes is silence" -- on the principle that masking corruption is how it
    # survives to draft night. That principle is right about `spent` and `remaining`, which are
    # facts and are still exact above.
    #
    # It does not hold for `max_bid`, because `max_bid` is not a fact, it is a *recommendation*
    # -- and its consumers read the numbers, not `state.alerts`. Those consumers are
    # `quant.affordability` and `cli.replay`; an earlier version of this note also named the
    # optimizer, which was wrong -- `best_roster` takes a plain `budget: int` and never sees a
    # `TeamState`. The alert was necessary and not sufficient all the same: the headline defect
    # this test is named for was still reachable by every path that acts on the number.
    assert team.max_bid <= team.budget, "an impossible bid must not reach a recommendation"
    assert team.max_bid == 186, "$200 capped, less $1 held back for each of 14 other open slots"
    # And the bound is not the whole answer -- see
    # `test_the_clamp_is_a_bound_on_the_damage_and_says_so_rather_than_pretending_to_be_a_fix`.
    assert team.figures_suspect, "the figure must travel labelled, not merely bounded"
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


# ---------------------------------------- DI-053: the duplicated fields are cross-checked


def _fixture_pick(pick_no: int) -> dict:
    payload = copy.deepcopy(load_picks(FIXTURES / "picks.json"))
    return next(p for p in payload if p["pick_no"] == pick_no)


def test_a_slot_that_disagrees_with_its_metadata_is_reported():
    """The Sprint 1 design said `metadata.slot` "duplicates `draft_slot` and is used as a
    cross-check". What shipped was `a or b`, which takes the primary and never looks at the
    duplicate again, so a payload where the two disagree parsed clean and silent.

    This is the shape that matters: money debited from the wrong team still reconciles to
    $2,000. The total is right, and two managers' budgets, max bids and affordability figures
    are all wrong, all night.
    """
    row = _fixture_pick(50)
    truth = row["metadata"]["slot"]
    row["draft_slot"] = 1
    assert str(truth) != "1", "the fixture must actually disagree for this to test anything"

    result = parse_picks([row])

    assert len(result.picks) == 1, "the pick is kept: dropping loses its dollars AND its slot"
    assert result.picks[50].slot == 1, "the primary field still wins"
    reject = " ".join(result.rejects)
    assert "draft_slot" in reject and str(truth) in reject


def test_a_player_id_that_disagrees_with_its_metadata_is_reported():
    """Same gap, worse consequence. The player actually bought stays on our available board, so
    the tool goes on recommending bids for somebody already rostered, and a keeper stops
    matching the manifest on `(player_id, slot)`."""
    row = _fixture_pick(50)
    truth = row["metadata"]["player_id"]
    row["player_id"] = "9999999"

    result = parse_picks([row])

    assert result.picks[50].player_id == "9999999"
    reject = " ".join(result.rejects)
    assert "player_id" in reject and truth in reject


def test_both_conflicts_are_reported_together_rather_than_the_first_only():
    row = _fixture_pick(50)
    row["draft_slot"], row["player_id"] = 1, "9999999"
    reject = " ".join(parse_picks([row]).rejects)
    assert "draft_slot" in reject and "player_id" in reject


def test_a_missing_primary_field_falls_back_silently_and_is_not_a_conflict():
    """The fallback is the documented behaviour and must stay quiet, or every mock pick -- which
    is the whole replay fixture -- would report a conflict it does not have."""
    for field in ("draft_slot", "player_id"):
        row = _fixture_pick(50)
        row[field] = None
        result = parse_picks([row])
        assert result.picks and not result.rejects, f"{field} fallback must be silent"


def test_the_real_fixture_reports_no_conflicts_at_all():
    """160 real picks, both duplicated fields populated on every one of them."""
    result = parse_picks(copy.deepcopy(load_picks(FIXTURES / "picks.json")))
    assert len(result.picks) == 160
    assert not result.rejects


def test_a_negative_amount_cannot_produce_a_bid_larger_than_the_league_budget():
    """M3, second half. A sign-flipped amount makes `spent` negative, which makes `remaining`
    larger than the budget, and `max_bid` returned **$686 in a $200 league**. The fold does alert
    — but `max_bid` is read by the optimizer and the affordability ladder, and neither of those
    reads alerts, so the cockpit would have advised bidding $686.

    `spent` and `remaining` still report exactly what the ledger folded. Only the *recommendation*
    is clamped, because hiding the corruption is how it survives to draft night.
    """
    state = fold(
        [
            PickObserved(
                seq=1,
                pick=PickSnapshot(pick_no=1, player_id="A", slot=1, amount=-500, is_keeper=False),
            )
        ],
        slots=range(1, 11),
    )
    team = state.teams[1]

    assert team.spent == -500, "the ledger still says what it folded"
    assert team.remaining == 700, "and so does the arithmetic"
    assert state.alerts, "the corruption is reported"
    assert team.max_bid <= team.budget, f"advised a ${team.max_bid} bid in a ${team.budget} league"


@pytest.mark.parametrize("budget", [200, 100, 350])
def test_the_clamp_does_not_touch_an_honest_ledger(budget):
    """It must bind only on impossible input, or it is silently capping real bids.

    **Parametrised over the budget because hardcoding the league's own $200 inside the clamp
    survived the entire 517-test suite.** Every test in the repo folded at the default, so
    `min(self.remaining, 200)` was indistinguishable from `min(self.remaining, self.budget)` --
    the §1 no-hardcoded-league-values rule, undetectable. $350 also covers the direction a
    `BudgetAdjustment` moves the ceiling: corrections fold into `budget`, so a +$150 commissioner
    correction must raise the cap with it rather than being clipped back to $200.
    """
    state = fold([], slots=range(1, 11), budget=budget, total_slots=16)
    team = state.teams[1]
    assert team.max_bid == budget - 15, "budget less $1 held back for each of 15 other open slots"
    assert not team.figures_suspect


def test_a_budget_correction_raises_the_ceiling_it_is_clamped_against():
    """The clamp reads `self.budget`, and `BudgetAdjustment` folds into `budget` — so the two
    track. Correct by reading and, until now, entirely untested."""
    from draft_intel.models import BudgetAdjustment

    base = fold([], slots=range(1, 11), budget=200, total_slots=16).teams[1]
    raised = fold(
        [BudgetAdjustment(seq=1, slot=1, delta=150)], slots=range(1, 11), budget=200, total_slots=16
    ).teams[1]
    assert raised.max_bid == base.max_bid + 150, "the ceiling moved with the correction"


def test_the_clamp_is_a_bound_on_the_damage_and_says_so_rather_than_pretending_to_be_a_fix():
    """The clamp only binds when the negative amount dominates the whole roster sum. Add real
    spend and it goes inert while the figure stays wrong — $127 against a true $47 — because the
    information was destroyed at ingestion and no clamp can recover it.

    That is why `figures_suspect` exists. A bounded-but-wrong number is *more* dangerous than an
    absurd one: $686 in a $200 league announces itself, $127 does not. What makes the figure safe
    to publish is not the bound, it is the label.
    """
    state = fold(
        [
            PickObserved(
                seq=1,
                pick=PickSnapshot(pick_no=1, player_id="A", slot=1, amount=100, is_keeper=False),
            ),
            ManualKeeper(seq=2, slot=1, player_id="B", amount=-40),
        ],
        slots=range(1, 11),
    )
    team = state.teams[1]

    assert team.spent == 60, "the ledger reports what it folded; the truth is 140"
    assert team.max_bid > 100, "the clamp is inert here — this is the honest, uncomfortable part"
    assert team.figures_suspect, "so the figure must arrive labelled"
    assert any("NEGATIVE AMOUNT" in alert for alert in state.alerts)


def test_a_payload_conflict_alerts_even_when_the_caller_forgets_the_rejects_channel():
    """M3. The conflict used to go only to `ParseResult.rejects`, which reaches the fold only if
    the caller passes `rejects=` — and `fold`'s parameter defaults to None, so the obvious
    Sprint 3 poll loop (`parse_picks → diff_snapshots → fold`) drops it silently.

    Mid-draft that is the charter's named failure mode exactly: one corrupted `draft_slot` moves
    real money to the wrong team, wrecks two max bids, leaves conservation at $2,000 and raises
    nothing. The conflict now rides on the pick itself, so no ingestion path can forget it.
    """
    rows = [r for r in copy.deepcopy(load_picks(FIXTURES / "picks.json")) if r["pick_no"] <= 60]
    moved = next(r for r in rows if r["pick_no"] == 55)
    truth = moved["metadata"]["slot"]
    moved["draft_slot"] = 1
    assert str(truth) != "1"

    result = parse_picks(rows)
    log = [
        PickObserved(seq=i + 1, pick=pick)
        for i, pick in enumerate(sorted(result.picks.values(), key=lambda p: p.pick_no))
    ]
    state = fold(log, slots=SLOTS)  # deliberately NOT passing rejects=

    assert state.total_spent + state.total_remaining == 2000, (
        "conservation still holds; that is the trap"
    )
    conflict_alerts = [a for a in state.alerts if "PAYLOAD CONFLICT" in a]
    assert conflict_alerts, "the wrong-team debit must be announced without a side channel"
    assert "55" in conflict_alerts[0] and str(truth) in conflict_alerts[0]


def test_a_clean_payload_raises_no_conflict_alert():
    """All 160 real picks, both duplicated fields populated on every one."""
    result = parse_picks(copy.deepcopy(load_picks(FIXTURES / "picks.json")))
    log = [
        PickObserved(seq=i + 1, pick=pick)
        for i, pick in enumerate(sorted(result.picks.values(), key=lambda p: p.pick_no))
    ]
    state = fold(log, slots=SLOTS)
    assert not [a for a in state.alerts if "PAYLOAD CONFLICT" in a]


@pytest.mark.parametrize("field,falsy", [("player_id", ""), ("draft_slot", 0)])
def test_a_falsy_primary_field_falls_back_without_claiming_the_primary_won(field, falsy):
    """m2. The fallback uses `or`, so any falsy primary takes the metadata value — but the
    conflict test used `is not None`, so `player_id: ""` reported a conflict saying "the primary
    field wins" while the *duplicate* was in effect. Sleeper does send `""` for `player_id` on
    some rows, so that was a spurious complaint every poll carrying a message that misstated
    which number was live."""
    from draft_intel.sleeper.poller import parse_pick

    row = next(r for r in copy.deepcopy(load_picks(FIXTURES / "picks.json")) if r["pick_no"] == 50)
    row[field] = falsy
    pick, complaint = parse_pick(row)

    assert pick is not None
    assert complaint is None, "a falsy primary is a fallback, not a disagreement"
    assert pick.conflicts == ()
