"""The draft-night cockpit: the live ledger, and what to do about the player on the block.

Everything under this module was built and tested across Sprints 1 and 2 and had no surface.
The poller parses picks, the ledger folds them, the valuation prices the board, the
affordability engine ranks who can outbid you — and until now the only way to see any of it was
a printed report from before the draft started. This is the thing that runs *during* the
auction.

**The nominated player is entered by hand, and that is a design decision, not a gap.** Sleeper
publishes completed picks over REST and nothing else; the current nomination and the live bid
clock exist only on its internal websocket, which charter §2 forbids reverse-engineering in
terms that leave no room to negotiate. So the room tells you who is up, you type the name, and
the tool answers the question you actually have: *what is this worth to me, and who can outbid
me?* Every figure behind that answer is derived from the picks feed, which is public.

**Staleness is treated as a first-class failure.** A cockpit whose numbers quietly freeze is
worse than no cockpit: you keep bidding against a board that stopped updating four minutes ago.
So every snapshot carries the age of the poll it came from, :attr:`LiveSnapshot.stale` turns
true well before the figures could mislead anybody, and the page says so at the top rather than
in a corner.

The pipeline — projections, baselines, the priced board — is expensive and is built once, then
rebuilt only when ``config/value_overrides.yaml`` changes on disk. That is what lets you retune
a price at 7:40pm from ``/prices`` and have the cockpit pick it up without a restart.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml
from pydantic import BaseModel, ConfigDict

from draft_intel.config import LeagueConfig
from draft_intel.domain.classify import KeeperClassifier
from draft_intel.domain.identity import Identity, build_identity, manifest_keys
from draft_intel.domain.ledger import fold
from draft_intel.models import DerivedState, PickObserved
from draft_intel.prep import Pipeline, build_pipeline
from draft_intel.quant.affordability import affordability
from draft_intel.quant.inflation import (
    Inflation,
    market_inflation,
    realized_positional_inflation,
)
from draft_intel.quant.optimizer import Candidate
from draft_intel.quant.valuation import PlayerValue
from draft_intel.quant.walkaway import WalkAway, WalkAwayBoard, walkaway_board
from draft_intel.sleeper.poller import parse_picks
from draft_intel.store.overrides import OverrideStore
from draft_intel.store.seats import SeatStore, apply_seats

STALE_AFTER_SECONDS = 8.0
"""How old a poll may get before the page stops presenting it as live.

Deliberately a few multiples of the poll interval rather than one: a single slow response is
normal and flagging it would train the user to ignore the warning, which is the one outcome
that makes the warning worse than useless.
"""

POLL_INTERVAL_SECONDS = 1.5
"""Charter §3 sets a 1s floor on Sleeper requests. This sits above it with room to spare."""


@runtime_checkable
class DraftFeed(Protocol):
    """The four calls the cockpit makes. :class:`SleeperClient` satisfies it.

    A protocol rather than the concrete client because this is genuinely all that is needed,
    and saying so lets the tests drive a completed draft through the real polling path instead
    of stubbing around it. The rate floor, retry, backoff and circuit breaker live in
    ``SleeperClient`` and are not reimplemented here.
    """

    async def draft(self, draft_id: str) -> Any: ...

    async def picks(self, draft_id: str) -> Any: ...

    async def rosters(self, league_id: str) -> Any: ...

    async def users(self, league_id: str) -> Any: ...


WALKAWAY_TOP = 12
"""How many players get a precomputed curve.

Each curve is dozens of optimizer solves, so this is the knob that decides whether the
precompute finishes between two picks. It matches `make prep`'s target list, so the printed
board and the cockpit rank the same players -- and it is a statement about what fits in the
time, never a claim that only twelve players matter.
"""

IDENTITY_REFRESH_SECONDS = 60.0
"""How often to re-resolve slot -> owner while the cockpit runs.

Not once at startup: managers are still joining, and each one who joins fills in a seat and
places two more keepers. Not every poll either -- it is three extra requests against a rate
floor, to answer a question that changes a few times a week.
"""


class TeamLine(BaseModel):
    """One team's money, as the cockpit shows it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slot: int
    owner: str
    is_me: bool
    spent: int
    remaining: int
    filled_slots: int
    open_slots: int
    max_bid: int
    keepers: int
    figures_suspect: bool
    """A negative amount reached this team's ledger, so every figure on this row is downstream
    of a number that cannot happen. Shown, never silently corrected."""


