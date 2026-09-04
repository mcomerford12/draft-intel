"""The draft-night rehearsal: 160 picks through the cockpit, one at a time.

Sprint 4's gate, and the one test the project did not have. Everything else feeds the ledger a
finished array and checks the total. This feeds it the draft *as it happens* — poll by poll,
with the array growing under it — and checks the invariants after every single pick, because
that is the only shape in which a whole class of defect shows up:

* state that is correct at pick 160 and wrong at pick 40;
* a figure that drifts rather than breaks, so no single reading looks wrong;
* a poll that fits comfortably in its budget early and does not late;
* the block view quoting a price for somebody who was bought two picks ago.

It drives the real :class:`~draft_intel.api.live.LiveDraft` through its real
:meth:`~draft_intel.api.live.LiveDraft.poll_once`, over a feed that serves the first *i* picks of
``fixtures/picks.json``. Nothing is stubbed below the client. What runs here is what runs on
Saturday.

**At each step it nominates the player who is about to be bought.** That is the live situation:
the room names somebody, you type them, they are not yet on anyone's roster, and the tool has to
price them and rank the field. Nominating a player already in the ledger is checked too — at the
step *after* they are bought, where the answer must be "already rostered" and not a max bid.

Run with ``make rehearsal``. Exits non-zero if any invariant breaks, so it can gate a release.

``make rehearsal-live`` runs the same 160 picks against the **live league**: identity resolved
from Sleeper's own rosters and users, the real ``config/owners.yaml``, the real seat assignments.
The picks are re-attributed by *owner* rather than by slot, because the mock and the live league
seat people differently -- mock slot 1 is AJ, live slot 1 is Mason -- so replaying raw slot
numbers would test a draft nobody is going to play. Re-attributing keeps the same 160 picks made
by the same ten people, seated where they will actually sit. Owners who have not joined are
assigned the leftover slots in order, and that assumption is printed rather than buried.

That mode is the closest thing to Saturday this project can produce without Saturday, and it is
the one that exercises the production identity path end to end.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

from draft_intel.api.live import POLL_INTERVAL_SECONDS, LiveDraft, LiveSnapshot
from draft_intel.store.corrections import CorrectionStore
from draft_intel.store.overrides import OverrideStore

ROOT = Path(__file__).resolve().parents[1]

# The observed final ledger from the user's real mock draft. Sprint 1's golden file, restated
# here so the rehearsal ends by proving it reached the same place the replay harness does.
GOLDEN_SPEND = {1: 199, 2: 200, 3: 195, 4: 200, 5: 200, 6: 200, 7: 200, 8: 200, 9: 185, 10: 200}

# The seating those 160 picks were drafted under, expressed the way the live league expresses it:
# Sleeper display names, resolved through config/owners.yaml. The three managers with no alias
# carry their manifest name as their display name, which `build_identity` resolves directly.
# NOT the mock's own slot_name_* values -- the cockpit deliberately refuses to read those, and a
# rehearsal that fed them in would be exercising a path production never takes.
SEATING = {
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


class ReplayFeed:
    """Serves the first ``cursor`` picks, as Sleeper would while the draft runs.

    ``draft``/``rosters``/``users`` default to the synthetic seating above. In ``--live`` mode
    the real payloads fetched from Sleeper are passed in instead, so identity resolves through
    exactly the production path -- the ``slot_to_roster_id`` join, the real display names, the
    real ``config/owners.yaml``.
    """

    def __init__(
        self,
        picks: list[dict[str, Any]],
        *,
        draft: dict[str, Any] | None = None,
        rosters: list[dict[str, Any]] | None = None,
        users: list[dict[str, Any]] | None = None,
    ) -> None:
        self._picks = picks
        self.cursor = 0
        self._draft = draft
        self._rosters = rosters
        self._users = users

    async def draft(self, _draft_id: str) -> dict[str, Any]:
        if self._draft is not None:
            return {**self._draft, "status": "drafting"}
        return {
            "status": "drafting" if self.cursor < len(self._picks) else "complete",
            "slot_to_roster_id": {str(slot): slot for slot in SEATING},
            "metadata": {},
        }

    async def picks(self, _draft_id: str) -> list[dict[str, Any]]:
        return self._picks[: self.cursor]

    async def rosters(self, _league_id: str) -> list[dict[str, Any]]:
        if self._rosters is not None:
            return self._rosters
        return [{"roster_id": slot, "owner_id": f"u{slot}"} for slot in SEATING]

    async def users(self, _league_id: str) -> list[dict[str, Any]]:
        if self._users is not None:
            return self._users
        return [{"user_id": f"u{slot}", "display_name": n} for slot, n in SEATING.items()]


class Violation(NamedTuple):
    """One invariant that failed, and where."""

    pick: int
    rule: str
    detail: str


def check(snap: LiveSnapshot, *, pick_no: int, budget: int, rounds: int) -> list[Violation]:
    """Every invariant that must hold after *every* pick, not merely at the end.

    These are deliberately the cheap, absolute ones. A rehearsal is not the place to re-derive
    the valuation; it is the place to catch a ledger that has started lying.
    """
    out: list[Violation] = []
    teams = snap.teams

    def fail(rule: str, detail: str) -> None:
        out.append(Violation(pick_no, rule, detail))

    total = sum(t.spent for t in teams) + sum(t.remaining for t in teams)
    if total != len(teams) * budget:
        fail("money conservation", f"spent + remaining = ${total}, expected ${len(teams) * budget}")

    for team in teams:
        if team.remaining < 0:
            fail("no negative budget", f"{team.owner} has ${team.remaining}")
        if team.max_bid > team.remaining:
            fail("max bid within budget", f"{team.owner} max ${team.max_bid} > ${team.remaining}")
        if team.max_bid < 0:
            fail("max bid non-negative", f"{team.owner} max ${team.max_bid}")
        if team.filled_slots > rounds:
            fail("roster capacity", f"{team.owner} holds {team.filled_slots} of {rounds}")
        if team.keepers > 2:
            fail("keeper cap", f"{team.owner} holds {team.keepers} keepers")
        if team.figures_suspect:
            fail("figures trustworthy", f"{team.owner} has a negative amount in their ledger")

    filled = sum(t.filled_slots for t in teams)
    if filled != pick_no:
        fail("every pick lands", f"{filled} rostered against {pick_no} picks seen")

    if snap.picks_seen != pick_no:
        fail("feed read fully", f"saw {snap.picks_seen}, expected {pick_no}")

    if snap.stale:
        fail("fresh after a good poll", f"stale immediately after polling: {snap.connection}")

    if snap.alerts:
        fail("clean fixture", f"{len(snap.alerts)} alert(s): {snap.alerts[0][:80]}")

    if snap.blockers:
        fail("no blockers", snap.blockers[0][:90])

    block = snap.block
    if block is not None:
        mine = snap.my_team
        if mine is not None and block.my_max_bid > mine.remaining:
            fail("block max bid honest", f"${block.my_max_bid} > ${mine.remaining} remaining")
        if block.already_drafted_by is None and block.my_max_bid < 0:
            fail("block max bid non-negative", f"${block.my_max_bid}")

    return out


def _fresh(feed: ReplayFeed, *, corrections: CorrectionStore | None = None) -> LiveDraft:
    scratch = Path(tempfile.mkdtemp())
    return LiveDraft(
        ROOT,
        league_id="rehearsal",
        draft_id="rehearsal",
        store=OverrideStore(scratch / "no-overrides.yaml"),
        # Scratch paths, never `config/`. A rehearsal that writes a correction into the real
        # config changes what every later run and every test folds -- which has already happened
        # once, from a test, and is why `tests/conftest.py` now fingerprints the directory.
        corrections=corrections or CorrectionStore(scratch / "no-corrections.yaml"),
        client=feed,
    )


def chaos(picks: list[dict[str, Any]]) -> list[Violation]:
    """The six things that go wrong on a real draft night, run against the cockpit.

    A clean 160-pick replay proves the tool handles a draft where nothing goes wrong. Nothing
    going wrong is not the case worth rehearsing. These are the Sprint 1 plan's chaos list,
    re-run one layer up — through :meth:`LiveDraft.poll_once` rather than the replay harness,
    because the harness is not what will be running.

    The fifth, a **budget correction** mid-draft, was listed here as *not rehearsed* until
    DI-069: the ledger took override events from Sprint 1 but nothing in the cockpit emitted
    one, so there was no path to exercise. There is now, and leaving the old note in place would
    have understated the coverage exactly as long as removing it early would have overstated it.
    """
    print()
    print("-" * 78)
    print("CHAOS — what a real draft night does to a tool")
    print("-" * 78)
    out: list[Violation] = []
    midpoint = 100

    def report(name: str, ok: bool, detail: str) -> None:
        print(f"  {'ok ' if ok else '!! '}{name:<34} {detail}")
        if not ok:
            out.append(Violation(midpoint, name, detail))

    # 1. The process dies and comes back. The cockpit holds no incremental state -- every poll
    #    refolds the whole log -- so recovery should be exact rather than approximate. This is
    #    ADR-0001's whole claim, checked rather than asserted.
    feed = ReplayFeed(picks)
    feed.cursor = midpoint
    first = _fresh(feed)
    asyncio.run(first.poll_once())
    before = first.snapshot()

    restarted = _fresh(feed)
    asyncio.run(restarted.poll_once())
    after = restarted.snapshot()
    same = [t.model_dump() for t in before.teams] == [t.model_dump() for t in after.teams]
    report(
        "restart mid-draft",
        same and before.competitive_picks == after.competitive_picks,
        f"a new process at pick {midpoint} rebuilds the identical ledger",
    )

    # 2. The commissioner reverses a pick. The buyer's money and roster spot must come back
    #    exactly -- not approximately, and not on the next pick.
    victim = picks[midpoint - 1]
    slot = int(victim["draft_slot"])
    paid = int(victim["metadata"]["amount"])
    spent_before = next(t.spent for t in before.teams if t.slot == slot)
    filled_before = next(t.filled_slots for t in before.teams if t.slot == slot)

    # 2. The commissioner reverses a pick, on the SAME running instance -- the feed shrinks under
    #    a cockpit that has already folded the larger one. A fresh instance would prove only that
    #    99 picks fold to 99 picks; the transition is the thing that happens on the night.
    #    The buyer's money and roster spot must come back exactly, and on the next cycle.
    shrunk = ReplayFeed([p for p in picks if p["pick_no"] != victim["pick_no"]])
    shrunk.cursor = midpoint - 1
    first.client = shrunk
    asyncio.run(first.poll_once())
    team = next(t for t in first.snapshot().teams if t.slot == slot)
    report(
        "pick removed mid-draft",
        team.spent == spent_before - paid and team.filled_slots == filled_before - 1,
        f"slot {slot} went ${spent_before} -> ${team.spent}, "
        f"{filled_before} -> {team.filled_slots} picks (refunded ${paid})",
    )

    # 3. A pick's amount is corrected in place, again on the same running instance. The ledger
    #    must follow within one cycle, and the money must still conserve -- a correction that
    #    balances nowhere is worse than one that never applies.
    amended = [dict(p) for p in picks]
    amended[midpoint - 1] = {
        **amended[midpoint - 1],
        "metadata": {**amended[midpoint - 1]["metadata"], "amount": str(paid + 7)},
    }
    corrected = ReplayFeed(amended)
    corrected.cursor = midpoint
    first.client = corrected
    asyncio.run(first.poll_once())
    snap3 = first.snapshot()
    team = next(t for t in snap3.teams if t.slot == slot)
    conserved = sum(t.spent + t.remaining for t in snap3.teams) == 10 * first.config.budget
    report(
        "pick amended mid-draft",
        team.spent == spent_before + 7 and conserved,
        f"slot {slot} went ${spent_before} -> ${team.spent} in one cycle, money still conserves",
    )

    # 4. The connection drops. The last reading must stay on screen AND stop being presented as
    #    live -- both, because either one alone misleads.
    class Dropping(ReplayFeed):
        async def picks(self, draft_id: str) -> list[dict[str, Any]]:
            raise ConnectionError("connection reset by peer")

    feed.cursor = midpoint
    first.client = feed
    asyncio.run(first.poll_once())
    held = first.snapshot().total_remaining
    first.client = Dropping(picks)
    asyncio.run(first.poll_once())
    dropped = first.snapshot()
    report(
        "connection drops",
        dropped.total_remaining == held
        and dropped.stale
        and "ConnectionError" in dropped.connection,
        f"kept ${held} on screen, marked stale, named the failure",
    )

    # 5. The room's figures disagree with the feed's and the user corrects a team's budget
    #    mid-draft. Sleeper publishes no auction value for keepers (Finding 3), so somebody's
    #    ceremonial price being typed in wrong is not an exotic case -- it is Saturday.
    #
    #    Three things have to hold, and only the first is obvious. The corrected team's money
    #    moves by exactly the delta; **everyone else's is untouched**, because a correction that
    #    quietly rebalances the room is worse than one that never applies; and the revert puts
    #    it back to the dollar, because a correction you cannot undo at 9pm is one nobody will
    #    dare type. Money conservation is deliberately *not* asserted: the whole point of a
    #    budget correction is that the room no longer totals 10 x $200, and the ledger
    #    reconciling to `2000 + Σ deltas` instead is the Sprint 1 property.
    store = CorrectionStore(Path(tempfile.mkdtemp()) / "corrections.yaml")
    ledger = _fresh(feed, corrections=store)
    feed.cursor = midpoint
    asyncio.run(ledger.poll_once())
    baseline = {t.slot: t.remaining for t in ledger.snapshot().teams}
    # The richest team, so the case demonstrates a correction rather than an overdraw -- that is
    # the next case, and conflating the two would leave neither clearly proven.
    target = max(baseline, key=lambda slot: baseline[slot])

    entry = store.add(kind="budget", slot=target, delta=-5, observed=baseline[target] - 5)
    asyncio.run(ledger.poll_once())
    after_teams = {t.slot: t.remaining for t in ledger.snapshot().teams}

    store.revert(entry.id)
    asyncio.run(ledger.poll_once())
    restored = {t.slot: t.remaining for t in ledger.snapshot().teams}

    others_held = all(after_teams[s] == r for s, r in baseline.items() if s != target)
    report(
        "budget corrected mid-draft",
        after_teams[target] == baseline[target] - 5 and others_held and restored == baseline,
        f"slot {target} ${baseline[target]} -> ${after_teams[target]}, "
        f"nine other teams unmoved, revert restored it exactly",
    )

    # 6. The same surface, used wrong. A fat-fingered correction at 9pm can put a team below
    #    zero, and the two ways to handle that are both wrong: refusing the entry means the tool
    #    argues with the person who can see the room, and accepting it silently means a max bid
    #    computed off money that does not exist. It has to take the number and say so.
    store.add(kind="budget", slot=target, delta=-baseline[target] - 20, observed=-20)
    asyncio.run(ledger.poll_once())
    overdrawn = ledger.snapshot()
    team = next(t for t in overdrawn.teams if t.slot == target)
    report(
        "budget correction overdraws a team",
        team.remaining == -20
        and team.max_bid == 0
        and any("overdrawn" in a for a in overdrawn.alerts),
        f"slot {target} taken to $-20 as typed, max bid clamped to $0, and said so out loud",
    )
    return out


async def _live_context() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    import httpx

    from draft_intel.cli import LEAGUE_ID, REAL_DRAFT_ID
    from draft_intel.sleeper.client import SleeperClient

    async with httpx.AsyncClient() as http:
        client = SleeperClient(client=http)
        return (
            await client.draft(REAL_DRAFT_ID),
            await client.rosters(LEAGUE_ID) or [],
            await client.users(LEAGUE_ID) or [],
        )


def _reattribute(
    picks: list[dict[str, Any]], live: Any, teams: int
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    """Move each pick from the seat its owner had in the mock to the seat they hold live.

    Replaying raw ``draft_slot`` numbers against the live league would test a draft nobody is
    going to play: mock slot 1 is AJ and live slot 1 is Mason. What carries over is *who made
    the pick*, so the mock's identity answers that and the live one says where they now sit.

    Owners with no live seat -- managers who have not joined, or who joined under a display name
    ``owners.yaml`` does not know -- take the leftover slots in order. That is an assumption, and
    it is returned so the caller can print it rather than bury it.
    """
    import yaml

    from draft_intel.domain.identity import build_identity
    from draft_intel.domain.keepers import load_manifest

    aliases = yaml.safe_load((ROOT / "config" / "owners.yaml").read_text()) or {}
    mock = build_identity(
        json.loads((ROOT / "fixtures" / "draft.json").read_text()),
        aliases={**(aliases.get("aliases") or {}), **(aliases.get("mock_aliases") or {})},
    )

    # Keyed on **manifest owner names**, on both sides. Matching the mock's display names
    # against the live identity looked right and was not: the mock seats "Matt" while the
    # manifest calls that owner "Me", so the user themselves came out as "has not joined" and
    # was placed in a leftover seat -- which happened to be the correct one, by luck.
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    owners = sorted({owner for owner, _entry in manifest.entries})
    mock_slot = {owner: slot for owner in owners if (slot := mock.slot_for(owner)) is not None}
    placed = {owner: slot for owner in owners if (slot := live.slot_for(owner)) is not None}

    spare = [slot for slot in range(1, teams + 1) if slot not in set(placed.values())]
    assumed = [owner for owner in owners if owner not in placed]
    for owner, slot in zip(assumed, spare, strict=False):
        placed[owner] = slot

    by_mock_slot = {slot: owner for owner, slot in mock_slot.items()}
    # `metadata.slot` is rewritten alongside `draft_slot`. The poller cross-checks the two
    # (DI-053) and flags any disagreement as a PAYLOAD CONFLICT -- which it did, 224 times,
    # when this rewrote only one of them. The tool was right and the harness was producing a
    # payload Sleeper would never emit.
    moved: list[dict[str, Any]] = []
    for pick in picks:
        origin = int(pick["draft_slot"])
        if origin not in by_mock_slot:
            continue
        slot = placed[by_mock_slot[origin]]
        moved.append(
            {**pick, "draft_slot": slot, "metadata": {**pick["metadata"], "slot": str(slot)}}
        )
    return moved, placed, assumed


def _mock_slots() -> dict[str, int]:
    """Manifest owner -> the slot they held in the mock draft, for comparing by person."""
    import yaml

    from draft_intel.domain.identity import build_identity
    from draft_intel.domain.keepers import load_manifest

    aliases = yaml.safe_load((ROOT / "config" / "owners.yaml").read_text()) or {}
    mock = build_identity(
        json.loads((ROOT / "fixtures" / "draft.json").read_text()),
        aliases={**(aliases.get("aliases") or {}), **(aliases.get("mock_aliases") or {})},
    )
    owners = {owner for owner, _entry in load_manifest(ROOT / "config" / "keepers.yaml").entries}
    return {owner: slot for owner in owners if (slot := mock.slot_for(owner)) is not None}


def _owner_at(placed: dict[str, int], slot: int) -> str | None:
    return next((owner for owner, seat in placed.items() if seat == slot), None)


def run(live_league: bool = False, _seats_override: str | None = None) -> int:
    picks: list[dict[str, Any]] = sorted(
        json.loads((ROOT / "fixtures" / "picks.json").read_text()),
        key=lambda p: p["pick_no"],
    )
    assumed: list[str] = []
    placed: dict[str, int] = {}
    if live_league:
        draft, rosters, users = asyncio.run(_live_context())
        import yaml

        from draft_intel.domain.identity import build_identity
        from draft_intel.store.seats import SeatStore, apply_seats

        aliases = yaml.safe_load((ROOT / "config" / "owners.yaml").read_text()) or {}
        seats_path = Path(_seats_override or (ROOT / "config" / "seats.yaml"))
        resolved = apply_seats(
            build_identity(
                draft, rosters=rosters, users=users, aliases=aliases.get("aliases") or {}
            ),
            SeatStore(seats_path).load(),
        )
        picks, placed, assumed = _reattribute(picks, resolved, teams=10)
        feed = ReplayFeed(picks, draft=draft, rosters=rosters, users=users)
    else:
        feed = ReplayFeed(picks)

    # A store on a path that does not exist: the rehearsal runs the *model's* numbers, not the
    # user's current overrides. Not because overrides are untrusted -- because a gate that reads
    # a file the user edits is a gate whose result changes for reasons unrelated to the code.
    scratch = Path(tempfile.mkdtemp())
    from draft_intel.store.seats import SeatStore as _SeatStore

    live = LiveDraft(
        ROOT,
        league_id="rehearsal",
        draft_id="rehearsal",
        store=OverrideStore(scratch / "no-overrides.yaml"),
        # Corrections likewise. This is not hypothetical: a stray -$36 correction left in
        # `config/corrections.yaml` by a test made the rehearsal report "first failure at pick 1
        # of 160" for a reason that had nothing to do with pick 1.
        corrections=CorrectionStore(scratch / "no-corrections.yaml"),
        # Seats are the exception, and deliberately so: the cockpit must read the *same* seats
        # the re-attribution did, or the rehearsal measures one seating while the ledger
        # classifies against another -- exactly the mock-vs-live confusion DI-064 was built to
        # prevent, reintroduced inside the harness meant to catch it.
        seats=_SeatStore(_seats_override or (ROOT / "config" / "seats.yaml")),
        client=feed,
    )

    print("=" * 78)
    if live_league:
        print("DRAFT-NIGHT REHEARSAL — 160 picks against the LIVE LEAGUE")
    else:
        print("DRAFT-NIGHT REHEARSAL — 160 picks, one poll at a time")
    print("=" * 78)
    if live_league:
        print("  identity resolved from Sleeper's own rosters/users, through config/owners.yaml")
        print("  picks re-attributed by OWNER, not by slot: the mock and the live league seat")
        print("  people differently, so raw slot numbers would test a draft nobody will play.")
        print()
        for owner, slot in sorted(placed.items(), key=lambda kv: kv[1]):
            mark = "  <-- ASSUMED, has not joined" if owner in assumed else ""
            print(f"    slot {slot:>2}  {owner}{mark}")
        print()
    started = time.monotonic()
    live.pipeline  # build the board once, outside the timings  # noqa: B018
    print(f"  board built                {time.monotonic() - started:.1f}s")
    print(f"  poll budget                {POLL_INTERVAL_SECONDS:.1f}s per cycle")
    print()

    violations: list[Violation] = []
    poll_ms: list[float] = []
    block_ms: list[float] = []
    arc: list[tuple[int, int, float, int]] = []
    already_checked = False

    for i in range(1, len(picks) + 1):
        feed.cursor = i

        t0 = time.perf_counter()
        asyncio.run(live.poll_once())
        poll_ms.append((time.perf_counter() - t0) * 1000)

        # Nominate whoever is about to go — the live situation. On the last pick there is nobody
        # left to nominate, so re-nominate the one just bought, which exercises the other branch.
        upcoming = picks[i] if i < len(picks) else picks[i - 1]
        live.nominate(upcoming["player_id"])

        t1 = time.perf_counter()
        snap = live.snapshot()
        block_ms.append((time.perf_counter() - t1) * 1000)

        violations += check(
            snap, pick_no=i, budget=live.config.budget, rounds=live.config.draft_rounds
        )

        # The other branch, checked once mid-draft: a player already in the ledger must report as
        # rostered rather than be handed a max bid.
        if i == 100 and not already_checked:
            already_checked = True
            live.nominate(picks[i - 1]["player_id"])
            bought = live.snapshot().block
            if bought is None or bought.already_drafted_by is None:
                violations.append(
                    Violation(i, "bought players are not biddable", f"{picks[i - 1]['player_id']}")
                )
            live.nominate(upcoming["player_id"])

        if i % 20 == 0 or i == len(picks):
            mine = snap.my_team
            arc.append((i, snap.total_remaining, snap.inflation, snap.competitive_picks))
            mine_left = f"${mine.remaining:>3}" if mine else "  ?"
            print(
                f"  pick {i:>3}   room ${snap.total_remaining:>4}   "
                f"you {mine_left}   infl {snap.inflation:>5.2f}x   "
                f"comp {snap.competitive_picks:>3}   poll {poll_ms[-1]:>6.0f}ms"
            )

    print()
    print("-" * 78)
    print("LATENCY — poll (fetch + parse + fold) and snapshot (ledger + block + ladder)")
    print("-" * 78)
    for label, series in (("poll", poll_ms), ("snapshot", block_ms)):
        ordered = sorted(series)
        p50 = statistics.median(ordered)
        p95 = ordered[int(len(ordered) * 0.95)]
        print(
            f"  {label:<10} p50 {p50:>8.1f}ms   p95 {p95:>8.1f}ms   "
            f"max {ordered[-1]:>8.1f}ms   (first {series[0]:.0f}ms, last {series[-1]:.0f}ms)"
        )
    budget_ms = POLL_INTERVAL_SECONDS * 1000
    over = [i + 1 for i, ms in enumerate(poll_ms) if ms > budget_ms]
    if over:
        print(
            f"\n  !! {len(over)} of {len(poll_ms)} polls exceeded the {budget_ms:.0f}ms cycle "
            f"budget, from pick {over[0]} onward."
        )
    else:
        print(f"\n  every poll fitted inside the {budget_ms:.0f}ms cycle budget.")

    print()
    print("-" * 78)
    print("FINAL LEDGER vs the golden file")
    print("-" * 78)
    final = live.snapshot()
    # In live mode the golden file is compared **by owner**, not by slot: the whole point of
    # re-attribution is that these people now sit somewhere else, so slot 1 spending $200
    # rather than $199 is the seating changing, not the ledger being wrong.
    if live_league:
        want_by_owner = {
            owner: GOLDEN_SPEND[mock_slot]
            for owner, mock_slot in ((o, s) for o, s in _mock_slots().items() if s in GOLDEN_SPEND)
        }
        got_by_owner = {owner: 0 for owner in want_by_owner}
        for team in final.teams:
            seated = _owner_at(placed, team.slot)
            if seated is not None:
                got_by_owner[seated] = team.spent
        for owner in sorted(want_by_owner):
            mark = "ok " if got_by_owner.get(owner) == want_by_owner[owner] else "!! "
            print(
                f"  {mark}{owner:<10} spent ${got_by_owner.get(owner, 0):>3}  "
                f"(mock: ${want_by_owner[owner]})"
            )
        if got_by_owner != want_by_owner:
            violations.append(
                Violation(len(picks), "final ledger", "does not match the golden file by owner")
            )
    else:
        spend = {t.slot: t.spent for t in final.teams}
        for slot, team in sorted((t.slot, t) for t in final.teams):
            want = GOLDEN_SPEND[slot]
            mark = "ok " if team.spent == want else "!! "
            print(
                f"  {mark}slot {slot:>2}  {team.owner:<16} "
                f"spent ${team.spent:>3}  left ${team.remaining:>3}  "
                f"picks {team.filled_slots:>2}  keepers {team.keepers}"
            )
        if spend != GOLDEN_SPEND:
            violations.append(
                Violation(len(picks), "final ledger", "does not match the golden file")
            )
    if final.competitive_picks != 140:
        violations.append(
            Violation(len(picks), "keeper classification", f"{final.competitive_picks} competitive")
        )

    violations += chaos(picks)

    print()
    print("=" * 78)
    if violations:
        print(f"FAILED — {len(violations)} invariant violation(s)")
        print("=" * 78)
        seen: set[tuple[str, str]] = set()
        for v in violations:
            key = (v.rule, v.detail)
            if key in seen:
                continue
            seen.add(key)
            print(f"  pick {v.pick:>3}  {v.rule}: {v.detail}")
        first = min(v.pick for v in violations)
        print(f"\n  first failure at pick {first} of {len(picks)}.")
        return 1

    print(f"PASSED — {len(picks)} picks, every invariant held at every one of them")
    print("=" * 78)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    seats = next((a.split("=", 1)[1] for a in args if a.startswith("--seats=")), None)
    return run(live_league="--live" in args, _seats_override=seats)


if __name__ == "__main__":
    sys.exit(main())
