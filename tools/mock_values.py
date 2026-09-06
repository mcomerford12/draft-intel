"""Extract observed auction prices from the completed mock draft.

The mock's 160 picks each carry a ``metadata.amount``. That is not an estimate of anything --
it is **160 dollar amounts that ten managers actually paid**, in a room with this league's
settings, this league's roster shape and this league's budgets. Nothing else available to this
project has that property: the shipped market values come from an ADP rank transfer plus an
internal model, and are badged ``ESTIMATE`` everywhere they appear for exactly that reason.

Run with ``make mock-values``. Writes ``reports/mock_auction_values.csv`` -- deliberately **not**
``config/auction_values.csv``, because dropping it there changes every keeper price, every
surplus figure and the whole structural inflation read, and that is the user's decision rather
than this script's.

Resolution is on ``player_id``, which the picks feed carries directly. No name matching anywhere:
the CSV loader takes a ``player_id`` column in preference to a name, and the charter forbids a
name deciding anything.

**What this data is, and is not.**

*Is*: one complete observation of how this specific room allocates $2,000 across a 2QB roster.
That shape -- which positions it overpays, where its cliffs fall -- is the read worth having, and
it is not available from any projection source.

*Is not*: a consensus. Every player has exactly one observation. A mock is also played without
money at stake, and the place that shows up worst is precisely the tail, where a $1 price means
"the bidding stopped", not "this player is worth a dollar". Treating those as valuations would
put a $15 quarterback's keeper price at $1.

So the report below separates the contested prices from the tail, and says which is which.
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Any, NamedTuple

from draft_intel.prep import build_pipeline
from draft_intel.store.overrides import OverrideStore

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "mock_auction_values.csv"

UNCONTESTED = 2
"""At or below this, the price records an absence of bidding rather than a valuation.

Not a tuning knob. In an auction the last players go for the minimum by construction -- supply
meets demand exactly and somebody takes what is left. A $1 sale says nobody else wanted the slot
at that moment, which is a fact about the room's remaining money, not about the player.
"""


class Observed(NamedTuple):
    player_id: str
    name: str
    position: str
    paid: int
    model: float

    @property
    def delta(self) -> float:
        return round(self.paid - self.model, 1)

    @property
    def contested(self) -> bool:
        return self.paid > UNCONTESTED


def observations() -> list[Observed]:
    """Every mock pick that lands on a player the current board prices."""
    picks: list[dict[str, Any]] = json.loads((ROOT / "fixtures" / "picks.json").read_text())
    paid = {
        pick["player_id"]: int(pick["metadata"]["amount"])
        for pick in picks
        if (pick.get("metadata") or {}).get("amount") not in (None, "")
    }
    built = build_pipeline(ROOT, overrides=OverrideStore(Path("/nonexistent/overrides.yaml")))
    board = {player.player_id: player for player in built.board.players}

    out: list[Observed] = []
    for player_id, amount in paid.items():
        player = board.get(player_id)
        model = built.market.get(player_id)
        if player is None or not player.in_pool_full or model is None:
            continue
        out.append(Observed(player_id, player.name, player.position, amount, round(model, 1)))
    return sorted(out, key=lambda o: -o.paid)


def write_csv(rows: list[Observed]) -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["player_id", "name", "position", "value", "note"])
        for row in sorted(rows, key=lambda o: (o.position, -o.paid)):
            note = "" if row.contested else "uncontested - bidding stopped, not a valuation"
            writer.writerow([row.player_id, row.name, row.position, row.paid, note])
    return OUT


def report(rows: list[Observed]) -> None:
    rule = "=" * 78
    print(rule)
    print("OBSERVED AUCTION PRICES — from the completed mock draft")
    print(rule)
    paid = sum(r.paid for r in rows)
    model = sum(r.model for r in rows)
    print(f"  players priced             {len(rows)} of 160 in the pool")
    print(f"  total paid                 ${paid}   against ${model:.0f} of model value")
    print(f"  aggregate ratio            {paid / model:.3f}")
    deltas = [r.delta for r in rows]
    print(
        f"  paid - model               mean {statistics.mean(deltas):+.1f}, "
        f"median {statistics.median(deltas):+.1f}"
    )
    correlation = statistics.correlation([r.paid for r in rows], [r.model for r in rows])
    print(f"  correlation                {correlation:.3f}")
    print()
    print("  The totals agree. The SHAPE does not, and the shape is the point:")
    print()
    print(f"  {'pos':<5}{'n':>4}{'paid':>8}{'model':>8}{'ratio':>8}")
    by_pos: dict[str, list[Observed]] = {}
    for row in rows:
        by_pos.setdefault(row.position, []).append(row)
    for position in sorted(by_pos, key=lambda k: -sum(r.paid for r in by_pos[k])):
        group = by_pos[position]
        a = sum(r.paid for r in group)
        m = sum(r.model for r in group)
        print(f"  {position:<5}{len(group):>4}{a:>8}{m:>8.0f}{a / m:>8.2f}")

    tail = [r for r in rows if not r.contested]
    print()
    print(rule)
    print(f"THE TAIL — {len(tail)} players went for ${UNCONTESTED} or less")
    print(rule)
    print("  These are not valuations. In an auction the last players go for the minimum by")
    print("  construction: supply meets demand and somebody takes what is left. Adopting them")
    print("  as market values would price a keeper's retention at $1.")
    print()
    for row in sorted(tail, key=lambda r: r.model - r.paid, reverse=True)[:10]:
        print(f"    ${row.paid:>2}  model ${row.model:>5.1f}   {row.position:<3} {row.name}")

    print()
    print(rule)
    print("WHERE THE ROOM DISAGREED MOST WITH THE MODEL — contested prices only")
    print(rule)
    contested = [r for r in rows if r.contested]
    for row in sorted(contested, key=lambda r: -abs(r.delta))[:12]:
        print(
            f"    paid ${row.paid:>3}   model ${row.model:>5.1f}   {row.delta:+6.1f}   "
            f"{row.position:<3} {row.name}"
        )


def main(argv: list[str] | None = None) -> int:
    del argv
    rows = observations()
    if not rows:
        print("no observations — the picks fixture resolved nothing against the board")
        return 1
    report(rows)
    path = write_csv(rows)
    print()
    print("=" * 78)
    print(f"written to {path}")
    print()
    print("  This file is NOT read by anything yet. To adopt it:")
    print("      cp reports/mock_auction_values.csv config/auction_values.csv && make prep")
    print()
    print("  That replaces the ADP-transfer estimates for these players, clears the ESTIMATE")
    print("  badge, and moves every keeper rule price, surplus figure and the structural")
    print("  inflation read with them. Consider deleting the uncontested rows first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