class BlockView(BaseModel):
    """The player on the block, and what the tool has to say about them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    player_id: str
    name: str
    position: str
    tier_note: str = ""

    my_value: float
    """What this player is worth to me — the model's price with my overrides applied."""

    inflation_adjusted: float
    """What they should cost *right now*, given the money still chasing the board."""

    my_max_bid: int
    blacklisted: bool
    already_drafted_by: str | None
    """Set when the ledger already shows this player bought. Bidding is over; say so."""

    ladder: tuple[str, ...]
    """Who is still in, and above what price they drop out."""

    clears_the_field: int
    contenders: int

    walk_away: int | None = None
    """The highest price at which buying this player still improves the team.

    ``None`` means the board holds no curve for them — **not** that they are worthless. The two
    are opposite conclusions and :attr:`walk_away_note` says which one applies.
    """

    walk_away_note: str = ""
    """Why there is no number, or what qualifies the one there is. Never left to inference."""

    curve: tuple[tuple[int, float], ...] = ()
    """``(price, Δ starting points)`` — §4.7b's axes. Empty when no curve is precomputed."""

    curve_trustworthy: bool = True
    """False when the curve is not monotone, which means its deltas cannot be read as a
    walk-away price at all. Shown rather than smoothed."""


class WalkAwayStatus(BaseModel):
    """What the precomputed curve board is, and whether it still describes your position.

    ADR-0006 clause 4 requires the live lookup to be O(1) against a board precomputed between
    settled picks, **and its cost at more open slots to be stated on the page rather than
    hidden.** This is that statement. It is a field rather than a log line because the honest
    answer at pick 12 is often "still computing, the last one took four minutes" — and a user
    who cannot see that will read an empty curve as "no opinion" instead of "not ready".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str
    """``absent``, ``computing``, ``current`` or ``stale``."""

    detail: str
    curves: int = 0
    budget: int | None = None
    slots: int | None = None
    seconds: float | None = None
    """How long the last completed precompute took. The cost ADR-0006 asks to be stated."""

    picks_since: int = 0
    """Picks that have landed since the board was computed. Every one of them makes it staler:
    the players it priced against are being bought."""


class LiveSnapshot(BaseModel):
    """One complete reading of the draft. Everything the page renders comes from here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    polled_at: float | None
    age_seconds: float
    stale: bool
    """True once the reading is too old to bid against. See :data:`STALE_AFTER_SECONDS`."""

    connection: str
    """``live``, ``never connected``, or the text of the last failure. A cockpit that hides a
    broken connection behind a stale number is the failure mode this whole module guards."""

    draft_status: str
    picks_seen: int
    competitive_picks: int

    teams: tuple[TeamLine, ...]
    total_remaining: int
    total_open_slots: int

    inflation: float
    inflation_detail: str
    positions: tuple[str, ...]
    """Per-position realized inflation, already filtered to the readable ones."""

    block: BlockView | None
    walkaway: WalkAwayStatus
    alerts: tuple[str, ...]

    blockers: tuple[str, ...] = ()
    """Conditions that corrupt every figure on the page while they hold.

    Separate from ``alerts`` because they are not the same kind of thing. An alert is something
    that happened and is recorded; a blocker is something *wrong right now* that makes the
    numbers beside it untrustworthy. Rendering them in one list means the one that invalidates
    the board sits between two that do not.
    """

    @property
    def my_team(self) -> TeamLine | None:
        return next((team for team in self.teams if team.is_me), None)


