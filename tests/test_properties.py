"""Property tests for the invariants that keep money correct under any sequence of events.

These are the tests the charter says never to cut. Every one of them protects against a
class of silent corruption where the tool keeps running and keeps giving confident advice
while a team's budget has been wrong since 7:40pm.
"""

from __future__ import annotations

import math
from fractions import Fraction

from hypothesis import example, given, settings
from hypothesis import strategies as st

from draft_intel.domain.keepers import retention_price
from draft_intel.domain.ledger import fold
from draft_intel.models import (
    BudgetAdjustment,
    ManualKeeper,
    PickAmended,
    PickClass,
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


def expected_spend(events):
    """Independently replay the log to per-slot spend, without using any ledger code.

    This is the whole point of the rewrite: `remaining` is *defined* as `budget - spent`, so
    asserting `spent + remaining == 2000` is an algebraic identity that holds for any value
    of `spent`, including a badly wrong one. The old property could not fail. This one
    compares the ledger's arithmetic against a second, independent implementation.
    """
    live = {}
    for e in sorted(events, key=lambda e: e.seq):
        if isinstance(e, PickObserved | PickAmended):
            live[e.pick.pick_no] = (e.pick.slot, e.pick.amount)
        elif isinstance(e, PickRemoved):
            live.pop(e.pick_no, None)
    spend = dict.fromkeys(SLOTS, 0)
    for slot, amount in live.values():
        spend[slot] = spend.get(slot, 0) + amount
    return spend, len(live)


@given(event_logs())
@settings(max_examples=200, deadline=None)
def test_spend_matches_an_independent_replay(events):
    """The ledger's per-team spend must equal a separately computed replay of the same log."""
    state = fold(events, slots=SLOTS)
    spend, total_picks = expected_spend(events)
    assert {s: t.spent for s, t in state.teams.items()} == spend
    assert sum(t.filled_slots for t in state.teams.values()) == total_picks
    assert state.total_spent == sum(spend.values())
    assert state.override_delta == 0


@given(event_logs())
@settings(max_examples=200, deadline=None)
def test_money_conservation_without_overrides(events):
    """Spent plus remaining is the full pot -- and spent is independently correct."""
    state = fold(events, slots=SLOTS)
    spend, _ = expected_spend(events)
    assert state.total_spent == sum(spend.values())  # guards the identity below
    assert state.total_spent + state.total_remaining == 10 * 200
    assert state.override_delta == 0


@given(event_logs(), st.lists(st.tuples(st.integers(1, 13), st.integers(-50, 50)), max_size=6))
@settings(max_examples=200, deadline=None)
def test_ledger_reconciles_exactly_with_overrides(events, corrections):
    """With overrides the pot moves by exactly the sum of the corrections - no more, no less.

    The charter deliberately relaxes conservation here rather than renormalising silently.
    What must hold is that the discrepancy is exactly accountable.

    **Slots are drawn past the end of the league on purpose.** ``Slot`` validates 1..32 while
    this league has 10, so a mistyped correction for slot 11 is a well-formed event naming a team
    that does not exist. It is alerted and deliberately *not* applied -- and drawing exactly
    1..10, as this test used to, meant a ledger that silently applied it would reconcile just as
    happily. The accounting below now has to distinguish the two.
    """
    extra = [BudgetAdjustment(slot=s, delta=d) for s, d in corrections]
    log = _seq([*events, *extra])
    state = fold(log, slots=SLOTS)
    spend, _ = expected_spend(log)
    applied = sum(d for s, d in corrections if s in SLOTS)
    stranded = [(s, d) for s, d in corrections if s not in SLOTS]

    assert state.total_spent == sum(spend.values())  # spend is right, not just self-consistent
    assert state.override_delta == applied, (
        "a correction for a team that does not exist is not money"
    )
    assert state.total_spent + state.total_remaining == 10 * 200 + applied

    # **Per team, not only in total.** Every assertion above is an aggregate, so crediting each
    # correction to the wrong team satisfied all of them: the sums are identical whichever team
    # holds the money. That is the same wrong-team-but-reconciling shape the payload cross-check
    # exists to catch, sitting in the test written to guard corrections.
    per_team = dict.fromkeys(SLOTS, 0)
    for slot, delta in corrections:
        if slot in SLOTS:
            per_team[slot] += delta
    for slot, team in state.teams.items():
        assert team.budget == 200 + per_team[slot], f"slot {slot} holds another team's correction"
    for slot, _delta in stranded:
        assert any(f"slot {slot} is not one of" in alert for alert in state.alerts), (
            "a mistyped slot must be reported, not absorbed"
        )


@given(event_logs())
@settings(max_examples=100, deadline=None)
def test_max_bid_never_strands_a_team(events):
    """One-sided until DI-056: it bounded `max_bid` from above and never from below, so
    `return 0` satisfied it for every team in every generated log. A max bid of zero says "this
    team is out", and saying that about a team with money still in hand takes them off the
    affordability ladder — the display whose entire job is telling the user who they are actually
    bidding against."""
    state = fold(events, slots=SLOTS)
    for team in state.teams.values():
        if team.open_slots > 0 and team.remaining >= team.open_slots:
            assert team.max_bid + (team.open_slots - 1) <= team.remaining
            assert team.max_bid >= 1, "a team that can cover every open slot can bid on this one"


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
    st.integers(1, 10),
    st.integers(1, 200).map(str),
    st.integers(1, 60),
    st.integers(1, 60),
    st.booleans(),
    st.booleans(),
)
@settings(max_examples=300, deadline=None)
def test_manual_keeper_counted_exactly_once(
    manual_slot, pick_slot, player_id, manual_amt, pick_amt, manual_first, pick_is_keeper
):
    """For any interleaving, a keeper is counted once - never twice, never zero times.

    **The two slots are drawn independently.** An earlier version passed one drawn ``slot`` to
    both the manual entry and the pick, so the case this property most needs to cover was never
    generated: the operator types the keeper against the wrong team. Supersession keys on the
    player, and had it keyed on ``(slot, player_id)`` the two entries would not have matched --
    the player would be counted once on each team, the money booked twice, and this test would
    have gone on passing because it only ever drew them equal.

    **``is_keeper`` is drawn too.** It was hardcoded ``True`` -- the one value api-findings
    Finding 5 says never appears on a real ceremonial keeper, since all twenty in the fixture
    carry ``false``. So the branch that actually fires on this league's data was the branch the
    property never generated, and supersession firing *only* for ``is_keeper`` picks survived
    the whole file.
    """
    pick = PickSnapshot(
        pick_no=1, player_id=player_id, slot=pick_slot, amount=pick_amt, is_keeper=pick_is_keeper
    )
    manual = ManualKeeper(slot=manual_slot, player_id=player_id, amount=manual_amt)
    observed = PickObserved(pick=pick)
    order = [manual, observed] if manual_first else [observed, manual]
    state = fold(_seq(order), slots=SLOTS)

    # Counted once across the WHOLE league, not merely once on the team we happened to look at.
    # "Once" is about the roster spot and the money, which hold however the pick is classified;
    # whether the entry is a *keeper* follows the feed, and is asserted below.
    assert sum(t.filled_slots for t in state.teams.values()) == 1
    assert state.total_spent == pick_amt  # the real pick always wins, at its own price

    landed = state.teams[pick_slot]
    assert landed.filled_slots == 1 and landed.spent == pick_amt
    if manual_slot != pick_slot:
        assert state.teams[manual_slot].filled_slots == 0, "the wrong team keeps nothing"
        assert any("SLOT MISMATCH" in alert for alert in state.alerts)

    # The feed is authoritative for the pick, so a competitive pick supersedes a manual keeper
    # and the entry stops counting as one. That moves money out of `keeper_spend()` and drops
    # the N/20 readout, so it is a divergence the operator has to see -- exactly like the slot
    # and amount mismatches beside it, which have alerted since Sprint 1 while this one did not.
    if pick_is_keeper:
        assert len(landed.keepers) == 1
        assert state.keeper_spend() == pick_amt
    else:
        assert len(landed.keepers) == 0
        assert any("KEEPER MISMATCH" in alert for alert in state.alerts)


