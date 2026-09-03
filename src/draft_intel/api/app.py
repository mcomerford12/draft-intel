"""The price table: a route that shows every price, and lets the user change one.

Charter §4.8 has always required per-player value overrides. What it did not have was a surface
— the plumbing existed in :mod:`draft_intel.quant.overrides` and nothing called it. This is the
surface, and it is deliberately the smallest thing that does the job:

* ``GET  /prices``                  the table, sorted by live value, editable in place
* ``GET  /api/prices``              the same rows as JSON
* ``POST /api/prices/{player_id}``  set or clear one player's override
* ``GET  /healthz``                 is it up

**The model's number is never overwritten.** Every row shows ``model`` beside ``yours``, because
"the model said $17.74 and I said $40" is a different fact from "$40", and on draft night the
difference is the whole reason to trust or distrust the number. Deleting an override falls back
to the model rather than to zero.

Overrides persist to ``config/value_overrides.yaml`` — see :mod:`draft_intel.api.store` for why
a file rather than the event log. They survive a restart and can be edited by hand.

**This is not the cockpit.** It reads the same pipeline ``make prep`` does, so the two cannot
disagree, and it holds no draft state: no picks, no budgets, no bidding. Sprint 3 owns that.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from draft_intel.api.store import OverrideStore, ValueOverride
from draft_intel.prep import build_pipeline
from draft_intel.quant.overrides import apply_overrides

ROOT = Path(__file__).resolve().parents[3]


class PriceRow(BaseModel):
    """One player as the table shows them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    player_id: str
    name: str
    position: str
    points: float
    vorp: float

    model_live_value: float
    """What the model says this player should cost in this auction, always retained."""

    live_value: float
    """What the tool will actually price them at: the override if there is one, else the model."""

    market_value: float
    overridden: bool
    blacklisted: bool
    note: str = ""

    @property
    def delta(self) -> float:
        """How far the user moved the model, in dollars. Zero when untouched."""
        return round(self.live_value - self.model_live_value, 2)


class OverrideRequest(BaseModel):
    """A price edit. Every field optional: send only what you are changing."""

    model_config = ConfigDict(extra="forbid")

    live_value: float | None = Field(default=None, ge=0)
    market_value: float | None = Field(default=None, ge=0)
    points: float | None = None
    blacklisted: bool = False
    note: str = ""


def price_rows(root: Path, store: OverrideStore) -> list[PriceRow]:
    """The priced board with overrides applied, sorted by what the user will bid against.

    Built from :func:`draft_intel.prep.build_pipeline` — the same chain ``make prep`` runs — so
    the page and the printed report cannot quote different numbers for the same player.
    """
    built = build_pipeline(root)
    stored = store.load()
    result = apply_overrides(
        [p for p in built.board.players if not p.is_keeper and p.in_pool_live],
        total_live_money=built.board.total_live_money,
        players=store.as_player_overrides(),
    )
    rows = [
        PriceRow(
            player_id=value.player.player_id,
            name=value.player.name,
            position=value.player.position,
            points=value.points,
            vorp=value.player.vorp_live,
            model_live_value=round(value.player.baseline_value, 2),
            live_value=round(value.baseline_value, 2),
            market_value=round(value.market_value, 2),
            overridden=value.is_overridden,
            blacklisted=value.blacklisted,
            note=stored[value.player.player_id].note if value.player.player_id in stored else "",
        )
        for value in result.values
    ]
    rows.sort(key=lambda row: (-row.live_value, row.name))
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
        known = {row.player_id for row in price_rows(base, overrides)}
        if player_id not in known:
            # An override naming nobody is a typo, and storing it silently leaves the user
            # believing a correction was applied. Same rule `apply_overrides` already enforces.
            raise HTTPException(404, f"no player {player_id!r} on the board")
        name = next(r.name for r in price_rows(base, overrides) if r.player_id == player_id)
        overrides.set(
            ValueOverride(
                player_id=player_id,
                name=name,
                live_value=edit.live_value,
                market_value=edit.market_value,
                points=edit.points,
                blacklisted=edit.blacklisted,
                note=edit.note,
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
        return _render(price_rows(base, overrides))

    return app


def _render(rows: list[PriceRow]) -> str:
    """The table. Server-rendered, no build step, no framework — it is a table."""
    edited = sum(1 for row in rows if row.overridden)
    body = "\n".join(_row_html(row) for row in rows)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prices — draft-intel</title>
<style>
  :root {{
    --ground:#f5f6f4; --surface:#fff; --line:#dadeda; --ink:#171d1a; --muted:#6a756f;
    --accent:#0f6e62; --edit:#96701a; --edit-bg:#96701a14;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --ground:#0d1412; --surface:#141c19; --line:#26312c; --ink:#e6ede9; --muted:#8a968f;
      --accent:#4fbeab; --edit:#d4a63f; --edit-bg:#d4a63f1c;
    }}
  }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; background:var(--ground); color:var(--ink); font:15px/1.5
    "IBM Plex Sans",ui-sans-serif,system-ui,sans-serif; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:28px 20px 64px }}
  h1 {{ font:600 26px/1.1 "IBM Plex Serif",ui-serif,Georgia,serif; margin:0 0 6px }}
  p.lede {{ color:var(--muted); margin:0 0 22px; max-width:70ch }}
  table {{ width:100%; border-collapse:collapse; background:var(--surface);
    border:1px solid var(--line) }}
  th,td {{ padding:7px 10px; text-align:right; border-bottom:1px solid var(--line);
    font-variant-numeric:tabular-nums }}
  th {{ font:600 11px/1.4 ui-monospace,monospace; letter-spacing:.09em; text-transform:uppercase;
    color:var(--muted); text-align:right; position:sticky; top:0; background:var(--surface) }}
  th.l,td.l {{ text-align:left }}
  tr.edited {{ background:var(--edit-bg) }}
  td.yours {{ font-weight:600 }}
  tr.edited td.yours {{ color:var(--edit) }}
  input {{ width:72px; padding:3px 6px; font:inherit; font-variant-numeric:tabular-nums;
    text-align:right; border:1px solid var(--line); border-radius:3px;
    background:var(--ground); color:var(--ink) }}
  button {{ font:inherit; padding:3px 9px; border:1px solid var(--line); border-radius:3px;
    background:var(--ground); color:var(--ink); cursor:pointer }}
  button:hover {{ border-color:var(--accent); color:var(--accent) }}
  .note {{ color:var(--muted); font-size:13px }}
  .count {{ font:600 12px ui-monospace,monospace; color:var(--edit) }}