class LiveDraft:
    """Polls the real draft, folds the ledger, and answers questions about the block.

    One instance per process. :meth:`poll_once` is safe to call directly, which is what the
    tests do; :meth:`run` is the loop the app starts in the background.
    """

    def __init__(
        self,
        root: Path,
        *,
        league_id: str,
        draft_id: str,
        store: OverrideStore | None = None,
        seats: SeatStore | None = None,
        client: DraftFeed | None = None,
        precompute: bool = False,
    ) -> None:
        """``precompute`` follows the same rule as the app's ``poll``: **off unless asked.**

        A walk-away board is minutes of optimizer work at many open slots -- 190s measured at
        the 16 the user has before a single pick lands. Wiring that into every ``poll_once``
        unconditionally turned a 3.6-second test file into a 10-minute one, which is the same
        class of mistake as a suite that quietly opens a socket to Sleeper: expensive work
        happening because something called a method, not because anybody wanted it.
        """
        self.root = root
        self.precompute = precompute
        self.league_id = league_id
        self.draft_id = draft_id
        self.store = store or OverrideStore(root / "config" / "value_overrides.yaml")
        self.seats = seats or SeatStore(root / "config" / "seats.yaml")
        self.client = client

        self._pipeline: Pipeline | None = None
        self._overrides_mtime: float | None = None
        self._state: DerivedState | None = None
        self._polled_at: float | None = None
        self._connection = "never connected"
        self._draft_status = "unknown"
        self._picks_raw: list[dict[str, Any]] = []
        self._nominated: str | None = None
        self._identity: Identity | None = None
        self._identity_at = float("-inf")
        self._seats_mtime: float | None = None
        """When identity was last resolved, on the monotonic clock.

        ``-inf`` rather than ``0.0`` because ``time.monotonic()``'s epoch is arbitrary -- on a
        container it starts near zero at boot, so ``0.0`` means "over a minute ago" only once
        the process has been alive a minute. That made ``now - 0.0 < REFRESH`` accidentally true
        early in a container's life. Here it only ever meant "never resolved", which the
        ``_identity is not None`` guard already covered, so nothing changes behaviourally -- but
        the same literal in a test *was* load-bearing and failed exactly that way (DI-067).
        """
        self._walkaway: WalkAwayBoard | None = None
        self._walkaway_task: asyncio.Task[None] | None = None
        self._walkaway_signature: tuple[int, int, frozenset[str]] | None = None
        self._walkaway_seconds: float | None = None
        self._walkaway_picks = 0
        self._walkaway_error = ""
        self._classifier: KeeperClassifier | None = None

    # ------------------------------------------------------------------ pipeline

    @property
    def pipeline(self) -> Pipeline:
        """The priced board, rebuilt only when the override file changes underneath it.

        Building it runs projections, four replacement baselines and the whole valuation, which
        is far too slow to do per request during an auction. Watching the file's mtime rather
        than caching outright is what lets the user retune a price on ``/prices`` at 7:40pm and
        have the cockpit agree with them on the next poll.
        """
        mtime = self.store.path.stat().st_mtime if self.store.path.exists() else None
        if self._pipeline is None or mtime != self._overrides_mtime:
            self._pipeline = build_pipeline(self.root, overrides=self.store)
            self._overrides_mtime = mtime
        return self._pipeline

    @property
    def config(self) -> LeagueConfig:
        return self.pipeline.config

    @property
    def identity(self) -> Identity | None:
        """Slot → owner **for the real draft**, or ``None`` until it has been resolved.

        **``Pipeline.identity`` must never be used here, and this returning ``None`` is the
        point.** That one is built from ``fixtures/draft.json`` — the *mock* draft — because
        ``make prep`` is a pre-draft report analysing the mock. The real draft seats people
        differently: the mock has slot 1 AJ, slot 2 Jake, slot 4 Mason; the live league has
        slot 1 Mason, slot 2 AJ, slot 4 Steve.

        Using the mock's seating in the cockpit is not a cosmetic error. The keeper classifier
        keys on ``(slot, player_id)``, so every keeper would be checked against the wrong seat,
        match nothing, and be classified as a competitive bid — twenty of them, the most
        expensive picks of the night, corrupting inflation, skew and every threat read. And the
        user's own seat would be wrong, so the threat ladder would exclude somebody else.

        The reason that failure is dangerous rather than obvious is that **the user is slot 3
        in both**. The one seat a person would check by eye is the one seat that agrees.

        So there is no fallback. Until the live join succeeds this is ``None``, the cockpit
        raises a blocker, and it declines to attribute money to names it has not confirmed.
        """
        return self._identity

    @property
    def my_slot(self) -> int | None:
        """Derived from the manifest's own ``user_team`` against the *live* seating.

        An earlier version of the report hardcoded slot 3 and contradicted itself by $7. This
        derives it — but from :attr:`identity`, never the pipeline's mock-derived one.
        """
        if self._identity is None:
            return None
        slot = self._identity.slot_for(self.pipeline.manifest.user_team)
        return int(slot) if slot is not None else None

    def owner_for(self, slot: int) -> str:
        """The manager in this seat, or the seat number when it is not yet resolved.

        Never a guess. An unmapped slot is a manager who has not joined, and labelling them
        with somebody else's name is worse than labelling them with a number.
        """
        if self._identity is None:
            return f"slot {slot}"
        return str(self._identity.owner_for(slot) or f"slot {slot}")

    # ------------------------------------------------------------------ polling

    async def poll_once(self, client: DraftFeed | None = None) -> None:
        """Fetch, parse and fold once. Never raises: a failed poll is a reported condition.

        The previous reading is deliberately left in place on failure rather than cleared. The
        numbers stay on screen, the connection line says what went wrong, and
        :attr:`LiveSnapshot.stale` starts counting — which tells the user both what the board
        last said *and* that it is no longer being confirmed. Blanking the screen mid-auction
        would throw away the more useful of those two facts.
        """
        active = client or self.client
        if active is None:  # pragma: no cover - guarded by the app that constructs us
            self._connection = "no Sleeper client configured"
            return
        try:
            draft = await active.draft(self.draft_id)
            picks = await active.picks(self.draft_id) or []
            await self._refresh_identity(active, draft)
        except Exception as error:  # every failure here is reportable, none is fatal
            self._connection = f"{type(error).__name__}: {error}"
            return

        self._draft_status = str((draft or {}).get("status", "unknown"))
        self._picks_raw = list(picks)
        self._state = self._fold(self._picks_raw)
        self._polled_at = time.monotonic()
        self._connection = "live"
        self._precompute_walkaway(self._state)

    async def _refresh_identity(self, client: DraftFeed, draft: Any) -> None:
        """Resolve slot → owner from the **live** league, periodically.

        The real draft object carries no ``slot_name_*`` keys at all (Sprint 0, Finding 9), so
        the ``slot_to_roster_id`` join through ``/rosters`` and ``/users`` is the only path that
        resolves anybody in production. It was implemented in Sprint 1 and called by nothing
        outside ``smoke``.

        Re-resolved on a timer rather than once, because managers are still joining and each
        arrival fills a seat and places two more keepers. A failure here leaves the previous
        identity standing; it does not fail the poll, and it never falls back to the mock.
        """
        now = time.monotonic()
        # A seat typed at 7:10pm must land on the next poll, not up to a minute later -- the
        # user is staring at a blocker that names the manager they just placed. Watching the
        # file's mtime is the same trick the priced board uses for `value_overrides.yaml`.
        seats_mtime = self.seats.path.stat().st_mtime if self.seats.path.exists() else None
        seats_changed = seats_mtime != self._seats_mtime
        self._seats_mtime = seats_mtime
        if (
            self._identity is not None
            and not seats_changed
            and now - self._identity_at < IDENTITY_REFRESH_SECONDS
        ):
            return
        rosters = await client.rosters(self.league_id) or []
        users = await client.users(self.league_id) or []
        aliases = yaml.safe_load((self.root / "config" / "owners.yaml").read_text()) or {}
        resolved = apply_seats(
            build_identity(
                draft, rosters=rosters, users=users, aliases=aliases.get("aliases") or {}
            ),
            self.seats.load(),
        )
        if resolved.slot_to_owner != (self._identity.slot_to_owner if self._identity else None):
            # Seating changed, so every `(slot, player_id)` keeper key built from the old one is
            # stale. Dropping the classifier forces it to be rebuilt against the new seating.
            self._classifier = None
        self._identity = resolved
        self._identity_at = now

    # ------------------------------------------------------------------ walk-away

    def _precompute_walkaway(self, state: DerivedState) -> None:
        """Start a curve precompute in the background if the board no longer describes us.

        **Never on the request path, and never awaited by a poll.** A curve is dozens of
        optimizer solves by construction (ADR-0003), and E2 measured one at 11.1s with 14 open
        slots. Computing one while the room is bidding is the design ADR-0006 rewrote the gate
        to forbid; this runs in a worker thread and the live path does a dictionary lookup.

        Rebuilt when *anything* that moves a curve moves: the user's budget, their open slots,
        or the set of players still available. A curve prices you against a pool, so every pick
        anybody makes ages it — which is why :class:`WalkAwayStatus` reports how many picks have
        landed since, rather than only whether the budget still matches.

        Self-throttling by construction: one precompute at a time, and a new one is only started
        once the last has finished. Early in the draft that means it recomputes rarely, because
        it is slow and there are many open slots; late it keeps up easily. That is the right
        shape — the answer matters most when slots are few, which is exactly when it is cheap.
        """
        if not self.precompute:
            return
        if self._walkaway_task is not None and not self._walkaway_task.done():
            return
        my_slot = self.my_slot
        if my_slot is None or my_slot not in state.teams:
            return
        mine = state.teams[my_slot]
        if mine.open_slots <= 0:
            return

        drafted = frozenset(
            entry.player_id for team in state.teams.values() for entry in team.roster
        )
        signature = (mine.remaining, mine.open_slots, drafted)
        if signature == self._walkaway_signature:
            return
        self._walkaway_signature = signature
        self._walkaway_task = asyncio.create_task(
            self._run_precompute(
                budget=mine.remaining,
                slots=mine.open_slots,
                drafted=drafted,
                picks=len(self._picks_raw),
            )
        )

    async def _run_precompute(
        self, *, budget: int, slots: int, drafted: frozenset[str], picks: int
    ) -> None:
        built = self.pipeline
        candidates = [
            Candidate(
                player_id=p.player_id,
                name=p.name,
                position=p.position,
                points=p.points,
                vorp=p.vorp_live,
                price=max(1, round(p.baseline_value)),
                # Bought players are excluded, which `ValueBoard.available()` does not do -- it
                # only drops keepers. A curve computed against a pool still holding everybody
                # sold in the last hour prices you against players you cannot have.
            )
            for p in built.board.players
            if p.in_pool_live and not p.is_keeper and p.player_id not in drafted
        ]
        started = time.monotonic()
        try:
            board = await asyncio.to_thread(
                walkaway_board,
                candidates,
                budget=budget,
                slots=slots,
                starters=built.config.starters,
                top=WALKAWAY_TOP,
            )
        except Exception as error:  # a failed precompute must not take the cockpit down
            self._walkaway_error = f"{type(error).__name__}: {error}"
            self._walkaway_signature = None  # let the next poll try again
            return
        self._walkaway = board
        self._walkaway_seconds = time.monotonic() - started
        self._walkaway_picks = picks
        self._walkaway_error = ""

    def _walkaway_status(self, state: DerivedState | None) -> WalkAwayStatus:
        running = self._walkaway_task is not None and not self._walkaway_task.done()
        board = self._walkaway
        cost = (
            f" The last one took {self._walkaway_seconds:.0f}s."
            if self._walkaway_seconds is not None
            else ""
        )
        if self._walkaway_error:
            return WalkAwayStatus(
                state="absent", detail=f"the last precompute failed — {self._walkaway_error}"
            )
        if board is None:
            return WalkAwayStatus(
                state="computing" if running else "absent",
                detail=(
                    f"precomputing walk-away curves for the top {WALKAWAY_TOP} players.{cost}"
                    if running
                    else "no curves precomputed yet."
                ),
            )

        mine = (
            state.teams.get(self.my_slot)
            if state is not None and self.my_slot is not None
            else None
        )
        current = mine is not None and board.is_current_for(
            budget=mine.remaining, slots=mine.open_slots
        )
        since = max(0, len(self._picks_raw) - self._walkaway_picks)
        if current and since == 0:
            detail = f"current for ${board.budget} across {board.slots} open slots.{cost}"
        elif running:
            detail = (
                f"recomputing — these curves are for ${board.budget} / {board.slots} slots, "
                f"{since} pick(s) ago.{cost}"
            )
        else:
            detail = (
                f"STALE — computed for ${board.budget} / {board.slots} slots, {since} pick(s) "
                f"ago. Every price below answers a question about a roster you no longer "
                f"have.{cost}"
            )
        return WalkAwayStatus(
            state="current" if current and since == 0 else ("computing" if running else "stale"),
            detail=detail,
            curves=len(board.curves),
            budget=board.budget,
            slots=board.slots,
            seconds=self._walkaway_seconds,
            picks_since=since,
        )

    async def run(self, *, interval: float = POLL_INTERVAL_SECONDS) -> None:
        """Poll forever. Cancelled by the app on shutdown."""
        while True:
            await self.poll_once()
            await asyncio.sleep(interval)

    def _fold(self, picks: Sequence[Mapping[str, Any]]) -> DerivedState:
        """Parse the whole feed and fold it. One payload in, one ledger out.

        **This used to call ``replay_all``, on a justification that was wrong twice over.** The
        comment claimed it "drives the snapshot diff, so a commissioner reversing or amending a
        pick produces the PickRemoved and PickAmended the ledger knows how to fold". It does
        not: ``replay_events`` diffs *within a single payload*, where the array only ever grows
        and no pick changes, so it emits nothing but ``PickObserved`` — verified, 160 of 160.

        Corrections are handled, but by the mechanism ADR-0001 actually specifies: **there is no
        incremental state to correct.** Every poll refolds the entire log from the feed as it
        stands, so a reversed pick is simply a feed with one fewer row and an amended one is a
        feed with a different amount. The right answer falls out of statelessness, not out of
        diff events.

        Meanwhile ``replay_all`` re-parsed ``payload[:i]`` for every ``i``, which is quadratic:
        **101ms against 1.3ms at 160 picks, for output proven identical** — same events, same
        ``DerivedState`` — across a full feed, a feed with a pick removed, one with an amount
        amended, an unsorted feed, and one carrying an unparseable row. On the live path that
        cost sat inside every poll cycle.

        Sorted by ``pick_no`` before sequencing, matching what ``replay_events`` did, so
        ``competitive_seq`` is assigned in pick order however the feed happens to arrive.
        """
        built = self.pipeline
        payload = sorted((dict(p) for p in picks), key=lambda p: p.get("pick_no", 0))
        parsed = parse_picks(payload)
        return fold(
            [
                PickObserved(seq=index + 1, pick=snapshot)
                for index, snapshot in enumerate(parsed.picks.values())
            ],
            slots=range(1, built.config.teams + 1),
            budget=built.config.budget,
            total_slots=built.config.draft_rounds,
            max_keepers=built.config.keepers_per_team,
            classifier=self._keeper_classifier(),
            rejects=parsed.rejects,
        )

    def _keeper_classifier(self) -> KeeperClassifier:
        """The manifest-backed classifier — the only one that fires on real Sleeper data.

        The ceremonial keeper picks carry ``is_keeper: false`` (Sprint 0, Finding 4), so
        trusting the flag classifies nothing and twenty keepers enter the competitive series,
        poisoning skew, inflation and every tendency profile for the whole draft.

        **``require`` is deliberately not passed, and the incompleteness is reported instead.**
        ``manifest_keys(require=20)`` raises when an owner has no draft slot, which is the right
        behaviour for a pre-draft report and the wrong one for a cockpit: three managers have
        still not joined, and a tool that refuses to start at 7pm is worth nothing. This is
        ADR-0002's D4 decision applied one layer further in — warn loudly, do not brick — and
        the warning is not a footnote: :meth:`unresolved_keepers` puts it at the top of the page
        naming the owners, because every keeper it cannot place becomes a competitive bid and
        corrupts skew, inflation and every tendency profile for the night.

        Not armed, for the reason DI-055 recorded: ``arming_window`` is a hardcoded 20 rather
        than a fact read from the feed, and ``FLAGGED`` is terminal until the ``Reclassify``
        producer exists.
        """
        if self._classifier is None:
            self._classifier = KeeperClassifier(
                manifest_keys=self._manifest_keys_now(), armed=False
            )
        return self._classifier

    def unresolved_keepers(self) -> tuple[int, int, tuple[str, ...]]:
        """``(resolved, expected, owners_with_no_slot)``. The cockpit's loudest banner."""
        built = self.pipeline
        expected = built.config.teams * built.config.keepers_per_team
        unmapped = sorted(
            {
                owner
                for (owner, _player_id) in built.resolved
                if self._identity is None or self._identity.slot_for(owner) is None
            }
        )
        return len(self._manifest_keys_now()), expected, tuple(unmapped)

    def keepers_if_seated(self) -> int:
        """How many keepers would place **with the seats currently on disk applied**.

        Distinct from :meth:`unresolved_keepers`, deliberately. That one reports the identity
        the ledger is actually classifying against right now; this one reports what the user
        has just asserted, which does not reach the classifier until the next poll.

        Both are needed and neither substitutes for the other. Reporting only the live figure
        makes a correct assignment look like it failed — the user clicks "assign" and the count
        does not move. Reporting only the projected one clears the blocker a poll before the
        classifier agrees with it, which is the optimistic direction and the one that lies.
        """
        if self._identity is None:
            return 0
        seated = apply_seats(self._identity, self.seats.load())
        return len(manifest_keys(dict(self.pipeline.resolved), seated))

    def _manifest_keys_now(self) -> frozenset[tuple[int, str]]:
        """``(slot, player_id)`` keeper keys against the **live** seating.

        Empty until the live identity resolves, which is correct and is why
        :meth:`_blockers` refuses to let the page look healthy in that state: matching keepers
        against the mock's seating would place twenty of them on the wrong teams.
        """
        if self._identity is None:
            return frozenset()
        return manifest_keys(dict(self.pipeline.resolved), self._identity)

    # ------------------------------------------------------------------ the block

    def nominate(self, player_id: str | None) -> None:
        self._nominated = player_id

    def find(self, query: str) -> list[PlayerValue]:
        """Name search over the priced board, for typing a nomination in a hurry.

        Substring, case-insensitive, ranked by live value so the obvious answer is first. Names
        are input to a lookup here and nothing more — no name decides a price, a tier or a
        classification anywhere in this project.
        """
        needle = query.strip().lower()
        if not needle:
            return []
        hits = [
            player
            for player in self.pipeline.board.players
            if player.in_pool_full and needle in player.name.lower()
        ]
        hits.sort(key=lambda p: (-p.baseline_value, p.name))
        return hits[:12]

    # ------------------------------------------------------------------ snapshot

    def snapshot(self) -> LiveSnapshot:
        """Everything the page needs, computed from the last successful poll."""
        built = self.pipeline
        age = 0.0 if self._polled_at is None else time.monotonic() - self._polled_at
        state = self._state
        my_slot = self.my_slot
        blockers = self._blockers(my_slot)

        if state is None:
            return LiveSnapshot(
                polled_at=None,
                age_seconds=0.0,
                stale=True,
                connection=self._connection,
                draft_status=self._draft_status,
                picks_seen=0,
                competitive_picks=0,
                teams=(),
                total_remaining=built.config.teams * built.config.budget,
                total_open_slots=built.config.teams * built.config.draft_rounds,
                inflation=1.0,
                inflation_detail="no reading yet",
                positions=(),
                block=None,
                walkaway=self._walkaway_status(None),
                alerts=("no successful poll yet — every figure below is the model's prior",),
                blockers=blockers,
            )

        teams = tuple(
            TeamLine(
                slot=slot,
                owner=self.owner_for(slot),
                is_me=slot == my_slot,
                spent=team.spent,
                remaining=team.remaining,
                filled_slots=team.filled_slots,
                open_slots=team.open_slots,
                max_bid=team.max_bid,
                keepers=len(team.keepers),
                figures_suspect=team.figures_suspect,
            )
            for slot, team in sorted(state.teams.items())
        )

        drafted = {entry.player_id for team in state.teams.values() for entry in team.roster}
        available = [
            player
            for player in built.board.players
            if player.in_pool_live and player.player_id not in drafted
        ]
        remaining_money = sum(team.remaining for team in state.teams.values())
        remaining_slots = sum(team.open_slots for team in state.teams.values())
        inflation = market_inflation(
            available, remaining_money=remaining_money, remaining_slots=remaining_slots
        )

        return LiveSnapshot(
            polled_at=self._polled_at,
            age_seconds=round(age, 1),
            stale=age > STALE_AFTER_SECONDS or self._connection != "live",
            connection=self._connection,
            draft_status=self._draft_status,
            picks_seen=len(self._picks_raw),
            competitive_picks=len(state.competitive_seq),
            teams=teams,
            total_remaining=remaining_money,
            total_open_slots=remaining_slots,
            inflation=inflation.inflation,
            inflation_detail=_inflation_detail(inflation),
            positions=_position_lines(state, built),
            block=self._block(state, inflation, my_slot, drafted),
            walkaway=self._walkaway_status(state),
            alerts=tuple(state.alerts) + tuple(state.rejects) + tuple(state.orphans),
            blockers=blockers,
        )

    def _blockers(self, my_slot: int | None) -> tuple[str, ...]:
        """What is wrong *right now* in a way that makes the figures beside it untrustworthy."""
        out: list[str] = []
        if self._identity is None:
            # Nothing below can be trusted: with no live seating every keeper is checked against
            # the wrong slot, so the classifier matches nothing and the money is attributed to
            # names that were never confirmed.
            return (
                "slot → owner has not been resolved from the live league yet, so no keeper can "
                "be placed and no team name below is confirmed. Every figure on this page is "
                "provisional until the next successful poll.",
            )
        resolved, expected, unmapped = self.unresolved_keepers()
        if resolved < expected:
            out.append(
                f"{expected - resolved} of {expected} keepers cannot be placed on a draft slot "
                f"({', '.join(unmapped)} have not joined). Each one will be read as a "
                f"competitive bid, which corrupts inflation, skew and every threat read below."
            )
        if my_slot is None:
            out.append(
                f"your own draft slot is unknown — {self.pipeline.manifest.user_team!r} is not "
                "mapped to a seat, so there is no max bid and no threat ladder"
            )
        return tuple(out)

    def _block(
        self,
        state: DerivedState,
        inflation: Inflation,
        my_slot: int | None,
        drafted: set[str],
    ) -> BlockView | None:
        if self._nominated is None or my_slot is None:
            return None
        built = self.pipeline
        player = next((p for p in built.board.players if p.player_id == self._nominated), None)
        if player is None:
            return None

        owner = None
        for slot, team in state.teams.items():
            if any(entry.player_id == player.player_id for entry in team.roster):
                owner = self.owner_for(slot)
                break

        ladder = affordability(
            state,
            position=player.position,
            my_slot=my_slot,
            starters=built.config.starters,
            positions={p.player_id: p.position for p in built.board.players},
            owners={slot: self.owner_for(slot) for slot in state.teams},
        )
        override = built.overrides.get(player.player_id)
        return BlockView(
            player_id=player.player_id,
            name=player.name,
            position=player.position,
            tier_note=override.note if override else "",
            my_value=round(player.baseline_value, 2),
            inflation_adjusted=inflation.adjusted(player),
            my_max_bid=ladder.my_max_bid,
            blacklisted=bool(override and override.blacklisted),
            already_drafted_by=owner,
            ladder=tuple(ladder.describe()),
            clears_the_field=ladder.price_that_clears_the_field(),
            contenders=len(ladder.contenders),
            **_walkaway_fields(self._walkaway, player.player_id),
        )


