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

from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, computed_field

from draft_intel.prep import build_pipeline
from draft_intel.store.overrides import OverrideStore, ValueOverride

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


def create_app(root: Path | None = None, store: OverrideStore | None = None) -> FastAPI:
    """Build the app. ``root`` and ``store`` are injectable so tests never touch real config."""
    base = root or ROOT
    overrides = store or OverrideStore(base / "config" / "value_overrides.yaml")
    app = FastAPI(title="draft-intel", docs_url="/docs")

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


app = create_app()