</style></head><body><div class="wrap">
<h1>Prices</h1>
<p class="lede">Every available player, priced for this auction. Type a number in
<strong>yours</strong> and press Enter to override the model; clear it to fall back.
Edits are written to <code>config/value_overrides.yaml</code> and survive a restart, so you can
also edit that file by hand. <span class="count">{edited} overridden</span></p>
<table><thead><tr>
<th class="l">player</th><th class="l">pos</th><th>pts</th><th>VORP</th>
<th>model $</th><th>yours $</th><th>Δ</th><th class="l">note</th><th></th>
</tr></thead><tbody>
{body}
</tbody></table>
<script>
async function save(id, input) {{
  const raw = input.value.trim();
  const method = raw === "" ? "DELETE" : "POST";
  const opts = {{ method }};
  if (method === "POST") {{
    opts.headers = {{ "Content-Type": "application/json" }};
    opts.body = JSON.stringify({{ live_value: Number(raw) }});
  }}
  const res = await fetch(`/api/prices/${{id}}`, opts);
  if (!res.ok) {{ input.setAttribute("aria-invalid", "true"); return; }}
  location.reload();
}}
document.querySelectorAll("input[data-player]").forEach((input) => {{
  input.addEventListener("keydown", (event) => {{
    if (event.key === "Enter") save(input.dataset.player, input);
  }});
}});
document.querySelectorAll("button[data-clear]").forEach((button) => {{
  button.addEventListener("click", async () => {{
    await fetch(`/api/prices/${{button.dataset.clear}}`, {{ method: "DELETE" }});
    location.reload();
  }});
}});
</script>
</div></body></html>"""


def _row_html(row: PriceRow) -> str:
    delta = f"{row.delta:+.2f}" if row.overridden else ""
    clear = f'<button data-clear="{escape(row.player_id)}">clear</button>' if row.overridden else ""
    return (
        f'<tr class="{"edited" if row.overridden else ""}">'
        f'<td class="l">{escape(row.name)}</td>'
        f'<td class="l">{escape(row.position)}</td>'
        f"<td>{row.points:.1f}</td><td>{row.vorp:.1f}</td>"
        f"<td>{row.model_live_value:.2f}</td>"
        f'<td class="yours"><input data-player="{escape(row.player_id)}" '
        f'value="{row.live_value:.2f}" inputmode="decimal" '
        f'aria-label="price for {escape(row.name)}"></td>'
        f"<td>{delta}</td>"
        f'<td class="l note">{escape(row.note)}</td><td>{clear}</td></tr>'
    )


app = create_app()
