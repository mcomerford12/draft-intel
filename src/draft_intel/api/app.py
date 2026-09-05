"""The price table: a route that shows every value, and lets the user change any of them.

Charter §4.8 has always required per-player value overrides. What it did not have was a surface
— the plumbing existed in :mod:`draft_intel.quant.overrides` and nothing called it. This is the
surface, and it is deliberately the smallest thing that does the job:

* ``GET  /prices``                  the table, editable in place
* ``GET  /api/prices``              the same rows as JSON
* ``POST /api/prices/{player_id}``  set or clear one player's override
* ``GET  /healthz``                 is it up

**Every player, and every value they carry.** DI-061 shipped one editable field for the 140
available players. That covered the common case and not the question actually asked, which was
to override *all* the projected auction values. So (DI-062) the table carries all 160 priced
players, keepers included, and four editable fields each:

* **live $** — what to bid in this auction. Blank for a keeper: they are off the board, and an
  editable bid price for somebody already rostered is an invitation to a mistake.
* **market $** — full-market value. This is the number the league's ``floor(0.75 x auction
  value)`` keeper rule reads, so overriding it for a keeper moves their rule price and surplus.
  It is also the per-player way to clear the ESTIMATE badge without assembling the whole
  ``auction_values.csv``.
* **pts** — projected points, applied upstream of replacement level so it re-derives VORP and
  dollars rather than sitting inertly beside them.
* **blacklist** — never bid, whatever the model says.

**The model's number is never overwritten.** Every changed figure shows the model's own beneath
it, because "the model said $17.74 and I said $40" is a different fact from "$40", and on draft
night the difference is the whole reason to trust or distrust the number. Clearing an override
falls back to the model rather than to zero.

Overrides persist to ``config/value_overrides.yaml`` — see :mod:`draft_intel.store.overrides` for
why a file rather than the event log. They survive a restart and can be edited by hand.

**This is not the cockpit.** It reads the same pipeline ``make prep`` does — and since DI-062 the
pipeline reads the same override file — so the two cannot disagree. It holds no draft state: no
picks, no budgets, no bidding. Sprint 3 owns that.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, computed_field

from draft_intel.api.live import BlockView, LiveDraft, LiveSnapshot, TeamLine
from draft_intel.cli import LEAGUE_ID, REAL_DRAFT_ID
from draft_intel.models import PickClass
from draft_intel.prep import build_pipeline
from draft_intel.sleeper.client import SleeperClient
from draft_intel.store.corrections import Correction
from draft_intel.store.overrides import OverrideStore, ValueOverride
from draft_intel.store.seats import SeatAssignment

ROOT = Path(__file__).resolve().parents[3]


class PriceRow(BaseModel):
    """One player as the table shows them: the model's figures, and the user's beside them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    player_id: str
    name: str
    position: str
    is_keeper: bool

    model_points: float
    model_vorp: float
    model_live_value: float
    model_market_value: float
    """The model's four figures, always retained. §4.8 requires them displayable beside the
    user's, so nothing downstream can obtain one without the other."""

    points: float
    vorp: float
    live_value: float
    market_value: float
    """What the tool will actually use: the override where there is one, else the model."""

    market_is_estimate: bool
    """False once a real auction value covers this player, from the CSV or typed here."""

    blacklisted: bool
    note: str = ""

    # `computed_field`, not a bare `@property`: a property is invisible to serialisation, so
    # `/api/prices` returned rows with no way to tell an overridden figure from a model one and
    # the page's own JSON contract silently omitted the two fields that carry the §4.8 fact.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def overridden(self) -> bool:
        """Whether any figure on this row is the user's rather than the model's."""
        return (
            self.blacklisted
            or self.points != self.model_points
            or self.live_value != self.model_live_value
            or self.market_value != self.model_market_value
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def delta(self) -> float:
        """How far the live price moved from the model's, in dollars. Zero when untouched."""
        return round(self.live_value - self.model_live_value, 2)


class OverrideRequest(BaseModel):
    """A value edit. Every field optional: send only what you are changing."""

    model_config = ConfigDict(extra="forbid")

    live_value: float | None = Field(default=None, ge=0)
    market_value: float | None = Field(default=None, ge=0)
    points: float | None = None
    blacklisted: bool | None = None
    note: str | None = None


def price_rows(root: Path, store: OverrideStore) -> list[PriceRow]:
    """Every priced player, model figures and overridden figures side by side.

    Built from :func:`draft_intel.prep.build_pipeline` — the same chain ``make prep`` runs, over
    the same override file — so the page and the printed report cannot quote different numbers
    for the same player.

    Sorted available-first by live value, then keepers by market value. Keepers sort separately
    because their live value is zero by construction (they are off the board), so ranking them
    in with everybody else would file all twenty at the bottom under a price that is not a price.
    """
    built = build_pipeline(root, overrides=store)
    stored = store.load()
    model = {p.player_id: p for p in built.model_board.players}

    def market(resolved: object, player_id: str, fallback: float) -> float:
        """The provider's dollar opinion — the figure the 75% keeper rule reads.

        Not ``PlayerValue.market_value``: that is the *model's* book value, a different quantity
        from a different base, and the report has already been bitten once by printing the two
        under one heading. The fallback covers a player no provider priced at all, which the
        internal layer makes unlikely rather than impossible.
        """
        value = resolved.get(player_id)  # type: ignore[attr-defined]
        return round(fallback if value is None else value, 2)

    rows = [
        PriceRow(
            player_id=player.player_id,
            name=player.name,
            position=player.position,
            is_keeper=player.is_keeper,
            model_points=round(model[player.player_id].points, 2),
            model_vorp=round(model[player.player_id].vorp_live, 2),
            model_live_value=round(model[player.player_id].baseline_value, 2),
            model_market_value=market(
                built.model_market,
                player.player_id,
                model[player.player_id].market_value,
            ),
            points=round(player.points, 2),
            vorp=round(player.vorp_live, 2),
            live_value=round(player.baseline_value, 2),
            market_value=market(built.market, player.player_id, player.market_value),
            market_is_estimate=built.market.is_estimate_for(player.player_id),
            blacklisted=player.player_id in stored and stored[player.player_id].blacklisted,
            note=stored[player.player_id].note if player.player_id in stored else "",
        )
        for player in built.board.players
        if player.in_pool_full
    ]
    rows.sort(key=lambda row: (row.is_keeper, -row.live_value, -row.market_value, row.name))
    return rows


class SeatRequest(BaseModel):
    """Who is sitting in a draft slot, asserted by a person looking at the draft room.

    The owner is the name from ``config/keepers.yaml`` — *not* a Sleeper display name. The
    whole point is to bypass display-name resolution, which is what fails when a manager joins
    under a name nobody predicted.
    """

    model_config = ConfigDict(extra="forbid")

    owner: str = Field(min_length=1)
    note: str = ""


class CorrectionRequest(BaseModel):
    """A correction to a team's money, or a keeper the feed has not delivered.

    For a budget, give **either** ``remaining`` (what the room says the team actually has, which
    is what a person says out loud) **or** ``delta``. ``remaining`` is turned into a delta once,
    against the ledger as it stands at that moment, and never recomputed — §4.8's rule that a
    correction must not fight the next poll.
    """

    model_config = ConfigDict(extra="forbid")

    slot: int = Field(ge=1)
    remaining: int | None = Field(default=None, ge=0)
    delta: int | None = None
    player_id: str | None = None
    amount: int | None = Field(default=None, ge=0)
    reason: str = ""


class ReclassifyRequest(BaseModel):
    """A pick the classifier read the wrong way.

    ``FLAGGED`` is deliberately not offered. It is the classifier's way of saying *"I do not
    know, a person should look"*; a person looking and choosing "I do not know" moves nothing
    and leaves the pick out of the competitive series it may well belong in. The two answers
    worth typing are the two that settle it.
    """

    model_config = ConfigDict(extra="forbid")

    pick_no: int = Field(ge=1)
    pick_class: Literal[PickClass.KEEPER, PickClass.COMPETITIVE]
    reason: str = ""


class NominateRequest(BaseModel):
    """Who is on the block. ``null`` clears it.

    Typed by hand, deliberately: Sleeper publishes completed picks over REST and nothing else,
    and charter §2 forbids reverse-engineering the websocket that carries the live nomination.
    """

    model_config = ConfigDict(extra="forbid")

    player_id: str | None = None


def create_app(
    root: Path | None = None,
    store: OverrideStore | None = None,
    *,
    live_draft: LiveDraft | None = None,
    poll: bool = False,
) -> FastAPI:
    """Build the app. ``root`` and ``store`` are injectable so tests never touch real config.

    Args:
        live_draft: The cockpit's draft poller. Injected by tests with a fake client; built
            against the real league when omitted.
        poll: Whether to start the background poll loop. **Off by default**, so importing or
            testing this app never opens a socket to Sleeper — ``make cockpit`` turns it on.
            A test suite that quietly polls a live draft is one that fails on draft night for
            reasons nobody can reproduce.
    """
    base = root or ROOT
    overrides = store or OverrideStore(base / "config" / "value_overrides.yaml")
    # `precompute=poll`: curve precomputation only makes sense while actually polling a live
    # draft, and both are expensive enough that neither should start because something imported
    # this module.
    live = live_draft or LiveDraft(
        base,
        league_id=LEAGUE_ID,
        draft_id=REAL_DRAFT_ID,
        store=overrides,
        precompute=poll,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if not poll:
            yield
            return
        # One httpx client for the whole session, closed on shutdown. The rate floor, retry,
        # backoff and circuit breaker all live in `SleeperClient` and are shared with `smoke`
        # and `replay`; the cockpit gets them by using the same class rather than by promising
        # to be careful.
        async with httpx.AsyncClient() as http:
            if live.client is None:
                live.client = SleeperClient(client=http)
            task = asyncio.create_task(live.run())
            try:
                yield
            finally:
                task.cancel()

    app = FastAPI(title="draft-intel", docs_url="/docs", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/prices")
    def api_prices() -> list[PriceRow]:
        return price_rows(base, overrides)

    @app.post("/api/prices/{player_id}")
    def set_price(player_id: str, edit: OverrideRequest) -> PriceRow:
        row = next((r for r in price_rows(base, overrides) if r.player_id == player_id), None)
        if row is None:
            # An override naming nobody is a typo, and storing it silently leaves the user
            # believing a correction was applied. Same rule `apply_overrides` already enforces.
            raise HTTPException(404, f"no player {player_id!r} on the board")
        if row.is_keeper and edit.live_value is not None:
            # A keeper is off the board. A live price for one is not a small mistake to store
            # quietly: it is a bid recommendation for somebody who cannot be bid on.
            raise HTTPException(
                422,
                f"{row.name} is a keeper and cannot be bid on; override their market value "
                "instead, which is what the 75% retention rule reads",
            )

        held = overrides.load().get(player_id) or ValueOverride(player_id=player_id)
        # A field the request does not carry keeps whatever was stored for it; a field it carries
        # as null is *cleared*. The distinction is the difference between editing one box and
        # wiping the three next to it, and `None` alone cannot express it -- hence
        # `model_fields_set`, which is the only thing that knows what the JSON actually had.
        sent = edit.model_fields_set
        overrides.set(
            ValueOverride(
                player_id=player_id,
                name=row.name,
                live_value=edit.live_value if "live_value" in sent else held.live_value,
                market_value=edit.market_value if "market_value" in sent else held.market_value,
                points=edit.points if "points" in sent else held.points,
                blacklisted=(bool(edit.blacklisted) if "blacklisted" in sent else held.blacklisted),
                note=(edit.note or "") if "note" in sent else held.note,
            )
        )
        return next(r for r in price_rows(base, overrides) if r.player_id == player_id)

    @app.delete("/api/prices/{player_id}")
    def clear_price(player_id: str) -> PriceRow:
        overrides.clear(player_id)
        row = next((r for r in price_rows(base, overrides) if r.player_id == player_id), None)
        if row is None:
            raise HTTPException(404, f"no player {player_id!r} on the board")
        return row

    @app.get("/prices", response_class=HTMLResponse)
    def prices_page() -> str:
        built = build_pipeline(base, overrides=overrides)
        return _render(
            price_rows(base, overrides),
            live_money=built.board.total_live_money,
            orphans=built.orphan_overrides,
        )

    # ------------------------------------------------------------------ the cockpit

    @app.get("/api/live")
    def api_live() -> LiveSnapshot:
        return live.snapshot()

    @app.get("/api/live/search")
    def api_live_search(q: str = "") -> list[dict[str, str | float]]:
        """Name search for typing a nomination. Names resolve a lookup and decide nothing."""
        return [
            {
                "player_id": player.player_id,
                "name": player.name,
                "position": player.position,
                "live_value": round(player.baseline_value, 2),
                "is_keeper": str(player.is_keeper).lower(),
            }
            for player in live.find(q)
        ]

    @app.post("/api/live/nominate")
    def api_nominate(request: NominateRequest) -> LiveSnapshot:
        if request.player_id is not None and not any(
            p.player_id == request.player_id for p in live.pipeline.board.players
        ):
            raise HTTPException(404, f"no player {request.player_id!r} on the board")
        live.nominate(request.player_id)
        return live.snapshot()

    @app.get("/api/live/seats")
    def api_seats() -> dict[str, object]:
        """What is assigned, what is still unplaced, and who there is to place."""
        resolved, expected, unplaced = live.unresolved_keepers()
        teams = live.config.teams
        identity = live.identity
        return {
            "assigned": [s.model_dump() for _slot, s in sorted(live.seats.load().items())],
            "unmapped_slots": (
                identity.unmapped_slots(teams)
                if identity is not None
                else list(range(1, teams + 1))
            ),
            "unplaced_owners": list(unplaced),
            "keepers_resolved": resolved,
            "keepers_expected": expected,
            # What the seats on disk would give once the next poll picks them up. Without this
            # a correct assignment reads as a no-op: the live count cannot move until the
            # classifier is rebuilt, which is a poll away.
            "keepers_if_seated": live.keepers_if_seated(),
        }

    @app.post("/api/live/seats/{slot}")
    def set_seat(slot: int, request: SeatRequest) -> dict[str, object]:
        if not 1 <= slot <= live.config.teams:
            raise HTTPException(422, f"slot {slot} is outside this league's 1..{live.config.teams}")
        known = {owner for owner, _pid in live.pipeline.resolved}
        if request.owner not in known:
            # A seat naming nobody in the manifest silently places nothing, and the user walks
            # away believing six keepers are fixed. Same rule the price table applies to an
            # override naming nobody.
            raise HTTPException(
                404,
                f"{request.owner!r} is not an owner in config/keepers.yaml. "
                f"Known: {', '.join(sorted(known))}",
            )
        live.seats.assign(SeatAssignment(slot=slot, owner=request.owner, note=request.note))
        return {
            "assigned": request.owner,
            "slot": slot,
            "keepers_if_seated": live.keepers_if_seated(),
            "effective": "next poll",
        }

    @app.delete("/api/live/seats/{slot}")
    def clear_seat(slot: int) -> dict[str, object]:
        live.seats.clear(slot)
        return {"cleared": slot}

    @app.get("/api/live/corrections")
    def api_corrections() -> list[dict[str, object]]:
        return [{**c.model_dump(), "describe": c.describe()} for c in live.corrections.load()]

    @app.post("/api/live/corrections/budget")
    def correct_budget(request: CorrectionRequest) -> dict[str, object]:
        team = _team(live, request.slot)
        if request.remaining is None and request.delta is None:
            raise HTTPException(422, "give either `remaining` (what the room says) or `delta`")
        if request.remaining is not None and request.delta is not None:
            # Both would need a rule about which wins, and any such rule is a coin toss the
            # user did not ask for.
            raise HTTPException(422, "give `remaining` or `delta`, not both")

        delta = (
            request.delta
            if request.delta is not None
            else int(request.remaining or 0) - team.remaining
        )
        if delta == 0:
            raise HTTPException(
                422, f"{team.owner} already reads ${team.remaining}; nothing to correct"
            )
        entry = live.corrections.add(
            kind="budget",
            slot=request.slot,
            delta=delta,
            observed=request.remaining,
            reason=request.reason,
        )
        return {"correction": entry.model_dump(), "was": team.remaining, "effective": "next poll"}

    @app.post("/api/live/corrections/keeper")
    def correct_keeper(request: CorrectionRequest) -> dict[str, object]:
        _team(live, request.slot)
        if not request.player_id or request.amount is None:
            raise HTTPException(422, "a manual keeper needs `player_id` and `amount`")
        if not any(p.player_id == request.player_id for p in live.pipeline.board.players):
            raise HTTPException(404, f"no player {request.player_id!r} on the board")
        entry = live.corrections.add(
            kind="keeper",
            slot=request.slot,
            player_id=request.player_id,
            amount=request.amount,
            reason=request.reason,
        )
        return {"correction": entry.model_dump(), "effective": "next poll"}

    @app.get("/api/live/picks")
    def api_picks(q: str = "", limit: int = 25) -> list[dict[str, object]]:
        """Settled picks, newest first, for choosing one to reclassify.

        Newest first because the pick you need to argue with is almost always the one that just
        happened — you watched it land and the class it got is wrong. ``q`` matches a player
        name or an exact pick number, for the case where it is not.
        """
        return live.settled_picks(q, limit=limit)

    @app.post("/api/live/corrections/reclassify")
    def correct_class(request: ReclassifyRequest) -> dict[str, object]:
        settled = live.settled_picks(str(request.pick_no), limit=1)
        current = next((p for p in settled if p["pick_no"] == request.pick_no), None)
        if current is None:
            raise HTTPException(404, f"no pick {request.pick_no} in the ledger")
        if current["pick_class"] == request.pick_class.value:
            # Not an error the user needs protecting from, but a correction that changes nothing
            # is a row that will confuse whoever reads the audit trail later looking for a cause.
            raise HTTPException(
                422, f"pick {request.pick_no} already counts as {request.pick_class.value}"
            )
        entry = live.corrections.add(
            kind="reclassify",
            pick_no=request.pick_no,
            pick_class=request.pick_class,
            reason=request.reason,
        )
        return {
            "correction": entry.model_dump(mode="json"),
            "was": current["pick_class"],
            "effective": "next poll",
        }

    @app.delete("/api/live/corrections/{correction_id}")
    def revert_correction(correction_id: int) -> dict[str, object]:
        undone = live.corrections.revert(correction_id)
        if undone is None:
            raise HTTPException(404, f"no correction {correction_id}")
        return {"correction": undone.model_dump(), "effective": "next poll"}

    @app.get("/live", response_class=HTMLResponse)
    def live_page() -> str:
        identity = live.identity
        _resolved, _expected, unplaced = live.unresolved_keepers()
        return _render_live(
            live.snapshot(),
            corrections=[c for c in live.corrections.load() if not c.reverted],
            teams={t.slot: t.owner for t in live.snapshot().teams},
            unmapped=(
                identity.unmapped_slots(live.config.teams)
                if identity is not None
                else list(range(1, live.config.teams + 1))
            ),
            unplaced=list(unplaced),
            assigned={slot: s.owner for slot, s in live.seats.load().items()},
        )

    return app


def _render(rows: list[PriceRow], *, live_money: int, orphans: tuple[str, ...]) -> str:
    """The table. Server-rendered, no build step, no framework — it is a table."""
    edited = [row for row in rows if row.overridden]
    priced = sum(row.live_value for row in rows if not row.is_keeper)
    # §4.8's visible number. Values are not renormalised after an edit, so once anything is
    # overridden the board stops summing to the money in the room. That gap is shown, never
    # closed: one correction must not silently move every other price.
    deviation = round(priced - live_money, 2)
    banner = (
        f'<p class="dev">{len(edited)} override(s) in force. The board sums to ${priced:,.0f} '
        f"against ${live_money:,} of live money, a deviation of ${deviation:+,.0f}. Values are "
        f"<strong>not</strong> renormalised, deliberately: one edit must not move every other "
        f"price.</p>"
        if edited
        else ""
    )
    orphan_note = (
        f'<p class="dev">{len(orphans)} stored override(s) match no player on the board and are '
        f"being ignored: {escape(', '.join(orphans))}.</p>"
        if orphans
        else ""
    )
    body = "\n".join(_row_html(row) for row in rows)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prices — draft-intel</title>
<style>
  :root {{
    --ground:#f5f6f4; --surface:#fff; --line:#dadeda; --ink:#171d1a; --muted:#6a756f;
    --accent:#0f6e62; --edit:#96701a; --edit-bg:#96701a14; --keeper:#0f6e620f;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --ground:#0d1412; --surface:#141c19; --line:#26312c; --ink:#e6ede9; --muted:#8a968f;
      --accent:#4fbeab; --edit:#d4a63f; --edit-bg:#d4a63f1c; --keeper:#4fbeab12;
    }}
  }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; background:var(--ground); color:var(--ink); font:15px/1.5
    "IBM Plex Sans",ui-sans-serif,system-ui,sans-serif; }}
  .wrap {{ max-width:1240px; margin:0 auto; padding:28px 20px 64px }}
  h1 {{ font:600 26px/1.1 "IBM Plex Serif",ui-serif,Georgia,serif; margin:0 0 6px }}
  p.lede {{ color:var(--muted); margin:0 0 14px; max-width:78ch }}
  p.dev {{ color:var(--edit); margin:0 0 14px; max-width:78ch; font-size:14px }}
  .filter {{ margin:0 0 16px }}
  .filter input {{ width:280px; text-align:left }}
  table {{ width:100%; border-collapse:collapse; background:var(--surface);
    border:1px solid var(--line) }}
  th,td {{ padding:6px 9px; text-align:right; border-bottom:1px solid var(--line);
    font-variant-numeric:tabular-nums; vertical-align:top }}
  th {{ font:600 11px/1.4 ui-monospace,monospace; letter-spacing:.09em; text-transform:uppercase;
    color:var(--muted); text-align:right; position:sticky; top:0; background:var(--surface) }}
  th.l,td.l {{ text-align:left }}
  tr.keeper {{ background:var(--keeper) }}
  tr.edited {{ background:var(--edit-bg) }}
  tr.black td.nm {{ text-decoration:line-through; color:var(--muted) }}
  .was {{ display:block; color:var(--muted); font-size:12px; padding-top:2px }}
  .est {{ color:var(--muted); font-size:11px; font-family:ui-monospace,monospace }}
  input {{ width:74px; padding:3px 6px; font:inherit; font-variant-numeric:tabular-nums;
    text-align:right; border:1px solid var(--line); border-radius:3px;
    background:var(--ground); color:var(--ink) }}
  input[aria-invalid="true"] {{ border-color:#b3261e }}
  button {{ font:inherit; font-size:13px; padding:2px 7px; border:1px solid var(--line);
    border-radius:3px; background:var(--ground); color:var(--ink); cursor:pointer }}
  button:hover {{ border-color:var(--accent); color:var(--accent) }}
  .note {{ color:var(--muted); font-size:13px }}
  .tag {{ font:600 10px ui-monospace,monospace; color:var(--accent); letter-spacing:.06em }}
</style></head><body><div class="wrap">
<h1>Prices</h1>
<p class="lede">Every priced player — {len(rows)} of them, keepers included. Type in any box and
press Enter to override the model; empty it to fall back. <strong>live&nbsp;$</strong> is what to
bid in this auction. <strong>market&nbsp;$</strong> is full-market value, and is the number the
league's <code>floor(0.75 &times; auction value)</code> keeper rule reads. <strong>pts</strong> is
applied upstream of replacement level, so changing it re-derives VORP and every dollar figure.
Keepers carry no live price: they are off the board. Edits are written to
<code>config/value_overrides.yaml</code>, survive a restart, are read by <code>make prep</code>,
and can be edited by hand.</p>
{banner}{orphan_note}
<p class="filter"><input id="q" placeholder="filter by name or position" aria-label="filter"></p>
<table><thead><tr>
<th class="l">player</th><th class="l">pos</th>
<th>pts</th><th>VORP</th><th>live $</th><th>&Delta;</th><th>market $</th>
<th class="l">note</th><th></th>
</tr></thead><tbody>
{body}
</tbody></table>
<script>
async function save(id, field, input) {{
  const raw = input.value.trim();
  const body = {{}};
  body[field] = raw === "" ? null : Number(raw);
  const res = await fetch(`/api/prices/${{id}}`, {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify(body),
  }});
  if (!res.ok) {{ input.setAttribute("aria-invalid", "true"); return; }}
  location.reload();
}}
document.querySelectorAll("input[data-player]").forEach((input) => {{
  input.addEventListener("keydown", (event) => {{
    if (event.key === "Enter") save(input.dataset.player, input.dataset.field, input);
  }});
}});
document.querySelectorAll("button[data-clear]").forEach((button) => {{
  button.addEventListener("click", async () => {{
    await fetch(`/api/prices/${{button.dataset.clear}}`, {{ method: "DELETE" }});
    location.reload();
  }});
}});
const q = document.getElementById("q");
q.addEventListener("input", () => {{
  const needle = q.value.trim().toLowerCase();
  document.querySelectorAll("tbody tr").forEach((tr) => {{
    tr.hidden = needle !== "" && !tr.dataset.search.includes(needle);
  }});
}});
</script>
</div></body></html>"""


def _cell(row: PriceRow, field: str, value: float, model_value: float, suffix: str = "") -> str:
    """One editable figure, with the model's own beneath it whenever the two differ.

    §4.8: the user's number and the model's are shown together, always. A cell that renders only
    the override is a number with no provenance, which is the thing the charter forbids.
    """
    was = f'<span class="was">model {model_value:,.2f}</span>' if value != model_value else ""
    return (
        f'<td><input data-player="{escape(row.player_id)}" data-field="{field}" '
        f'value="{value:.2f}" inputmode="decimal" '
        f'aria-label="{field} for {escape(row.name)}">{suffix}{was}</td>'
    )


def _row_html(row: PriceRow) -> str:
    classes = " ".join(
        name
        for name, on in (
            ("keeper", row.is_keeper),
            ("edited", row.overridden),
            ("black", row.blacklisted),
        )
        if on
    )
    delta = f"{row.delta:+.2f}" if row.delta else ""
    clear = f'<button data-clear="{escape(row.player_id)}">clear</button>' if row.overridden else ""
    tag = ' <span class="tag">KEEPER</span>' if row.is_keeper else ""
    estimate = ' <span class="est">est</span>' if row.market_is_estimate else ""
    # A keeper is off the board, so there is no price to bid and no box to type one into.
    live = (
        '<td class="was">—</td>'
        if row.is_keeper
        else _cell(row, "live_value", row.live_value, row.model_live_value)
    )
    return (
        f'<tr class="{classes}" data-search="{escape((row.name + " " + row.position).lower())}">'
        f'<td class="l nm">{escape(row.name)}{tag}</td>'
        f'<td class="l">{escape(row.position)}</td>'
        + _cell(row, "points", row.points, row.model_points)
        + f"<td>{row.vorp:.1f}</td>"
        + live
        + f"<td>{delta}</td>"
        + _cell(row, "market_value", row.market_value, row.model_market_value, estimate)
        + f'<td class="l note">{escape(row.note)}</td><td>{clear}</td></tr>'
    )


def _render_live(
    snap: LiveSnapshot,
    *,
    unmapped: list[int] | None = None,
    unplaced: list[str] | None = None,
    assigned: dict[int, str] | None = None,
    corrections: list[Correction] | None = None,
    teams: dict[int, str] | None = None,
) -> str:
    """The cockpit. Read at a glance, mid-nomination, while somebody is shouting numbers.

    Every layout decision here follows from that: the block sits at the top at display size, the
    threat ladder is one column you scan downward, and anything that makes the numbers
    untrustworthy is a full-width bar above them rather than a badge beside them. The page
    re-fetches ``/api/live`` on a timer and repaints; there is no framework, because a table and
    a fetch do not need one.
    """
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cockpit — draft-intel</title>
<style>
  :root {{
    --ground:#f5f6f4; --surface:#fff; --line:#dadeda; --ink:#171d1a; --muted:#6a756f;
    --accent:#0f6e62; --warn:#96701a; --warn-bg:#96701a1a; --bad:#a3271e; --bad-bg:#a3271e14;
    --good:#0f6e62;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --ground:#0d1412; --surface:#141c19; --line:#26312c; --ink:#e6ede9; --muted:#8a968f;
      --accent:#4fbeab; --warn:#d4a63f; --warn-bg:#d4a63f22; --bad:#e5776b; --bad-bg:#e5776b1c;
      --good:#4fbeab;
    }}
  }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; background:var(--ground); color:var(--ink); font:15px/1.5
    "IBM Plex Sans",ui-sans-serif,system-ui,sans-serif }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:18px 20px 64px }}
  h1 {{ font:600 20px/1.1 "IBM Plex Serif",ui-serif,Georgia,serif; margin:0 0 2px }}
  h2 {{ font:600 11px/1.4 ui-monospace,monospace; letter-spacing:.09em; text-transform:uppercase;
    color:var(--muted); margin:26px 0 8px }}
  .bar {{ padding:9px 13px; border-radius:4px; margin:0 0 10px; font-size:14px }}
  .bar.bad {{ background:var(--bad-bg); color:var(--bad); border:1px solid var(--bad) }}
  .bar.warn {{ background:var(--warn-bg); color:var(--warn); border:1px solid var(--warn) }}
  .status {{ display:flex; gap:18px; align-items:baseline; color:var(--muted);
    font:12px ui-monospace,monospace; margin:0 0 14px }}
  .status b {{ color:var(--ink) }}
  .status .live {{ color:var(--good) }} .status .dead {{ color:var(--bad) }}
  .block {{ background:var(--surface); border:1px solid var(--line); border-radius:5px;
    padding:16px 18px; margin:0 0 8px }}
  .block .who {{ font:600 24px/1.2 "IBM Plex Serif",ui-serif,Georgia,serif }}
  .figs {{ display:flex; gap:30px; flex-wrap:wrap; margin:12px 0 0 }}
  .fig .k {{ font:600 10px ui-monospace,monospace; letter-spacing:.08em; color:var(--muted);
    text-transform:uppercase }}
  .fig .v {{ font:600 30px/1.1 ui-monospace,monospace; font-variant-numeric:tabular-nums }}
  .fig .v.hi {{ color:var(--good) }} .fig .v.lo {{ color:var(--bad) }}
  .fig .v.none {{ color:var(--muted) }}
  .wa-note {{ margin:10px 0 0; font-size:13.5px; color:var(--muted); max-width:74ch }}
  .wa-note.bad {{ color:var(--bad) }}
  .wa-chart {{ margin:12px 0 0; max-width:520px }}
  .wa-chart svg {{ width:100%; height:auto; display:block }}
  .wa-lbl {{ font:10px ui-monospace,monospace }}
  .wa-cap {{ font-size:12px; color:var(--muted); margin-top:2px }}
  .seats {{ background:var(--surface); border:1px solid var(--warn); border-radius:5px;
    padding:13px 16px; margin:0 0 12px }}
  .seats-hd {{ font:600 10px ui-monospace,monospace; letter-spacing:.09em;
    text-transform:uppercase; color:var(--warn) }}
  .seats-lede {{ margin:5px 0 10px; font-size:13.5px; color:var(--ink-2); max-width:78ch }}
  .seat-form {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap }}
  .seat-is {{ color:var(--muted); font-size:13px }}
  select {{ font:inherit; font-size:14px; padding:4px 7px; border:1px solid var(--line);
    border-radius:3px; background:var(--ground); color:var(--ink) }}
  .seat-list {{ margin:10px 0 0; font-size:13.5px }}
  .seat-list li {{ border-bottom:0; padding:3px 0 }}
  .corr {{ background:var(--surface); border:1px solid var(--line); border-radius:5px;
    padding:10px 16px; margin:0 0 12px }}
  .corr summary {{ font:600 10px ui-monospace,monospace; letter-spacing:.09em;
    text-transform:uppercase; color:var(--muted); cursor:pointer }}
  .corr-on {{ border-color:var(--edit) }}
  .corr-on .seats-hd {{ color:var(--edit) }}
  table {{ width:100%; border-collapse:collapse; background:var(--surface);
    border:1px solid var(--line) }}
  th,td {{ padding:6px 10px; text-align:right; border-bottom:1px solid var(--line);
    font-variant-numeric:tabular-nums }}
  th {{ font:600 10px/1.4 ui-monospace,monospace; letter-spacing:.09em; text-transform:uppercase;
    color:var(--muted) }}
  th.l,td.l {{ text-align:left }}
  tr.me {{ background:#0f6e620f; font-weight:600 }}
  @media (prefers-color-scheme: dark) {{ tr.me {{ background:#4fbeab14 }} }}
  tr.out td {{ color:var(--muted) }}
  .sus {{ color:var(--bad); font-weight:600 }}
  ul.plain {{ margin:0; padding:0; list-style:none }}
  ul.plain li {{ padding:4px 0; border-bottom:1px solid var(--line); font-size:14px }}
  input {{ width:320px; padding:6px 9px; font:inherit; border:1px solid var(--line);
    border-radius:3px; background:var(--surface); color:var(--ink) }}
  .hits {{ margin:6px 0 0; padding:0; list-style:none }}
  .hits li {{ padding:4px 0 }}
  .hits button {{ font:inherit; text-align:left; width:100%; padding:5px 9px; cursor:pointer;
    border:1px solid var(--line); border-radius:3px; background:var(--surface); color:var(--ink) }}
  .hits button:hover {{ border-color:var(--accent); color:var(--accent) }}
  .panel {{ background:var(--surface); border:1px solid var(--line); border-radius:5px;
    padding:14px 16px; margin:0 0 8px; display:grid; gap:9px }}
  .panel .seats-lede {{ margin:0 }}
  button:disabled {{ opacity:.45; cursor:not-allowed; border-color:var(--line);
    color:var(--muted) }}
</style></head><body><div class="wrap">
<h1>Cockpit</h1>
<div id="app">{
        _live_body(
            snap, unmapped or [], unplaced or [], assigned or {}, corrections or [], teams or {}
        )
    }</div>
<h2>who is up</h2>
<input id="q" autocomplete="off"
  placeholder="type a name, then pick" aria-label="nominate a player">
<ul class="hits" id="hits"></ul>

<!-- Every form lives BELOW #app, deliberately. #app is replaced wholesale on each repaint,
     so an input inside it loses whatever you were typing every two seconds. That is fine for
     status and lists, which should refresh, and unusable for anything you type into. -->
<h2>corrections</h2>
<div class="panel">
  <div class="seat-form">
    <select id="corr-slot" aria-label="team"></select>
    <span class="seat-is">actually has $</span>
    <input id="corr-amt" inputmode="numeric" style="width:70px" aria-label="dollars">
    <input id="corr-why" placeholder="why" style="width:200px;text-align:left"
      aria-label="reason">
    <button id="corr-go">correct the money</button>
  </div>
  <p class="seats-lede">Stored as a difference, not a fixed figure, so the next pick will not
    undo it.</p>
  <div class="seat-form">
    <select id="keeper-slot" aria-label="team for keeper"></select>
    <span class="seat-is">keeps</span>
    <input id="keeper-q" autocomplete="off" placeholder="type a name, then pick"
      style="width:210px;text-align:left" aria-label="keeper">
    <span class="seat-is">for $</span>
    <input id="keeper-amt" inputmode="numeric" style="width:64px" aria-label="retention price">
    <button id="keeper-go" disabled>add keeper</button>
  </div>
  <ul class="hits" id="keeper-hits"></ul>
  <p class="seats-lede">Sleeper publishes no auction value, so a retention price is typed from
    the draft room. Superseded automatically if the real pick arrives.</p>
  <div class="seat-form">
    <span class="seat-is">pick</span>
    <input id="class-q" autocomplete="off" placeholder="last 25, or search"
      style="width:210px;text-align:left" aria-label="pick to reclassify">
    <span class="seat-is">was really a</span>
    <select id="class-to" aria-label="what the pick actually was">
      <option value="KEEPER">keeper</option>
      <option value="COMPETITIVE">competitive bid</option>
    </select>
    <button id="class-go" disabled>recount it</button>
  </div>
  <ul class="hits" id="class-hits"></ul>
  <p class="seats-lede">Moves no money. It moves whether those dollars count as a bid — and so
    whether they reach inflation, skew and every tendency profile.</p>
</div>

<h2>seating</h2>
<div class="panel">
  <div class="seat-form">
    <select id="seat-slot" aria-label="draft slot"></select>
    <span class="seat-is">is</span>
    <select id="seat-owner" aria-label="manager"></select>
    <button id="seat-go">assign</button>
  </div>
  <p class="seats-lede">For a manager who joins under a display name
    <code>owners.yaml</code> does not know. Lands on the next poll.</p>
</div>
<script>
async function repaint() {{
  try {{
    const res = await fetch("/api/live");
    if (!res.ok) return;
    const html = await (await fetch("/live")).text();
    const body = html.split('<div id="app">')[1].split("</div>\\n<h2>who is up")[0];
    document.getElementById("app").innerHTML = body;
  }} catch (e) {{ /* a failed repaint leaves the last reading and its age on screen */ }}
}}
setInterval(repaint, 2000);

// The dropdowns are populated from the live snapshot rather than rendered server-side,
// because they sit outside #app (so they survive a repaint) and their contents still have to
// follow the draft -- a manager who joins changes both the team list and the unplaced list.
let keeperPick = null;

async function refreshPickers() {{
  try {{
    const [live, seats] = await Promise.all([
      (await fetch("/api/live")).json(),
      (await fetch("/api/live/seats")).json(),
    ]);
    const teamOptions = live.teams
      .map((t) => `<option value="${{t.slot}}">${{t.owner}}</option>`).join("");
    for (const id of ["corr-slot", "keeper-slot"]) {{
      const el = document.getElementById(id);
      if (el && el.innerHTML !== teamOptions) el.innerHTML = teamOptions;
    }}
    const slotEl = document.getElementById("seat-slot");
    const ownerEl = document.getElementById("seat-owner");
    const slots = (seats.unmapped_slots || [])
      .map((s) => `<option value="${{s}}">slot ${{s}}</option>`).join("");
    const owners = (seats.unplaced_owners || [])
      .map((o) => `<option value="${{o}}">${{o}}</option>`).join("");
    if (slotEl && slotEl.innerHTML !== slots) slotEl.innerHTML = slots;
    if (ownerEl && ownerEl.innerHTML !== owners) ownerEl.innerHTML = owners;
    const go = document.getElementById("seat-go");
    if (go) go.disabled = !slots || !owners;
  }} catch (e) {{ /* leave the pickers as they are rather than emptying them */ }}
}}

function flash(button, text) {{
  const was = button.textContent;
  button.textContent = text;
  setTimeout(() => {{ button.textContent = was; }}, 1600);
}}

document.addEventListener("click", async (event) => {{
  const target = event.target;
  if (!target) return;

  if (target.id === "corr-go") {{
    const raw = document.getElementById("corr-amt").value.trim();
    if (raw === "") return;
    const res = await fetch("/api/live/corrections/budget", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{
        slot: Number(document.getElementById("corr-slot").value),
        remaining: Number(raw),
        reason: document.getElementById("corr-why").value,
      }}),
    }});
    if (!res.ok) {{ flash(target, (await res.json()).detail || "refused"); return; }}
    document.getElementById("corr-amt").value = "";
    document.getElementById("corr-why").value = "";
    repaint();
  }} else if (target.id === "keeper-go") {{
    if (!keeperPick) return;
    const amt = document.getElementById("keeper-amt").value.trim();
    if (amt === "") return;
    const res = await fetch("/api/live/corrections/keeper", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{
        slot: Number(document.getElementById("keeper-slot").value),
        player_id: keeperPick.id,
        amount: Number(amt),
        reason: `${{keeperPick.name}}, typed from the draft room`,
      }}),
    }});
    if (!res.ok) {{ flash(target, (await res.json()).detail || "refused"); return; }}
    keeperPick = null;
    document.getElementById("keeper-q").value = "";
    document.getElementById("keeper-amt").value = "";
    document.getElementById("keeper-hits").innerHTML = "";
    target.disabled = true;
    repaint();
  }} else if (target.id === "class-go") {{
    if (!classPick) {{ flash(target, "pick one first"); return; }}
    const res = await fetch("/api/live/corrections/reclassify", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{
        pick_no: classPick.pick_no,
        pick_class: document.getElementById("class-to").value,
        reason: `${{classPick.name}}, corrected from the draft room`,
      }}),
    }});
    if (!res.ok) {{ flash(target, (await res.json()).detail || "refused"); return; }}
    classPick = null;
    document.getElementById("class-q").value = "";
    document.getElementById("class-hits").innerHTML = "";
    target.disabled = true;
    repaint();
  }} else if (target.id === "seat-go") {{
    const res = await fetch(`/api/live/seats/${{document.getElementById("seat-slot").value}}`, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{
        owner: document.getElementById("seat-owner").value,
        note: "assigned from the cockpit",
      }}),
    }});
    if (!res.ok) {{ flash(target, (await res.json()).detail || "refused"); return; }}
    refreshPickers();
    repaint();
  }} else if (target.dataset && target.dataset.uncorrect) {{
    await fetch(`/api/live/corrections/${{target.dataset.uncorrect}}`, {{ method: "DELETE" }});
    repaint();
  }} else if (target.dataset && target.dataset.unseat) {{
    await fetch(`/api/live/seats/${{target.dataset.unseat}}`, {{ method: "DELETE" }});
    refreshPickers();
    repaint();
  }}
}});

// The keeper needs a player, and a player needs a search. Same endpoint the nomination box
// uses; the id is held in `keeperPick` so the button sends an identity rather than a name.
let keeperTimer = null;
document.addEventListener("input", (event) => {{
  if (!event.target || event.target.id !== "keeper-q") return;
  clearTimeout(keeperTimer);
  keeperTimer = setTimeout(async () => {{
    const box = document.getElementById("keeper-q");
    const list = document.getElementById("keeper-hits");
    const button = document.getElementById("keeper-go");
    keeperPick = null;
    button.disabled = true;
    list.innerHTML = "";
    if (!box.value.trim()) return;
    const rows = await (await fetch(
      `/api/live/search?q=${{encodeURIComponent(box.value)}}`)).json();
    for (const row of rows) {{
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.textContent = `${{row.name}} · ${{row.position}}`
        + (row.is_keeper === "true" ? " · already a keeper" : "");
      b.onclick = () => {{
        keeperPick = {{ id: row.player_id, name: row.name }};
        box.value = row.name;
        list.innerHTML = "";
        button.disabled = false;
      }};
      li.appendChild(b);
      list.appendChild(li);
    }}
  }}, 180);
}});

// Reclassification names a *pick*, not a player: the same player can be bought once and the
// pick number is what a Reclassify keys on. So the list shows pick, buyer, price and the class
// it currently carries -- without the current class you cannot tell whether you are about to
// change anything, and the API refuses a no-op correction rather than writing a row that
// explains nothing to whoever reads the trail later.
let classPick = null;
let classTimer = null;
function drawPicks(rows) {{
  const list = document.getElementById("class-hits");
  const button = document.getElementById("class-go");
  classPick = null;
  button.disabled = true;
  list.innerHTML = "";
  for (const row of rows) {{
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.textContent = `#${{row.pick_no}} · ${{row.name}} · ${{row.owner}} · $${{row.amount}}`
      + ` · now ${{row.pick_class.toLowerCase()}}`;
    b.onclick = () => {{
      classPick = {{ pick_no: row.pick_no, name: row.name }};
      document.getElementById("class-q").value = `#${{row.pick_no}} ${{row.name}}`;
      list.innerHTML = "";
      button.disabled = false;
    }};
    li.appendChild(b);
    list.appendChild(li);
  }}
}}
document.addEventListener("input", (event) => {{
  if (!event.target || event.target.id !== "class-q") return;
  clearTimeout(classTimer);
  classTimer = setTimeout(async () => {{
    const box = document.getElementById("class-q");
    drawPicks(await (await fetch(
      `/api/live/picks?q=${{encodeURIComponent(box.value)}}&limit=8`)).json());
  }}, 180);
}});
// An empty box offers the last few picks rather than nothing, because the pick you need is
// usually the one that just landed and typing its number to find it is a step for no reason.
document.addEventListener("focusin", async (event) => {{
  if (!event.target || event.target.id !== "class-q") return;
  if (document.getElementById("class-q").value.trim()) return;
  drawPicks(await (await fetch("/api/live/picks?limit=8")).json());
}});

refreshPickers();
setInterval(refreshPickers, 10000);

const q = document.getElementById("q"), hits = document.getElementById("hits");
let timer = null;
q.addEventListener("input", () => {{
  clearTimeout(timer);
  timer = setTimeout(async () => {{
    hits.innerHTML = "";
    if (!q.value.trim()) return;
    const rows = await (await fetch(`/api/live/search?q=${{encodeURIComponent(q.value)}}`)).json();
    for (const row of rows) {{
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.textContent = `${{row.name}} · ${{row.position}} · $${{row.live_value}}`
        + (row.is_keeper === "true" ? " · KEEPER" : "");
      b.onclick = async () => {{
        await fetch("/api/live/nominate", {{
          method: "POST", headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ player_id: row.player_id }}),
        }});
        q.value = ""; hits.innerHTML = ""; repaint();
      }};
      li.appendChild(b); hits.appendChild(li);
    }}
  }}, 180);
}});
</script>
</div></body></html>"""


def _live_body(
    snap: LiveSnapshot,
    unmapped: list[int],
    unplaced: list[str],
    assigned: dict[int, str],
    corrections: list[Correction],
    teams: dict[int, str],
) -> str:
    """The part that repaints. Kept separate so the poll loop replaces only what changed."""
    out: list[str] = []

    for blocker in snap.blockers:
        out.append(f'<div class="bar bad">{escape(blocker)}</div>')
    # Directly under the blocker, because it is the fix for it. A banner naming three managers
    # you cannot place is a worse experience than no banner if the remedy is editing YAML and
    # restarting mid-auction.
    out.append(_seats_html(unmapped, unplaced, assigned))
    out.append(_corrections_html(corrections, teams))
    if snap.stale:
        # The failure this module exists to prevent: numbers that stopped updating and look
        # exactly like numbers that did not.
        out.append(
            f'<div class="bar bad">NOT LIVE — last good reading {snap.age_seconds:.0f}s ago '
            f"({escape(snap.connection)}). Every figure below is that old.</div>"
        )

    live_class = "live" if not snap.stale else "dead"
    out.append(
        f'<div class="status">'
        f'<span class="{live_class}">● {escape(snap.connection)}</span>'
        f"<span>{snap.age_seconds:.0f}s ago</span>"
        f"<span>draft <b>{escape(snap.draft_status)}</b></span>"
        f"<span><b>{snap.picks_seen}</b> picks, <b>{snap.competitive_picks}</b> competitive</span>"
        f"<span>room has <b>${snap.total_remaining:,}</b> for "
        f"<b>{snap.total_open_slots}</b> slots</span>"
        f"</div>"
    )

    out.append(_block_html(snap))

    out.append("<h2>the room</h2><table><thead><tr>")
    out.append(
        '<th class="l">team</th><th>keep</th><th>picks</th><th>spent</th><th>left</th>'
        "<th>slots</th><th>max bid</th></tr></thead><tbody>"
    )
    for team in sorted(snap.teams, key=lambda t: (-t.max_bid, t.slot)):
        classes = " ".join(c for c, on in (("me", team.is_me), ("out", team.max_bid == 0)) if on)
        suspect = ' <span class="sus">⚠ SUSPECT</span>' if team.figures_suspect else ""
        out.append(
            f'<tr class="{classes}"><td class="l">{escape(team.owner)}{suspect}</td>'
            f"<td>{team.keepers}</td><td>{team.filled_slots}</td><td>${team.spent}</td>"
            f"<td>${team.remaining}</td><td>{team.open_slots}</td><td>${team.max_bid}</td></tr>"
        )
    out.append("</tbody></table>")

    out.append("<h2>inflation</h2>")
    direction = "over" if snap.inflation >= 1.0 else "under"
    out.append(
        f'<div class="block"><div class="figs"><div class="fig">'
        f'<div class="k">live inflation</div>'
        f'<div class="v">{snap.inflation:.2f}x</div></div></div>'
        f'<p style="color:var(--muted);margin:10px 0 0;font-size:14px">'
        f"{escape(snap.inflation_detail)}</p></div>"
    )
    del direction
    if snap.positions:
        out.append('<ul class="plain">')
        out += [f"<li>{escape(line)}</li>" for line in snap.positions]
        out.append("</ul>")

    if snap.alerts:
        out.append('<h2>alerts</h2><ul class="plain">')
        out += [f"<li>{escape(alert)}</li>" for alert in snap.alerts]
        out.append("</ul>")

    return "\n".join(out)


def _team(live: LiveDraft, slot: int) -> TeamLine:
    """The team in this slot, or a 422 naming the range. Never an invented row.

    A correction against a slot outside the league would sit in the file forever, applying to
    nobody — and the fold reports it as an orphan whose money is deliberately not minted. Better
    to refuse it where the user can still see the typo.
    """
    team = next((t for t in live.snapshot().teams if t.slot == slot), None)
    if team is None:
        raise HTTPException(
            422, f"slot {slot} is not in this league's ledger (1..{live.config.teams})"
        )
    return team


def _seats_html(unmapped: list[int], unplaced: list[str], assigned: dict[int, str]) -> str:
    """What is unplaced and what has been assigned. **Display only** — the form is in the
    stable shell below `#app`, which is replaced wholesale on every repaint.

    A manager who joins under a display name `owners.yaml` has never seen is invisible to the
    tool, and their two keepers classify as competitive bids. That already happened once and
    went unnoticed for days, so it is a banner rather than a log line.
    """
    if not unmapped and not unplaced and not assigned:
        return ""
    rows = ""
    if assigned:
        rows = "".join(
            f"<li>slot {slot} is <strong>{escape(owner)}</strong> "
            f'<button data-unseat="{slot}">clear</button></li>'
            for slot, owner in sorted(assigned.items())
        )
        rows = f'<ul class="plain seat-list">{rows}</ul>'
    lede = (
        f"{len(unplaced)} manager(s) in the keeper manifest have no seat: "
        f"<strong>{escape(', '.join(unplaced))}</strong>. Sleeper does not know them by a name "
        f"<code>owners.yaml</code> recognises, so their keepers will classify as competitive "
        f"bids. Assign them under <em>seating</em> below and it is fixed on the next poll."
        if unplaced
        else "Seats you assigned by hand. These override what Sleeper resolved."
    )
    return (
        f'<div class="seats"><div class="seats-hd">seating</div>'
        f'<p class="seats-lede">{lede}</p>{rows}</div>'
    )


def _corrections_html(corrections: list[Correction], teams: dict[int, str]) -> str:
    """Every correction in force. **Display only**; the forms are in the stable shell.

    A corrected budget must never look like an uncorrected one — §4.8's rule about typed
    numbers applied to the money column. The moment a $5 adjustment stops being visible it is
    indistinguishable from a bug, so this panel is present whenever anything is in force and
    lists what you said alongside what the system derived from it.
    """
    if not corrections:
        return ""

    def label(c: Correction) -> str:
        """Who or what the correction is about. A reclassification is about a pick, not a team.

        It deliberately carries no slot — the pick already answers that, and more currently
        (see ``Correction.slot``) — so naming it by pick number here is the honest label rather
        than a fallback for a missing field.
        """
        if c.slot is None:
            return f"pick {c.pick_no}"
        return teams.get(c.slot, f"slot {c.slot}")

    rows = "".join(
        f"<li><strong>{escape(label(c))}</strong> "
        f"{escape(c.describe().split(': ', 1)[1])}"
        f"{f' — {escape(c.reason)}' if c.reason else ''} "
        f'<button data-uncorrect="{c.id}">undo</button></li>'
        for c in corrections
    )
    return (
        f'<div class="seats corr-on"><div class="seats-hd">corrections in force</div>'
        f'<p class="seats-lede">These numbers are yours, not the feed\'s.</p>'
        f'<ul class="plain seat-list">{rows}</ul></div>'
    )


def _block_html(snap: LiveSnapshot) -> str:
    block = snap.block
    if block is None:
        return (
            '<div class="block"><div class="who" style="color:var(--muted)">'
            "nobody on the block</div>"
            '<p style="color:var(--muted);margin:8px 0 0">Type a name below when the room '
            "nominates. Sleeper does not publish the nomination over its public API, so this "
            "is the one thing you tell the tool rather than the other way round.</p></div>"
        )

    if block.already_drafted_by is not None:
        head = (
            f'<div class="bar warn">{escape(block.name)} is already rostered by '
            f"{escape(block.already_drafted_by)} — bidding on this one is over.</div>"
        )
    elif block.blacklisted:
        head = (
            f'<div class="bar warn">{escape(block.name)} is blacklisted. You told the tool '
            f"never to bid, whatever the number says.</div>"
        )
    else:
        head = ""

    # `hi`/`lo` on the max bid, not on the value: the value is a projection and colouring it
    # would read as advice, while the max bid is arithmetic and zero genuinely means stop.
    max_class = "lo" if block.my_max_bid == 0 else "hi"
    ladder = "".join(f"<li>{escape(line)}</li>" for line in block.ladder)
    note = (
        f'<p style="color:var(--warn);margin:10px 0 0;font-size:14px">your note: '
        f"{escape(block.tier_note)}</p>"
        if block.tier_note
        else ""
    )
    return (
        f"{head}"
        f'<div class="block">'
        f'<div class="who">{escape(block.name)} '
        f'<span style="color:var(--muted);font-size:15px">{escape(block.position)}</span></div>'
        f'<div class="figs">'
        f'<div class="fig"><div class="k">worth to you</div>'
        f'<div class="v">${block.my_value:,.0f}</div></div>'
        f'<div class="fig"><div class="k">at today\'s inflation</div>'
        f'<div class="v">${block.inflation_adjusted:,.0f}</div></div>'
        f'<div class="fig"><div class="k">your max bid</div>'
        f'<div class="v {max_class}">${block.my_max_bid}</div></div>'
        f'<div class="fig"><div class="k">clears the field</div>'
        f'<div class="v">${block.clears_the_field}</div></div>'
        f'<div class="fig"><div class="k">contenders</div>'
        f'<div class="v">{block.contenders}</div></div>'
        f'<div class="fig"><div class="k">walk away above</div>'
        f'<div class="v {"" if block.walk_away is not None else "none"}">'
        f"{f'${block.walk_away}' if block.walk_away is not None else '—'}</div></div>"
        f"</div>{note}{_walkaway_html(block, snap)}</div>"
        f"<h2>who else wants {escape(block.position)}</h2>"
        f'<ul class="plain">{ladder}</ul>'
    )


def _walkaway_html(block: BlockView, snap: LiveSnapshot) -> str:
    """The curve, its caveats, and the state of the board it came from.

    The number alone is not enough to act on. "Walk away above $34" computed for a budget you
    no longer have is worse than no number, so the board's own staleness travels with it —
    §4.8's rule about never letting a figure appear without what qualifies it, applied to the
    one figure the user will act on fastest.
    """
    bits: list[str] = []
    status = snap.walkaway
    if block.walk_away_note:
        bits.append(f'<p class="wa-note">{escape(block.walk_away_note)}</p>')
    if not block.curve_trustworthy:
        bits.append(
            '<p class="wa-note bad">The curve is not monotone — it rises somewhere, so these '
            "deltas cannot be read as a walk-away price. Treat the number above as unusable.</p>"
        )
    if block.curve:
        bits.append(_curve_svg(block))
    if status.state != "current":
        cls = "bad" if status.state == "stale" else ""
        bits.append(f'<p class="wa-note {cls}">Curve board: {escape(status.detail)}</p>')
    return "".join(bits)


def _curve_svg(block: BlockView) -> str:
    """§4.7b's picture: price on x, Δ starting points on y, with the crossing marked.

    Drawn inline rather than with a library because it is a dozen points and one zero line, and
    the crossing *is* the answer — the price where buying stops improving the team. Everything
    else on the chart exists to make that one x-position readable.

    Colours come from the theme tokens so it holds in both, and the viewBox leaves room for the
    outermost labels rather than clipping them.
    """
    prices = [p for p, _ in block.curve]
    deltas = [d for _, d in block.curve]
    if len(prices) < 2:
        return ""
    w, h, pad_l, pad_r, pad_t, pad_b = 460, 130, 38, 14, 12, 26
    lo_x, hi_x = min(prices), max(prices)
    lo_y, hi_y = min(min(deltas), 0.0), max(max(deltas), 0.0)
    span_x = max(1, hi_x - lo_x)
    span_y = (hi_y - lo_y) or 1.0

    def px(v: float) -> float:
        return pad_l + (v - lo_x) / span_x * (w - pad_l - pad_r)

    def py(v: float) -> float:
        return pad_t + (hi_y - v) / span_y * (h - pad_t - pad_b)

    zero = py(0.0)
    line = " ".join(f"{px(p):.1f},{py(d):.1f}" for p, d in block.curve)
    marker = ""
    if block.walk_away is not None and lo_x <= block.walk_away <= hi_x:
        x = px(block.walk_away)
        marker = (
            f'<line x1="{x:.1f}" y1="{pad_t}" x2="{x:.1f}" y2="{h - pad_b}" '
            f'stroke="var(--warn)" stroke-width="1.5" stroke-dasharray="3 3"/>'
            f'<text x="{x:.1f}" y="{pad_t + 9}" class="wa-lbl" text-anchor="middle" '
            f'fill="var(--warn)">${block.walk_away}</text>'
        )
    return (
        f'<div class="wa-chart"><svg viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="walk-away curve for {escape(block.name)}: '
        f'change in starting points against price">'
        f'<line x1="{pad_l}" y1="{zero:.1f}" x2="{w - pad_r}" y2="{zero:.1f}" '
        f'stroke="var(--line)" stroke-width="1"/>'
        f'<text x="{pad_l - 6}" y="{zero + 3:.1f}" class="wa-lbl" text-anchor="end" '
        f'fill="var(--muted)">0</text>'
        f'<polyline points="{line}" fill="none" stroke="var(--accent)" stroke-width="2" '
        f'stroke-linejoin="round"/>'
        f"{marker}"
        f'<text x="{pad_l}" y="{h - 8}" class="wa-lbl" fill="var(--muted)">${lo_x}</text>'
        f'<text x="{w - pad_r}" y="{h - 8}" class="wa-lbl" text-anchor="end" '
        f'fill="var(--muted)">${hi_x}</text>'
        f'<text x="{pad_l - 6}" y="{pad_t + 8}" class="wa-lbl" text-anchor="end" '
        f'fill="var(--muted)">{hi_y:+.0f}</text>'
        f"</svg>"
        f'<div class="wa-cap">&Delta; starting points against price. The team stops improving '
        f"where the line crosses zero.</div></div>"
    )


app = create_app()


def cockpit() -> FastAPI:
    """The app with live polling on. ``make cockpit``'s entry point.

    A factory rather than a module-level instance because ``poll=True`` opens a socket to
    Sleeper, and that must never happen merely because something imported this module.
    """
    return create_app(poll=True)
