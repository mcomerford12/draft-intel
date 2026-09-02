"""Config tripwire and keeper resolution, exercised against the real league fixtures."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from draft_intel.config import (
    ConfigMismatch,
    LeagueConfig,
    Severity,
    assert_startable,
    load_league_config,
    positions_from_roster,
    validate,
)
from draft_intel.domain.identity import UnresolvedManifest, build_identity, manifest_keys
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


# --------------------------------------------------------------------------------------
# Regressions for the identity findings (DI-EVAL-1 B1) and the missing config file (M6).
# --------------------------------------------------------------------------------------


def test_real_draft_has_no_slot_names_at_all(real_draft):
    """The premise of the draft-night defect, pinned so it cannot regress silently."""
    metadata = real_draft.get("metadata") or {}
    assert not [k for k in metadata if k.startswith("slot_name_")]


def test_roster_user_fallback_resolves_owners_the_draft_object_cannot(real_draft):
    """B1: metadata alone resolved ZERO owners against the real league."""
    rosters = json.loads((FIXTURES / "rosters.json").read_text())
    users = json.loads((FIXTURES / "users.json").read_text())

    assert build_identity(real_draft).slot_to_owner == {}

    identity = build_identity(real_draft, rosters=rosters, users=users)
    assert identity.slot_for("mattchupiccu") == 3  # the user's own roster_id
    assert len(identity.slot_to_owner) == 4  # only 4 of 10 managers have joined
    assert not identity.is_complete(10)
    assert identity.unmapped_slots(10) == [5, 6, 7, 8, 9, 10]


def test_partial_manifest_raises_instead_of_silently_miscounting(players, real_draft):
    """B1: dropping unmapped owners silently turned every keeper into a competitive bid."""
    rosters = json.loads((FIXTURES / "rosters.json").read_text())
    users = json.loads((FIXTURES / "users.json").read_text())
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    resolved = resolve_manifest(manifest, players)
    aliases = yaml.safe_load((ROOT / "config" / "owners.yaml").read_text())["aliases"]
    identity = build_identity(real_draft, rosters=rosters, users=users, aliases=aliases)

    # Without `require` the old silent behaviour is still reachable, and is wrong.
    assert len(manifest_keys(resolved, identity)) < 20

    with pytest.raises(UnresolvedManifest, match="competitive bid"):
        manifest_keys(resolved, identity, require=20)


def test_mock_draft_manifest_resolves_completely(players):
    """The fixture path must still resolve all 20, or the replay gate means nothing."""
    draft = json.loads((FIXTURES / "draft.json").read_text())
    manifest = load_manifest(ROOT / "config" / "keepers.yaml")
    identity = build_identity(draft, aliases={"Me": "Matt"})
    assert len(manifest_keys(resolve_manifest(manifest, players), identity, require=20)) == 20


def test_league_config_file_exists_and_matches_the_live_league(real_league):
    """M6: the error message and ADR-0002 both named a file that did not exist."""
    config = load_league_config(ROOT / "config" / "league.yaml")
    assert config.starters == positions_from_roster(real_league["roster_positions"])
    assert config.roster_size == len(real_league["roster_positions"])
    assert assert_startable(
        validate(config, real_league, json.loads((FIXTURES / "real_draft.json").read_text()))
    )  # warnings, but startable


def test_the_configured_draft_start_matches_sleeper_exactly(real_draft):
    """The user says 2026-09-05 19:00 MT; Sleeper's start_time must say the same instant.

    19:00 MDT is UTC-06:00, so the epoch millis must land on 2026-09-06T01:00:00Z. This is the
    check that would have caught the date being a day out, which it was for most of a sprint.
    """
    config = load_league_config(ROOT / "config" / "league.yaml")
    assert config.draft_start == "2026-09-06T01:00:00Z"
    issues = validate(config, json.loads((FIXTURES / "league.json").read_text()), real_draft)
    assert not [i for i in issues if i.field == "draft.start_time"]


def test_a_moved_draft_warns_and_still_boots(real_league, real_draft):
    """A commissioner nudging the start time must never be able to keep the tool down."""
    moved = json.loads(json.dumps(real_draft))
    moved["start_time"] = real_draft["start_time"] + 3_600_000
    warnings = assert_startable(
        validate(load_league_config(ROOT / "config" / "league.yaml"), real_league, moved)
    )
    drift = [w for w in warnings if w.field == "draft.start_time"]
    assert len(drift) == 1
    assert drift[0].actual == "2026-09-06T02:00:00Z"


# ------------------------------------------------- roster size vs draft rounds (DI-045)


def test_two_extra_bench_spots_warn_but_do_not_block(real_league, real_draft):
    """The user reports 18 roster positions against 16 draft rounds.

    Waiver capacity above the draft costs nothing at auction, so it must move no price and
    must not refuse the boot. Before DI-045 this raised ConfigMismatch and took the tool down.
    """
    config = load_league_config(ROOT / "config" / "league.yaml")
    grown = dict(real_league)
    grown["roster_positions"] = [*real_league["roster_positions"], "BN", "BN"]

    warnings = assert_startable(validate(config, grown, real_draft))  # must not raise
    fields = {w.field for w in warnings}
    assert "roster_size" in fields
    assert "bench" in fields

    # The pool assertion has to compare two configs that differ in roster capacity, or it says
    # nothing: reading `config.auction_pool` off a config the mutated payload never touched
    # passes for any implementation, including one computing `teams * roster_size`.
    grown_config = replace(config, roster_size=18, bench=8)
    assert grown_config.auction_pool == config.auction_pool == 160
    assert grown_config.roster_size != config.roster_size


def test_a_roster_too_small_to_seat_the_draft_refuses_to_start(real_league, real_draft):
    """The one roster-shape case that is incoherent rather than merely surprising."""
    config = load_league_config(ROOT / "config" / "league.yaml")
    shrunk = dict(real_league)
    shrunk["roster_positions"] = real_league["roster_positions"][:12]
    with pytest.raises(ConfigMismatch, match="roster_size"):
        assert_startable(validate(config, shrunk, real_draft))


def test_a_self_contradictory_config_file_is_rejected_at_load(tmp_path):
    """roster_size below draft_rounds is our own typo, and must not reach the API comparison."""
    path = tmp_path / "league.yaml"
    path.write_text(
        "teams: 10\nbudget: 200\ndraft_rounds: 16\nroster_size: 14\n"
        "keepers_per_team: 2\nbench: 6\nstarters: {QB: 2}\n"
    )
    with pytest.raises(ConfigMismatch, match="self-contradictory"):
        load_league_config(path)


def test_draft_rounds_and_roster_size_are_not_the_same_knob(tmp_path):
    """A bigger roster with the same draft must not change the priced pool by a single spot."""
    body = (
        "teams: 10\nbudget: 200\ndraft_rounds: 16\nroster_size: {size}\n"
        "keepers_per_team: 2\nbench: 6\nstarters: {{QB: 2}}\n"
    )
    (tmp_path / "a.yaml").write_text(body.format(size=16))
    (tmp_path / "b.yaml").write_text(body.format(size=18))
    assert load_league_config(tmp_path / "a.yaml").auction_pool == 160
    assert load_league_config(tmp_path / "b.yaml").auction_pool == 160


# ------------------------------------- draft_rounds severity (DI-046, review B1)


def _league_with(real_league: dict, *, rounds_in_roster: int) -> dict:
    """The real league with its roster padded or trimmed to a given length."""
    positions = list(real_league["roster_positions"])
    while len(positions) < rounds_in_roster:
        positions.append("BN")
    return {**real_league, "roster_positions": positions[:rounds_in_roster]}


def test_draft_rounds_blocks_when_both_api_fields_agree_against_the_config(real_league, real_draft):
    """The scenario the first version of this check shipped without covering.

    The commissioner re-saves draft settings, the roster grows to 18 and `rounds` becomes 18.
    The two independent API fields now corroborate each other and our configured 16 is wrong.
    Under the old code this booted with warnings and priced a 160-player pool against a
    180-pick draft: `pool_full` excludes twenty players who will actually be bought,
    `discretionary` is off by twenty dollars, and the §4.3 sum invariants still pass because
    they are self-consistent against the wrong pool. A wrong-priced board with no error.
    """
    config = load_league_config(ROOT / "config" / "league.yaml")
    league = _league_with(real_league, rounds_in_roster=18)
    draft = json.loads(json.dumps(real_draft))
    draft["settings"]["rounds"] = 18

    with pytest.raises(ConfigMismatch, match="draft_rounds"):
        assert_startable(validate(config, league, draft))


def test_draft_rounds_blocks_in_the_dangerous_direction_too(real_league, real_draft):
    """A configured value LARGER than reality is the direction no downstream guard catches.

    The ledger's per-team slot cap fires only when a team takes one pick too many, which is the
    end of the draft, and never fires at all when the configured figure exceeds reality.
    """
    config = load_league_config(ROOT / "config" / "league.yaml")
    league = _league_with(real_league, rounds_in_roster=14)
    draft = json.loads(json.dumps(real_draft))
    draft["settings"]["rounds"] = 14

    issues = validate(config, league, draft)
    blocking = [i for i in issues if i.severity == Severity.BLOCKING]
    assert any(i.field == "draft_rounds" for i in blocking), blocking


def test_draft_rounds_only_warns_while_the_api_disagrees_with_itself(real_league, real_draft):
    """Today's state: roster says 16, draft.settings says 15. Nothing is authoritative, so the
    tool must boot -- blocking here takes it down on draft night over a diagnosed discrepancy."""
    config = load_league_config(ROOT / "config" / "league.yaml")
    warnings = assert_startable(validate(config, real_league, real_draft))  # must not raise
    assert any(w.field == "draft.rounds" for w in warnings)


def test_a_bigger_roster_alone_does_not_block_draft_rounds(real_league, real_draft):
    """Roster length stops being evidence about the draft once the two are decoupled.

    18 roster positions with draft.settings still saying 15: the API disagrees with itself, so
    this is the commissioner's reported shape and it must boot.
    """
    config = load_league_config(ROOT / "config" / "league.yaml")
    league = _league_with(real_league, rounds_in_roster=18)
    warnings = assert_startable(validate(config, league, real_draft))  # must not raise
    assert {"roster_size", "bench"} <= {w.field for w in warnings}


def test_a_non_numeric_rounds_value_warns_rather_than_crashing(real_league, real_draft):
    config = load_league_config(ROOT / "config" / "league.yaml")
    draft = json.loads(json.dumps(real_draft))
    draft["settings"]["rounds"] = "sixteen"
    warnings = assert_startable(validate(config, real_league, draft))
    assert any(w.field == "draft.rounds" for w in warnings)


def test_a_blocking_roster_size_message_still_names_the_configured_value(real_league, real_draft):
    """m4: the operator needs to see what was expected at the moment it refuses to start."""
    config = load_league_config(ROOT / "config" / "league.yaml")
    league = _league_with(real_league, rounds_in_roster=12)
    with pytest.raises(ConfigMismatch, match=r"expected '16 \(and at least draft_rounds, 16\)'"):
        assert_startable(validate(config, league, real_draft))


# ------------------------------------------------ draft_start normalisation (m3)


@pytest.mark.parametrize(
    "raw",
    [
        "2026-09-06T01:00:00Z",
        "2026-09-06T01:00:00+00:00",
        "2026-09-05T19:00:00-06:00",
        datetime(2026, 9, 6, 1, 0, tzinfo=UTC),
        datetime(2026, 9, 6, 1, 0),
    ],
)
def test_every_spelling_of_the_same_instant_collapses_to_one(tmp_path, raw):
    """An unquoted timestamp is parsed by yaml into a datetime, which would never equal a str
    and would warn permanently about a draft that has not moved."""
    path = tmp_path / "league.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "teams": 10,
                "budget": 200,
                "draft_rounds": 16,
                "roster_size": 16,
                "keepers_per_team": 2,
                "bench": 6,
                "starters": {"QB": 2},
                "draft_start": raw,
            }
        )
    )
    assert load_league_config(path).draft_start == "2026-09-06T01:00:00Z"


def test_an_unparseable_start_time_warns_rather_than_raising(real_league, real_draft):
    config = load_league_config(ROOT / "config" / "league.yaml")
    draft = json.loads(json.dumps(real_draft))
    draft["settings"]["rounds"] = 16  # quiet the unrelated warning
    draft["start_time"] = "not a timestamp"
    warnings = assert_startable(validate(config, real_league, draft))
    drift = [w for w in warnings if w.field == "draft.start_time"]
    assert len(drift) == 1
    assert "unparseable" in str(drift[0].actual)


# ------------------------- mutation escapes found by the adversarial evaluator (DI-047)


def test_an_undiagnosed_rounds_value_blocks_even_though_the_api_disagrees_with_itself(
    real_league, real_draft
):
    """The evaluator's payload, which survived the DI-046 fix.

    `draft.settings.rounds = 14` against a 16-slot roster is a legal ADR-0005 league: 14 drafted,
    two waiver spots. The API disagrees with itself, so the DI-046 rule warned -- and that warning
    is indistinguishable from the known-stale 15, sitting among three other routine ones. The
    board then priced a 160-spot pool for a 140-pick draft, moving the top of the board by around
    30%, with all three §4.3 invariants passing because they are self-consistent against whatever
    pool they are handed.

    A number we have no account of is not a diagnosed discrepancy, and must not be treated as one.
    """
    config = load_league_config(ROOT / "config" / "league.yaml")
    draft = json.loads(json.dumps(real_draft))
    draft["settings"]["rounds"] = 14

    with pytest.raises(ConfigMismatch, match="draft_rounds"):
        assert_startable(validate(config, real_league, draft))


def test_the_one_diagnosed_stale_value_still_only_warns(real_league, real_draft):
    """Finding 1's discrepancy is understood. Blocking on it takes the tool down tonight."""
    config = load_league_config(ROOT / "config" / "league.yaml")
    assert config.draft_rounds_api_known_stale == real_draft["settings"]["rounds"] == 15
    warnings = assert_startable(validate(config, real_league, real_draft))  # must not raise
    assert any(w.field == "draft.rounds" for w in warnings)


