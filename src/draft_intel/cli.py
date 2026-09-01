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

from draft_intel.config import Severity, assert_startable, load_league_config, validate
from draft_intel.domain.classify import KeeperClassifier, keepers_seen, reconcile
from draft_intel.domain.identity import (
    Identity,
    UnresolvedManifest,
    build_identity,
    manifest_keys,
)
from draft_intel.domain.keepers import load_manifest, resolve_manifest
from draft_intel.domain.ledger import fold
from draft_intel.replay.harness import load_picks, replay_all, replay_rejects
from draft_intel.sleeper.client import SleeperClient

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
CONFIG = ROOT / "config"

USERNAME = "mattchupiccu"
LEAGUE_ID = "1391959336820953088"
REAL_DRAFT_ID = "1391959337445920768"


def _aliases(key: str = "aliases") -> dict[str, str]:
    data = yaml.safe_load((CONFIG / "owners.yaml").read_text()) or {}
    merged = dict(data.get("aliases") or {})
    merged.update(data.get(key) or {} if key != "aliases" else {})
    return merged


def _classifier(
    draft: dict[str, Any], players: dict[str, Any], identity: Identity, *, require: int | None
) -> KeeperClassifier:
    manifest = load_manifest(CONFIG / "keepers.yaml")
    resolved = resolve_manifest(manifest, players)
    return KeeperClassifier(manifest_keys=manifest_keys(resolved, identity, require=require))


def replay() -> int:
    """Replay the completed mock draft and print the final ledger."""
    payload = load_picks(FIXTURES / "picks.json")
    draft = json.loads((FIXTURES / "draft.json").read_text())
    players = json.loads((FIXTURES / "players_slim.json").read_text())
    identity = build_identity(draft, aliases=_aliases("mock_aliases"))
    config = load_league_config(CONFIG / "league.yaml")
    manifest = load_manifest(CONFIG / "keepers.yaml")
    state = fold(
        replay_all(payload),
        slots=range(1, config.teams + 1),
        budget=config.budget,
        total_slots=config.total_slots,
        max_keepers=config.keepers_per_team,
        classifier=_classifier(
            draft, players, identity, require=config.teams * config.keepers_per_team
        ),
        expect_keepers=True,
        rejects=replay_rejects(payload),
    )

    print(
        f"{'slot':>4}  {'owner':<8} {'picks':>5} {'keep':>4} {'spent':>6} {'left':>5} {'maxbid':>7}"
    )
    for slot, team in sorted(state.teams.items()):
        print(
            f"{slot:>4}  {identity.owner_for(slot):<8} {team.filled_slots:>5} "
            f"{len(team.keepers):>4} {team.spent:>6} {team.remaining:>5} {team.max_bid:>7}"
        )
    recorded = {s: [(r.player_id, r.amount) for r in t.keepers] for s, t in state.teams.items()}
    seen, complete = keepers_seen(recorded)

    # Reconciliation against the manifest. This is the readout that catches a wrong price, a
    # keeper that quietly changed, or a team entering only one - the errors most likely to
    # actually occur on draft night, each of which silently corrupts a budget for the evening.
    # The function existed from Sprint 1 and was called by nothing outside tests.
    expected: dict[int, list[tuple[str, int | None]]] = {}
    for (owner, player_id), entry in resolve_manifest(manifest, players).items():
        slot = identity.slot_for(owner)
        if slot is not None:
            expected.setdefault(slot, []).append((player_id, entry.price))

    total_keepers = config.teams * config.keepers_per_team
    print(
        f"\ntotal spent ${state.total_spent}  remaining ${state.total_remaining}  "
        f"keeper spend ${state.keeper_spend()}"
    )
    print(f"keepers seen: {seen}/{total_keepers}   teams complete: {complete}/{config.teams}")
    print(f"competitive picks: {len(state.competitive_seq)}")
    for line in reconcile(recorded, expected, keepers_per_team=config.keepers_per_team):
        print(f"  RECONCILE {line}")
    for reject in state.rejects:
        print(f"  REJECT {reject}")
    for orphan in state.orphans:
        print(f"  ORPHAN {orphan}")
    for alert in state.alerts:
        print(f"  ALERT {alert}")
    return 0


async def _smoke() -> int:
    async with httpx.AsyncClient() as http:
        client = SleeperClient(client=http)
        league = await client.league(LEAGUE_ID)
        draft = await client.draft(REAL_DRAFT_ID)
        picks = await client.picks(REAL_DRAFT_ID) or []
        rosters = await client.rosters(LEAGUE_ID) or []
        users = await client.users(LEAGUE_ID) or []

    config = load_league_config(CONFIG / "league.yaml")
    warnings = assert_startable(validate(config, league, draft))
    print(f"league    : {league['name']} ({league['status']})")
    print(f"draft     : {draft['status']}, {len(picks)} picks")
    print("config    : startable")
    for warning in warnings:
        assert warning.severity == Severity.WARNING
        print(f"  WARN {warning}")

    # The real draft object carries no slot_name_* keys at all, so this join is the ONLY path
    # that resolves owners in production. It was implemented, tested, and called by nothing.
    identity = build_identity(draft, rosters=rosters, users=users, aliases=_aliases())
    print(
        f"identity  : {len(identity.slot_to_owner)}/{config.teams} slots resolved"
        f" {sorted(identity.slot_to_owner.items())}"
    )
    if not identity.is_complete(config.teams):
        print(f"  BLOCKER unmapped draft slots: {identity.unmapped_slots(config.teams)}")

    players = json.loads((FIXTURES / "players_slim.json").read_text())
    manifest = load_manifest(CONFIG / "keepers.yaml")
    try:
        keys = manifest_keys(
            resolve_manifest(manifest, players),
            identity,
            require=config.teams * config.keepers_per_team,
            teams=config.teams,
        )
        print(f"manifest  : {len(keys)} keeper keys resolved")
    except UnresolvedManifest as exc:
        print(f"  BLOCKER {exc}")
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
