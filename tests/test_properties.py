"""Property tests for the invariants that keep money correct under any sequence of events.

These are the tests the charter says never to cut. Every one of them protects against a
class of silent corruption where the tool keeps running and keeps giving confident advice
while a team's budget has been wrong since 7:40pm.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from draft_intel.domain.keepers import retention_price
from draft_intel.domain.ledger import fold
from draft_intel.models import (
    BudgetAdjustment,
    ManualKeeper,
    PickAmended,
    PickObserved,
    PickRemoved,
    PickSnapshot,
    Revert,
)
from draft_intel.sleeper.poller import diff_snapshots, parse_amount

SLOTS = range(1, 11)

picks = st.builds(
    PickSnapshot,
    pick_no=st.integers(1, 160),
    player_id=st.integers(1, 400).map(str),
    slot=st.integers(1, 10),
    amount=st.integers(0, 60),
    is_keeper=st.booleans(),
)


def _seq(events):
    return [e.model_copy(update={"seq": i + 1}) for i, e in enumerate(events)]


@st.composite
def event_logs(draw):
    """Arbitrary interleavings of observations, reversals and amendments."""
    chosen = draw(st.lists(picks, min_size=0, max_size=25, unique_by=lambda p: p.pick_no))
    events: list = []
    for pick in chosen:
        events.append(PickObserved(pick=pick))
        if draw(st.booleans()):
            events.append(
                PickAmended(pick=pick.model_copy(update={"amount": draw(st.integers(0, 60))}))
            )
        if draw(st.integers(0, 4)) == 0:
            events.append(PickRemoved(pick_no=pick.pick_no))
    return _seq(events)


@given(event_logs())
@settings(max_examples=200, deadline=None)
def test_money_conservation_without_overrides(events):
    """Spent plus remaining is always the full pot, after any add/remove/edit sequence."""
    state = fold(events, slots=SLOTS)
    assert state.total_spent + state.total_remaining == 10 * 200
    assert state.override_delta == 0


@given(event_logs(), st.lists(st.tuples(st.integers(1, 10), st.integers(-50, 50)), max_size=6))
@settings(max_examples=200, deadline=None)
def test_ledger_reconciles_exactly_with_overrides(events, corrections):
    """With overrides the pot moves by exactly the sum of the corrections - no more, no less.

    The charter deliberately relaxes conservation here rather than renormalising silently.
    What must hold is that the discrepancy is exactly accountable.
    """
    extra = [BudgetAdjustment(slot=s, delta=d) for s, d in corrections]
    state = fold(_seq([*events, *extra]), slots=SLOTS)
    total = sum(d for _, d in corrections)
    assert state.override_delta == total
    assert state.total_spent + state.total_remaining == 10 * 200 + total


@given(event_logs())
@settings(max_examples=100, deadline=None)
def test_max_bid_never_strands_a_team(events):
    state = fold(events, slots=SLOTS)
    for team in state.teams.values():
        if team.open_slots > 0 and team.remaining >= team.open_slots:
            assert team.max_bid + (team.open_slots - 1) <= team.remaining


@given(event_logs(), st.integers(1, 10), st.integers(-40, 40))
@settings(max_examples=150, deadline=None)
def test_override_applied_then_reverted_is_a_no_op(events, slot, delta):
    """Reverting an override must return state bit-identical to before it was applied."""
    before = fold(events, slots=SLOTS)
    n = len(events)
    with_override = [*events, BudgetAdjustment(seq=n + 1, slot=slot, delta=delta)]
    after = fold([*with_override, Revert(seq=n + 2, target_seq=n + 1)], slots=SLOTS)
    assert after.model_dump() == before.model_dump()


@given(st.lists(st.tuples(st.integers(1, 10), st.integers(-40, 40)), min_size=1, max_size=6))
@settings(max_examples=150, deadline=None)
def test_budget_corrections_commute(corrections):
    """Order of independent corrections must not change the result."""
    forward = fold(_seq([BudgetAdjustment(slot=s, delta=d) for s, d in corrections]), slots=SLOTS)
    backward = fold(
        _seq([BudgetAdjustment(slot=s, delta=d) for s, d in reversed(corrections)]), slots=SLOTS
    )
    assert forward.model_dump() == backward.model_dump()


@given(
    st.integers(1, 10),
    st.integers(1, 200).map(str),
    st.integers(1, 60),
    st.integers(1, 60),
    st.booleans(),
)
@settings(max_examples=200, deadline=None)
def test_manual_keeper_counted_exactly_once(slot, player_id, manual_amt, pick_amt, manual_first):
    """For any interleaving, a keeper is counted once - never twice, never zero times."""
    pick = PickSnapshot(pick_no=1, player_id=player_id, slot=slot, amount=pick_amt, is_keeper=True)
    manual = ManualKeeper(slot=slot, player_id=player_id, amount=manual_amt)
    observed = PickObserved(pick=pick)
    order = [manual, observed] if manual_first else [observed, manual]
    state = fold(_seq(order), slots=SLOTS)
    team = state.teams[slot]
    assert team.filled_slots == 1
    assert team.spent == pick_amt  # the real pick always wins
    assert len(team.keepers) == 1


@given(st.lists(picks, max_size=20, unique_by=lambda p: p.pick_no))
@settings(max_examples=200, deadline=None)
def test_no_team_exceeds_two_keepers_without_an_alert(chosen):
    state = fold(_seq([PickObserved(pick=p) for p in chosen]), slots=SLOTS)
    for slot, team in state.teams.items():
        if len(team.keepers) > 2:
            assert any(f"slot {slot} holds" in a for a in state.alerts)


@given(st.lists(picks, max_size=20, unique_by=lambda p: p.pick_no))
@settings(max_examples=200, deadline=None)
def test_snapshot_diff_round_trips(chosen):
    """Applying the diff to the old snapshot must produce the new one, whatever changed."""
    current = {p.pick_no: p for p in chosen}
    events = diff_snapshots({}, current)
    rebuilt: dict[int, PickSnapshot] = {}
    for event in events:
        if isinstance(event, PickObserved | PickAmended):
            rebuilt[event.pick.pick_no] = event.pick
        elif isinstance(event, PickRemoved):
            rebuilt.pop(event.pick_no, None)
    assert rebuilt == current
    assert diff_snapshots(current, current) == []


@given(st.integers(1, 200))
def test_retention_price_floors_and_clamps(value):
    """floor(0.75 * v), never below the $1 minimum bid."""
    price = retention_price(value)
    assert price == max(1, (value * 3) // 4)
    assert price >= 1
    assert price <= value


def test_retention_price_boundaries():
    """The cases the charter calls out explicitly, including the one that yields zero."""
    assert retention_price(4) == 3
    assert retention_price(1) == 1  # floor(0.75) == 0, clamped
    assert retention_price(2) == 1
    assert retention_price(40) == 30  # exact integer
    assert retention_price(47) == 35  # floor(35.25)


@given(st.one_of(st.none(), st.text(max_size=6), st.integers(-5, 99)))
def test_amount_parsing_never_raises(raw):
    assert isinstance(parse_amount(raw), int)