def test_clearing_the_known_stale_value_makes_every_disagreement_block(real_league, real_draft):
    """What the config should look like once DI-004 lands and the re-save is confirmed."""
    config = replace(
        load_league_config(ROOT / "config" / "league.yaml"), draft_rounds_api_known_stale=None
    )
    with pytest.raises(ConfigMismatch, match="draft_rounds"):
        assert_startable(validate(config, real_league, real_draft))


def test_a_changed_team_count_refuses_to_start(real_league, real_draft):
    """`teams` multiplies both the budget pool and the priced pool. Previously unasserted."""
    config = load_league_config(ROOT / "config" / "league.yaml")
    tampered = {**real_league, "total_rosters": 12}
    with pytest.raises(ConfigMismatch, match="teams"):
        assert_startable(validate(config, tampered, real_draft))


def test_starting_slots_is_the_sum_of_the_starters_not_the_largest_one():
    """Ten starters, of which the largest single position is two. `max` gives 2, `sum` gives 10,
    and the difference is the entire starting lineup."""
    config = load_league_config(ROOT / "config" / "league.yaml")
    assert config.starting_slots == 10
    assert config.starting_slots != max(config.starters.values())


def test_corroboration_blocks_even_a_value_recorded_as_diagnosed_stale(real_league, real_draft):
    """The corroboration branch, isolated. A mutation run found it unreachable.

    Every earlier test reached a block through the *undiagnosed* branch instead, so removing the
    corroboration check entirely left the suite green. The two rules genuinely differ in one
    case: a value that was recorded as diagnosed-stale, and which `roster_positions` has since
    grown to agree with. The diagnosis is stale itself at that point -- two independent API
    fields now say the same thing and our config is the odd one out.

    Roster size is 18 here so that the roster-too-small rule cannot supply the block instead,
    which is how this test would otherwise have passed for the wrong reason as well.
    """
    config = replace(
        load_league_config(ROOT / "config" / "league.yaml"), draft_rounds_api_known_stale=18
    )
    league = _league_with(real_league, rounds_in_roster=18)
    draft = json.loads(json.dumps(real_draft))
    draft["settings"]["rounds"] = 18

    issues = validate(config, league, draft)
    blocking = [i for i in issues if i.severity == Severity.BLOCKING]
    assert [i.field for i in blocking] == ["draft_rounds"], blocking
    assert "corroborated" in blocking[0].source