@given(st.integers(1, 10), st.integers(1, 200).map(str), st.integers(1, 60))
@settings(max_examples=200, deadline=None)
def test_a_manual_keeper_the_feed_has_not_delivered_is_classified_as_a_keeper(
    slot, player_id, amount
):
    """The residual blindness in the test above: it always builds a pick carrying the drawn
    ``player_id``, so supersession always fires and the manual entry never survives into the
    asserted state. It counts the pick that replaced a manual keeper, never a manual keeper.

    That branch matters more than most. ``ledger.py`` calls ``ManualKeeper`` "the *primary*
    route by which real keeper prices enter the system" -- Sleeper publishes no auction value,
    so retention prices are typed in from the draft room, and until the ceremonial pick lands
    the manual entry is the only record of one. Its ``pick_class`` drives ``keeper_spend()``,
    the N/20 readout, the ``expect_keepers`` alert, ``reconcile()``, and whether it is filtered
    out of ``competitive_seq``.

    Classifying it COMPETITIVE instead survived all 527 tests: keeper spend would drop out of
    structural inflation, the entry would join the skew series as a competitive bid at a
    retention price, and the readout would report fewer keepers than the team had entered.
    """
    state = fold(_seq([ManualKeeper(slot=slot, player_id=player_id, amount=amount)]), slots=SLOTS)
    team = state.teams[slot]

    assert team.filled_slots == 1
    assert [entry.pick_class for entry in team.roster] == [PickClass.KEEPER]
    assert len(team.keepers) == 1
    assert state.keeper_spend() == amount
    assert not state.competitive_seq, "a retention price is not a competitive bid"


