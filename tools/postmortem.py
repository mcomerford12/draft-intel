"""The draft that actually happened, against the board that predicted it.

``make postmortem``. Reads ``fixtures/live/`` -- a snapshot of the completed draft taken from
Sleeper, kept as a fixture so this is reproducible after the API forgets, moves or changes.

Four questions, in the order they matter to the person who played:

1. **How did I do.** Every pick, what it cost, what the model said it was worth.
2. **How did everyone do.** The same, per team, ranked.
3. **Was the model any good.** Predicted against actual, by position and by price band. This is
   the scorecard on the whole project and it is reported whichever way it comes out.
4. **What is this room actually like.** The shape of its spending, and where its cliffs fell.

----

**Three facts about this draft that the analysis has to respect, none of them assumptions.**

*Budgets are per team and they differ*, $192 to $212, carried in ``draft.settings.budget_<slot>``
rather than the single ``budget`` field. They encode the league's keeper economics. Reading the
flat $200 would have shown two teams overspending and three underspending by a wide margin, all
of it fictional.

*Slot to owner comes from the keeper manifest, not from display names.* Two managers joined under
names ``config/owners.yaml`` has never seen. Every slot holds exactly the two keepers one
manifest owner is listed as keeping, which identifies them from data rather than from a
resemblance -- the rule that mapping is confirmed rather than inferred is about names looking
alike, and this is the keeper slate matching.

*The first twenty picks are the ceremonial round* -- one per team per round, every one a manifest
keeper, all carrying ``is_keeper: false`` exactly as Sprint 0 found. They are retention prices,
not bids, and mixing them into the auction analysis is the single failure this project has spent
its whole life preventing. They are reported separately throughout.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, NamedTuple

from draft_intel.domain.keepers import load_manifest, resolve_manifest
from draft_intel.prep import build_pipeline
from draft_intel.store.overrides import OverrideStore

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "fixtures" / "live"
RULE = "=" * 78

CEREMONIAL_ROUNDS = 2
"""Picks per team that are keeper retentions rather than bids, from the league's own rule."""


class Pick(NamedTuple):
    pick_no: int
    slot: int
    owner: str
    display: str
    player_id: str
    name: str
    position: str
    paid: int
    value: float
    """The model's live auction value -- what it said this player was worth in this auction."""

    keeper: bool

    @property
    def surplus(self) -> float:
        """Value minus price. Positive means they got him for less than the model's number."""
        return round(self.value - self.paid, 1)


class Draft(NamedTuple):
    picks: list[Pick]
    budgets: dict[int, int]
    display: dict[int, str]
    owner: dict[int, str]

    @property
    def bids(self) -> list[Pick]:
        return [p for p in self.picks if not p.keeper]

    @property
    def keepers(self) -> list[Pick]:
        return [p for p in self.picks if p.keeper]


def load() -> Draft:
    draft = json.loads((LIVE / "draft.json").read_text())
    raw = json.loads((LIVE / "picks.json").read_text())
    users = {
        u["user_id"]: u.get("display_name") for u in json.loads((LIVE / "users.json").read_text())
    }
    owners = {
        r["roster_id"]: r.get("owner_id") for r in json.loads((LIVE / "rosters.json").read_text())
    }
    players = json.loads((ROOT / "fixtures" / "players_slim.json").read_text())

    resolved = resolve_manifest(load_manifest(ROOT / "config" / "keepers.yaml"), players)
    keeper_owner = {player_id: owner for (owner, player_id) in resolved}

    settings = draft["settings"]
    slot_to_roster = draft["slot_to_roster_id"]
    budgets = {
        int(slot): int(settings.get(f"budget_{slot}", settings["budget"]))
        for slot in slot_to_roster
    }
    display = {
        int(slot): str(users.get(owners.get(rid)) or f"slot {slot}")
        for slot, rid in slot_to_roster.items()
    }

    # Slot -> manifest owner, by which keepers landed there. Data, not resemblance.
    by_slot: dict[int, set[str]] = {}
    for row in raw:
        who = keeper_owner.get(row["player_id"])
        if who is not None:
            by_slot.setdefault(int(row["draft_slot"]), set()).add(who)
    owner = {
        slot: (sorted(names)[0] if len(names) == 1 else f"slot {slot} (ambiguous)")
        for slot, names in by_slot.items()
    }

    built = build_pipeline(ROOT, overrides=OverrideStore(Path("/nonexistent/overrides.yaml")))
    board = {p.player_id: p for p in built.board.players}
    # A keeper's `baseline_value` is **zero by construction** -- they are off the auction board,
    # and a bid price for somebody nobody can bid on is not a number. Comparing a $39 retention
    # against $0 would report a $39 loss on every keeper in the league. The comparable figure for
    # a retention is the *market* value: what they would have cost had they been in the auction,
    # which is also the figure the league's 75% rule reads.
    market = built.market

    picks: list[Pick] = []
    for row in sorted(raw, key=lambda r: r["pick_no"]):
        player = board.get(row["player_id"])
        meta = row.get("metadata") or {}
        slot = int(row["draft_slot"])
        picks.append(
            Pick(
                pick_no=int(row["pick_no"]),
                slot=slot,
                owner=owner.get(slot, f"slot {slot}"),
                display=display.get(slot, f"slot {slot}"),
                player_id=row["player_id"],
                name=player.name if player else f"{meta.get('first_name')} {meta.get('last_name')}",
                position=player.position if player else str(meta.get("position") or "?"),
                paid=int(meta.get("amount") or 0),
                value=_value(player, market, row["player_id"] in keeper_owner),
                keeper=row["player_id"] in keeper_owner,
            )
        )
    return Draft(picks, budgets, display, owner)


