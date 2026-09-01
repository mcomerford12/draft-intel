"""Config tripwire and keeper resolution, exercised against the real league fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from draft_intel.config import (
    ConfigMismatch,
    LeagueConfig,
    Severity,
    assert_startable,
    positions_from_roster,
    validate,
)
from draft_intel.domain.identity import build_identity, manifest_keys
from draft_intel.domain.keepers import (
    AmbiguousPlayer,
    load_manifest,
    resolve_manifest,
    resolve_player_id,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


@pytest.fixture(scope="module")
def players() -> dict:
    return json.loads((FIXTURES / "players_slim.json").read_text())


@pytest.fixture(scope="module")
def real_league() -> dict:
    return json.loads((FIXTURES / "league.json").read_text())


@pytest.fixture(scope="module")
def real_draft() -> dict:
    return json.loads((FIXTURES / "real_draft.json").read_text())


# --------------------------------------------------------------------------- config


def test_roster_positions_match_the_charter(real_league):
    """The league object is the source we trust, and it agrees with the charter exactly."""
    starters = positions_from_roster(real_league["roster_positions"])
    assert starters == {"QB": 2, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1}
    assert "DEF" not in starters
    assert len(real_league["roster_positions"]) == 16


def test_real_league_starts_but_warns_about_the_stale_draft_settings(real_league, real_draft):
    """The known live inconsistency must warn loudly and still let the tool boot.

    draft.settings says 1 QB, 1 DEF, 5 bench, 15 rounds while roster_positions says 2 QB, no
    DEF, 6 bench, 16 slots. Blocking on that would take the tool down on draft night over a
    discrepancy we have already diagnosed.
    """
    issues = validate(LeagueConfig(), real_league, real_draft)
    warnings = assert_startable(issues)  # must not raise
    fields = {w.field for w in warnings}
    assert "draft.slots_qb" in fields
    assert "draft.slots_def" in fields
    assert "draft.rounds" in fields
    assert "league.max_keepers" in fields
    assert all(w.severity == Severity.WARNING for w in warnings)


def test_a_changed_roster_setting_refuses_to_start(real_league, real_draft):
    """The tripwire's actual job: a commissioner changing QB slots the night before."""
    tampered = dict(real_league)
    tampered["roster_positions"] = [
        p if p != "QB" else "SUPER_FLEX" for p in real_league["roster_positions"]
    ]
    issues = validate(LeagueConfig(), tampered, real_draft)
    with pytest.raises(ConfigMismatch, match=r"starters\.QB"):
        assert_startable(issues)


def test_budget_change_refuses_to_start(real_league, real_draft):
    tampered = json.loads(json.dumps(real_draft))
    tampered["settings"]["budget"] = 100
    with pytest.raises(ConfigMismatch, match="budget"):
        assert_startable(validate(LeagueConfig(), real_league, tampered))


# --------------------------------------------------------------------------- keepers


def test_josh_allen_collision_resolves_to_the_quarterback(players):
    """The charter warned about this one. A guard shares the name."""
    assert resolve_player_id("Josh Allen", "QB", players) == "4984"
    assert players["4984"]["team"] == "BUF"


def test_lamar_jackson_collision_resolves_to_the_quarterback(players):
    """The charter did not warn about this one; a cornerback shares the name."""
    assert resolve_player_id("Lamar Jackson", "QB", players) == "4881"
    assert players["4881"]["team"] == "BAL"


def test_name_only_matching_would_be_ambiguous(players):
    """Proof the position confirmation is load-bearing rather than ceremonial."""
    same_name = [
        p for p in players.values() if f"{p['first_name']} {p['last_name']}" == "Josh Allen"
    ]
    assert len(same_name) > 1


def test_wrong_position_is_an_error_not_a_silent_mismatch(players):
    with pytest.raises(AmbiguousPlayer):
        resolve_player_id("Josh Allen", "TE", players)


def test_unknown_player_is_an_error(players):
    with pytest.raises(AmbiguousPlayer, match="matched no player"):
        resolve_player_id("Nobody At All", "QB", players)


def test_all_twenty_keepers_resolve_uniquely(players):
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    resolved = resolve_manifest(manifest, players)
    assert len(resolved) == 20
    assert len({pid for _, pid in resolved}) == 20
    for (_owner, pid), entry in resolved.items():
        assert players[pid]["position"] == entry.pos


def test_resolved_ids_match_the_mock_draft_picks(players):
    """Independent confirmation: the ids we resolved are the ids Sleeper actually used."""
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    resolved = resolve_manifest(manifest, players)
    picks = json.loads((FIXTURES / "picks.json").read_text())
    by_name = {f"{p['metadata']['first_name']} {p['metadata']['last_name']}": p for p in picks}
    for (_owner, pid), entry in resolved.items():
        assert by_name[entry.name]["player_id"] == pid


def test_manifest_positional_split_matches_appendix_a(players):
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    counts: dict[str, int] = {}
    for _owner, entry in manifest.entries:
        counts[entry.pos] = counts.get(entry.pos, 0) + 1
    assert counts == {"QB": 7, "RB": 6, "WR": 7}


def test_three_teams_need_two_quarterbacks():
    """A.4's most exploitable fact, re-derived rather than trusted."""
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    no_qb = [t.owner for t in manifest.teams if not any(k.pos == "QB" for k in t.keepers)]
    assert sorted(no_qb) == ["AJ", "Burt", "Mason"]


# --------------------------------------------------------------------------- identity


def test_identity_maps_slots_owners_and_the_me_alias():
    draft = json.loads((FIXTURES / "draft.json").read_text())
    identity = build_identity(draft, aliases={"Me": "Matt"})
    assert identity.owner_for(1) == "AJ"
    assert identity.slot_for("Me") == 3
    assert identity.slot_for("Matt") == 3
    assert identity.slot_to_roster[3] == 3


def test_unmapped_owners_are_dropped_not_guessed(players):
    """Six managers have not joined the real league; inventing slots would misattribute keepers."""
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    resolved = resolve_manifest(manifest, players)
    partial = build_identity({"metadata": {"slot_name_1": "AJ"}, "slot_to_roster_id": {}})
    keys = manifest_keys(resolved, partial)
    assert len(keys) == 2
    assert all(slot == 1 for slot, _ in keys)