def _walkaway_fields(board: WalkAwayBoard | None, player_id: str) -> dict[str, Any]:
    """The block's walk-away fields, by **O(1) dictionary lookup** — never a solve.

    ADR-0006 clause 4 is a promise about this function: the answer during a nomination is a
    lookup against a board precomputed between picks. There is deliberately no fallback that
    computes a missing curve on demand, because that fallback is exactly the 11-second stall the
    amended gate exists to forbid, and it would fire precisely when the room is bidding.

    Every absence is explained rather than left as a blank. "No curve" and "worth nothing" are
    opposite conclusions that a missing number cannot distinguish between.
    """
    if board is None:
        return {"walk_away_note": "no curves precomputed yet — bid on value and the ladder."}
    curve: WalkAway | None = board.get(player_id)
    if curve is None:
        return {
            "walk_away_note": (
                f"outside the precomputed top {WALKAWAY_TOP} by VORP — no curve for them, "
                "which is not the same as not worth bidding on."
            )
        }
    if curve.walk_away_price is None:
        return {
            "walk_away_note": (
                "the curve never turns positive: at this budget and these open slots, buying "
                "them does not improve the team at any legal price."
            ),
            "curve": tuple((p.price, round(p.starting_points_delta, 1)) for p in curve.points),
            "curve_trustworthy": curve.monotone,
        }
    note = ""
    if curve.worth_it_at_any_legal_price:
        # The distinction the sampled curve cannot show: the constraint is your wallet, not
        # their value. Reading "walk away above $93" as "they are worth $93" is backwards here.
        note = (
            f"still worth it at your maximum legal bid of ${curve.max_legal_bid} — the binding "
            "constraint is your budget, not their value."
        )
    if not curve.monotone:
        note = (note + " " if note else "") + (
            "the curve rises somewhere, so its deltas cannot be trusted as a walk-away price."
        )
    return {
        "walk_away": curve.walk_away_price,
        "walk_away_note": note,
        "curve": tuple((p.price, round(p.starting_points_delta, 1)) for p in curve.points),
        "curve_trustworthy": curve.monotone,
    }


def _inflation_detail(inflation: Inflation) -> str:
    direction = "over" if inflation.inflation >= 1.0 else "under"
    return (
        f"${inflation.discretionary_remaining} discretionary chasing "
        f"${inflation.remaining_value:.0f} of value across {inflation.pool_size} players — "
        f"expect the room to clear about {abs(1 - inflation.inflation) * 100:.0f}% {direction} book"
    )


def _position_lines(state: DerivedState, built: Pipeline) -> tuple[str, ...]:
    """Per-position realized inflation, filtered to the positions with enough picks to read.

    An unreadable position is dropped rather than shown with a blank ratio: a number computed
    from two picks is not a market reading, and rendering one invites a bidding decision built
    on noise. ``PositionInflation.is_reportable`` is the module's own answer to that question,
    so the threshold is not restated here where it could drift.
    """
    board = {p.player_id: p for p in built.board.players}
    realized = realized_positional_inflation(state, board)
    return tuple(line.describe() for line in realized.values() if line.is_reportable)


__all__ = ["BlockView", "DraftFeed", "LiveDraft", "LiveSnapshot", "TeamLine"]
