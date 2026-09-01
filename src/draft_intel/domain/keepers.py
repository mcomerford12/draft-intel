"""The keeper manifest: expected state, never ledger truth.

The manifest drives pre-draft valuation, pick classification and reconciliation alerting.
It never by itself derives budgets, rosters or slot counts - the picks feed is the sole
authority for money. Keeping those two roles apart is what prevents the divergence bug the
charter warns about in §2.

Names in the manifest are input to ``player_id`` resolution and nothing more. Once resolved,
every downstream comparison keys on ``player_id``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

PriceSource = str


class KeeperEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    pos: str
    player_id: str | None = None
    price: int | None = None
    price_source: PriceSource | None = None


class TeamKeepers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str
    keepers: list[KeeperEntry]


class LeagueKeeperRules(BaseModel):
    model_config = ConfigDict(extra="allow")

    teams: int
    budget: int
    keepers_per_team: int
    retention_rule: str = ""
    value_snapshot_date: str | None = None
    minimum_retention_price: int = 1


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    league: LeagueKeeperRules
    user_team: str
    teams: list[TeamKeepers]

    @property
    def entries(self) -> list[tuple[str, KeeperEntry]]:
        return [(t.owner, k) for t in self.teams for k in t.keepers]


def load_manifest(path: str | Path) -> Manifest:
    return Manifest.model_validate(yaml.safe_load(Path(path).read_text()))


class AmbiguousPlayer(Exception):
    """Raised when a manifest name cannot be resolved to exactly one player."""


def resolve_player_id(name: str, position: str, players: dict[str, dict[str, Any]]) -> str:
    """Resolve one manifest name to a Sleeper ``player_id``, confirming by position.

    Position confirmation is not optional. Sleeper's map carries a guard named Josh Allen
    alongside the Buffalo quarterback, and a cornerback named Lamar Jackson alongside the
    Baltimore one. Matching on name alone silently attaches a keeper to the wrong player and
    corrupts that team's roster for the whole draft.
    """
    candidates = [
        pid
        for pid, p in players.items()
        if f"{p.get('first_name') or ''} {p.get('last_name') or ''}".strip() == name
    ]
    confirmed = [pid for pid in candidates if players[pid].get("position") == position]
    if len(confirmed) == 1:
        return confirmed[0]
    if not candidates:
        raise AmbiguousPlayer(f"{name!r} ({position}) matched no player in the Sleeper map")
    detail = ", ".join(f"{pid}:{players[pid].get('position')}" for pid in candidates)
    raise AmbiguousPlayer(
        f"{name!r} ({position}) resolved to {len(confirmed)} players by position "
        f"out of {len(candidates)} name matches [{detail}]"
    )


def resolve_manifest(
    manifest: Manifest, players: dict[str, dict[str, Any]]
) -> dict[tuple[str, str], KeeperEntry]:
    """Resolve every keeper, returning a mapping of ``(owner, player_id)`` to the entry."""
    out: dict[tuple[str, str], KeeperEntry] = {}
    for owner, entry in manifest.entries:
        pid = entry.player_id or resolve_player_id(entry.name, entry.pos, players)
        out[(owner, pid)] = entry.model_copy(update={"player_id": pid})
    return out


def retention_price(market_value: int, *, minimum: int = 1) -> int:
    """``floor(0.75 * market_value)``, clamped to the league minimum bid.

    This is a *check*, not a price source. Sleeper publishes no auction value over REST
    (docs/api-findings.md, Finding 3), so real retention prices are read from the draft room
    and this function only tells us when a loaded price looks wrong.

    The clamp matters because ``floor(0.75 * 1) == 0``, and a $0 pick breaks both money
    conservation and the max-bid reserve, which assumes every filled slot cost at least $1.
    """
    return max(minimum, (market_value * 3) // 4)
