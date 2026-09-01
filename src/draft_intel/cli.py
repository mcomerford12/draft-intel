"""Sprint 1 command line: replay a completed draft, or smoke-test the live API.

There is no cockpit yet. These two commands are how the data spine is exercised by hand.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from draft_intel.config import LeagueConfig, Severity, assert_startable, validate
from draft_intel.domain.classify import KeeperClassifier, keepers_seen
from draft_intel.domain.identity import build_identity, manifest_keys
from draft_intel.domain.keepers import load_manifest, resolve_manifest
from draft_intel.domain.ledger import fold
from draft_intel.replay.harness import load_picks, replay_all
from draft_intel.sleeper.client import SleeperClient

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
CONFIG = ROOT / "config"

USERNAME = "mattchupiccu"
LEAGUE_ID = "1391959336820953088"
REAL_DRAFT_ID = "1391959337445920768"


def _aliases() -> dict[str, str]:
    data = yaml.safe_load((CONFIG / "owners.yaml").read_text()) or {}
    return dict(data.get("aliases") or {})


def _classifier(draft: dict[str, Any], players: dict[str, Any]) -> KeeperClassifier:
    manifest = load_manifest(CONFIG / "keepers.yaml")
    identity = build_identity(draft, aliases=_aliases())
    return KeeperClassifier(
        manifest_keys=manifest_keys(resolve_manifest(manifest, players), identity)
    )


def replay() -> int:
    """Replay the completed mock draft and print the final ledger."""
    payload = load_picks(FIXTURES / "picks.json")
    draft = json.loads((FIXTURES / "draft.json").read_text())
    players = json.loads((FIXTURES / "players_slim.json").read_text())
    identity = build_identity(draft, aliases=_aliases())
    state = fold(replay_all(payload), slots=range(1, 11), classifier=_classifier(draft, players))

    print(
        f"{'slot':>4}  {'owner':<8} {'picks':>5} {'keep':>4} {'spent':>6} {'left':>5} {'maxbid':>7}"
    )
    for slot, team in sorted(state.teams.items()):
        print(
            f"{slot:>4}  {identity.owner_for(slot):<8} {team.filled_slots:>5} "
            f"{len(team.keepers):>4} {team.spent:>6} {team.remaining:>5} {team.max_bid:>7}"
        )
    seen, complete = keepers_seen(
        {s: [(r.player_id, r.amount) for r in t.keepers] for s, t in state.teams.items()}
    )
    print(
        f"\ntotal spent ${state.total_spent}  remaining ${state.total_remaining}  "
        f"keeper spend ${state.keeper_spend()}"
    )
    print(f"keepers seen: {seen}/20   teams complete: {complete}/10")
    print(f"competitive picks: {len(state.competitive_seq)}")
    for alert in state.alerts:
        print(f"  ALERT {alert}")
    return 0


async def _smoke() -> int:
    async with httpx.AsyncClient() as http:
        client = SleeperClient(client=http)
        league = await client.league(LEAGUE_ID)
        draft = await client.draft(REAL_DRAFT_ID)
        picks = await client.picks(REAL_DRAFT_ID) or []

    warnings = assert_startable(validate(LeagueConfig(), league, draft))
    print(f"league    : {league['name']} ({league['status']})")
    print(f"draft     : {draft['status']}, {len(picks)} picks")
    print("config    : startable")
    for warning in warnings:
        assert warning.severity == Severity.WARNING
        print(f"  WARN {warning}")
    return 0


def smoke() -> int:
    """Hit the live API, validate the real league, and poll the real draft once."""
    return asyncio.run(_smoke())


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    command = args[0] if args else "replay"
    if command == "replay":
        return replay()
    if command == "smoke":
        return smoke()
    print(f"unknown command {command!r}; expected 'replay' or 'smoke'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