@example(
    chosen=[
        PickSnapshot(pick_no=i, player_id=str(i), slot=1, amount=1, is_keeper=True)
        for i in range(1, 4)
    ]
)
@given(st.lists(picks, max_size=20, unique_by=lambda p: p.pick_no))
@settings(max_examples=200, deadline=None)
def test_no_team_exceeds_two_keepers_without_an_alert(chosen):
    state = fold(_seq([PickObserved(pick=p) for p in chosen]), slots=SLOTS)
    for slot, team in state.teams.items():
        if len(team.keepers) > 2:
            # Match the keeper alert specifically. `f"slot {slot} holds"` is also the prefix
            # of the over-roster alert, so this assertion passed on a completely different
            # alert whenever a generated team exceeded 16 players -- which, drawing up to 20
            # picks onto few slots, is most of the time.
            wanted = f"slot {slot} holds {len(team.keepers)} keepers, limit is"
            assert any(wanted in a for a in state.alerts)


def apply_diff(previous, events):
    rebuilt = dict(previous)
    for event in events:
        if isinstance(event, PickObserved | PickAmended):
            rebuilt[event.pick.pick_no] = event.pick
        elif isinstance(event, PickRemoved):
            rebuilt.pop(event.pick_no, None)
    return rebuilt


@given(
    st.lists(picks, max_size=12, unique_by=lambda p: p.pick_no),
    st.lists(picks, max_size=12, unique_by=lambda p: p.pick_no),
)
@settings(max_examples=300, deadline=None)
def test_snapshot_diff_round_trips_between_arbitrary_states(before, after):
    """The diff must carry ANY snapshot to ANY other.

    The previous version only ever diffed from an empty snapshot, so it emitted nothing but
    observations -- the amendment and removal branches, which are the entire reason this
    module exists, were never executed at all.
    """
    previous = {p.pick_no: p for p in before}
    current = {p.pick_no: p for p in after}
    assert apply_diff(previous, diff_snapshots(previous, current)) == current
    assert diff_snapshots(current, current) == []


def test_diff_emits_amendments_and_removals():
    """Named, deterministic coverage of the two branches that matter."""
    a = PickSnapshot(pick_no=1, player_id="A", slot=1, amount=10, is_keeper=False)
    b = PickSnapshot(pick_no=2, player_id="B", slot=2, amount=20, is_keeper=False)
    a_repriced = a.model_copy(update={"amount": 15})

    assert diff_snapshots({1: a}, {1: a_repriced}) == [PickAmended(pick=a_repriced)]
    assert diff_snapshots({1: a, 2: b}, {1: a}) == [PickRemoved(pick_no=2)]

    # A pick_no that comes to name a different player is a renumbering, not an amendment:
    # emitting PickAmended would silently re-point the pick's identity, so any earlier
    # reclassification of pick_no 1 would land on the wrong player.
    renumbered = diff_snapshots({1: a}, {1: b.model_copy(update={"pick_no": 1})})
    assert [e.kind for e in renumbered] == ["pick_removed", "pick_observed"]


@given(st.integers(1, 200))
def test_retention_price_floors_and_clamps(value):
    """floor(0.75 * v), never below the $1 minimum bid.

    Computed with `Fraction` so this is an independent derivation rather than a
    character-for-character restatement of the implementation line, which is what it was
    before and which could not catch a wrong formula.
    """
    price = retention_price(value)
    expected = max(1, math.floor(Fraction(3, 4) * value))
    assert price == expected
    assert 1 <= price <= value


def test_retention_price_boundaries():
    """The cases the charter calls out explicitly, including the one that yields zero."""
    assert retention_price(4) == 3
    assert retention_price(1) == 1  # floor(0.75) == 0, clamped
    assert retention_price(2) == 1
    assert retention_price(40) == 30  # exact integer
    assert retention_price(47) == 35  # floor(35.25)


@given(st.one_of(st.none(), st.text(max_size=6), st.integers(-5, 99), st.booleans()))
def test_amount_parsing_never_raises(raw):
    value, complaint = parse_amount(raw)
    assert type(value) is int  # not `isinstance`: bool is an int subclass and must not pass
    assert complaint is None or isinstance(complaint, str)


def test_amount_parsing_surfaces_what_it_could_not_read():
    """Formats that previously booked a real bid as $0 in silence."""
    assert parse_amount("35") == (35, None)
    assert parse_amount("35.0") == (35, None)
    assert parse_amount("$35") == (35, None)
    assert parse_amount("1,200") == (1200, None)
    for bad in (None, "", "abc", True):
        value, complaint = parse_amount(bad)
        assert value == 0 and complaint