def _value(player: Any, market: Any, keeper: bool) -> float:
    """What the model said this player was worth, on the basis the pick was made.

    A competitive bid is measured against ``baseline_value`` -- the live auction price. A keeper
    retention is measured against ``market_value``, because that is the quantity a retention is a
    discount on, and because ``baseline_value`` is zero for anyone off the board.
    """
    if player is None:
        return 0.0
    if keeper:
        return round(market.get(player.player_id) or player.market_value, 1)
    return round(player.baseline_value, 1)


def _table(rows: list[Pick], *, limit: int | None = None) -> None:
    for p in rows[:limit]:
        print(
            f"    #{p.pick_no:>3}  {p.position:<3} {p.name:<24} ${p.paid:>3}   "
            f"model ${p.value:>5.1f}   {p.surplus:+6.1f}"
        )


def me(draft: Draft, who: str) -> None:
    print(RULE)
    print(f"1. YOUR DRAFT — {who}")
    print(RULE)
    mine = [p for p in draft.picks if p.owner == who]
    if not mine:
        print(f"  no picks found for {who!r}")
        return
    slot = mine[0].slot
    bids = [p for p in mine if not p.keeper]
    keeps = [p for p in mine if p.keeper]
    paid = sum(p.paid for p in bids)
    value = sum(p.value for p in bids)
    print(f"  seat {slot} ({draft.display[slot]})   budget ${draft.budgets[slot]}")
    print(f"  keepers      {len(keeps):>2} for ${sum(p.paid for p in keeps):>4}")
    print(
        f"  bids         {len(bids):>2} for ${paid:>4}   model value ${value:>6.1f}   "
        f"surplus {value - paid:+.1f}"
    )
    print()
    print("  your bids, best value first:")
    _table(sorted(bids, key=lambda p: -p.surplus))
    print()
    print("  your keepers (retention price vs open-market value):")
    _table(sorted(keeps, key=lambda p: -p.surplus))


def league(draft: Draft) -> None:
    print()
    print(RULE)
    print("2. THE LEAGUE — surplus captured on competitive bids")
    print(RULE)
    print("  Surplus is model value minus what was paid, over the 140 competitive picks only.")
    print("  Keeper retentions are excluded: they were not bids and nobody won them.")
    print()
    print(
        f"  {'owner':<9}{'seat':>5}{'budget':>8}{'bid $':>7}{'value':>8}{'surplus':>9}{'per $':>7}"
    )
    rows = []
    for slot in sorted(draft.budgets):
        bids = [p for p in draft.bids if p.slot == slot]
        if not bids:
            continue
        paid = sum(p.paid for p in bids)
        value = sum(p.value for p in bids)
        rows.append((value - paid, slot, paid, value, len(bids)))
    for surplus, slot, paid, value, _n in sorted(rows, reverse=True):
        print(
            f"  {draft.owner.get(slot, '?'):<9}{slot:>5}{draft.budgets[slot]:>8}"
            f"{paid:>7}{value:>8.1f}{surplus:>+9.1f}{value / paid if paid else 0:>7.2f}"
        )


def scorecard(draft: Draft) -> None:
    print()
    print(RULE)
    print("3. WAS THE MODEL ANY GOOD — predicted against actual")
    print(RULE)
    bids = [p for p in draft.bids if p.value > 0]
    paid = sum(p.paid for p in bids)
    value = sum(p.value for p in bids)
    deltas = [p.paid - p.value for p in bids]
    print(f"  competitive picks priced   {len(bids)} of {len(draft.bids)}")
    print(
        f"  total paid                 ${paid}   model said ${value:.0f}   ratio {paid / value:.3f}"
    )
    print(
        f"  paid - model               mean {statistics.mean(deltas):+.1f}   "
        f"median {statistics.median(deltas):+.1f}"
    )
    if len(bids) > 2:
        r = statistics.correlation([p.paid for p in bids], [p.value for p in bids])
        print(f"  correlation                {r:.3f}")
        print(f"  mean absolute error        ${statistics.mean([abs(d) for d in deltas]):.1f}")
    print()
    print(f"  {'pos':<5}{'n':>4}{'paid':>8}{'model':>8}{'ratio':>8}")
    by_pos: dict[str, list[Pick]] = {}
    for p in bids:
        by_pos.setdefault(p.position, []).append(p)
    for pos in sorted(by_pos, key=lambda k: -sum(p.paid for p in by_pos[k])):
        g = by_pos[pos]
        a, m = sum(p.paid for p in g), sum(p.value for p in g)
        print(f"  {pos:<5}{len(g):>4}{a:>8}{m:>8.1f}{a / m if m else 0:>8.2f}")

    print()
    print("  by price band — where the model was wrong is more useful than by how much:")
    print(f"  {'band':<10}{'n':>4}{'paid':>8}{'model':>8}{'ratio':>8}")
    for lo, hi, label in [
        (40, 999, "$40+"),
        (25, 40, "$25-39"),
        (15, 25, "$15-24"),
        (5, 15, "$5-14"),
        (0, 5, "$1-4"),
    ]:
        g = [p for p in bids if lo <= p.paid < hi]
        if not g:
            continue
        a, m = sum(p.paid for p in g), sum(p.value for p in g)
        print(f"  {label:<10}{len(g):>4}{a:>8}{m:>8.1f}{a / m if m else 0:>8.2f}")

    print()
    print("  biggest misses — the model said cheap, the room paid up:")
    _table(sorted(bids, key=lambda p: p.value - p.paid)[:8])
    print()
    print("  biggest misses — the model said expensive, the room passed:")
    _table(sorted(bids, key=lambda p: -(p.value - p.paid))[:8])


def tendencies(draft: Draft) -> None:
    print()
    print(RULE)
    print("4. WHAT THIS ROOM IS LIKE")
    print(RULE)
    bids = draft.bids
    total = sum(p.paid for p in bids)
    print(f"  {'band':<10}{'n':>4}{'paid':>8}{'share':>8}")
    for lo, hi, label in [
        (40, 999, "$40+"),
        (25, 40, "$25-39"),
        (15, 25, "$15-24"),
        (5, 15, "$5-14"),
        (0, 5, "$1-4"),
    ]:
        g = [p for p in bids if lo <= p.paid < hi]
        if not g:
            continue
        a = sum(p.paid for p in g)
        print(f"  {label:<10}{len(g):>4}{a:>8}{a / total:>7.1%}")

    for position in ("QB", "RB", "WR", "TE"):
        group = sorted([p for p in draft.picks if p.position == position], key=lambda p: -p.paid)
        if len(group) < 6:
            continue
        print()
        print(f"  {position} — every one taken, keepers marked (K), biggest cliff flagged")
        gaps = [(group[i - 1].paid - group[i].paid, i) for i in range(1, len(group))]
        cliff = max(gaps)[1] if gaps else None
        for i, p in enumerate(group):
            mark = "  <-- biggest cliff" if i == cliff else ""
            tag = "K" if p.keeper else " "
            print(f"     {tag} ${p.paid:>3}  model ${p.value:>5.1f}   {p.name}{mark}")


def main(argv: list[str] | None = None) -> int:
    del argv
    if not (LIVE / "picks.json").exists():
        print(f"no snapshot at {LIVE}. Take one first.")
        return 1
    draft = load()
    manifest_user = load_manifest(ROOT / "config" / "keepers.yaml").user_team
    me(draft, manifest_user)
    league(draft)
    scorecard(draft)
    tendencies(draft)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
