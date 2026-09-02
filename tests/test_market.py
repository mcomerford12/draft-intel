"""DI-027 — the market value providers.

Every player used here is discovered from the committed Sleeper fixtures at runtime. Nothing
in this file names a real player, per the charter's rule that no player name, team, ranking or
tier may be hardcoded outside ``config/keepers.yaml``. That is not pedantry in this module in
particular: the code under test resolves names, so a hardcoded name would let a test pass by
agreeing with the fixture it was copied from rather than by exercising the resolution.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from draft_intel.quant.market import (
    AdpMarketValues,
    CsvMarketValues,
    InternalMarketValues,
    MarketValues,
    parse_dollars,
    resolve_market_values,
)
from draft_intel.quant.scoring import PlayerProjection, ProjectionSource

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


@pytest.fixture(scope="module")
def players() -> dict:
    return json.loads((FIXTURES / "players_slim.json").read_text())


def _full_name(record: dict) -> str:
    return f"{record.get('first_name') or ''} {record.get('last_name') or ''}".strip()


@pytest.fixture(scope="module")
def unique_names(players: dict) -> list[tuple[str, str, str]]:
    """``(player_id, name, position)`` for players whose name is unique in the Sleeper map.

    Discovered, never listed. These are the rows that *should* resolve cleanly by name and
    position, so a failure here is the resolver's fault and not the fixture's.
    """
    counts: dict[str, int] = {}
    for record in players.values():
        counts[_full_name(record)] = counts.get(_full_name(record), 0) + 1
    return [
        (pid, _full_name(record), record["position"])
        for pid, record in sorted(players.items())
        if counts[_full_name(record)] == 1
        and record.get("position") in {"QB", "RB", "WR", "TE", "K"}
    ]


@pytest.fixture(scope="module")
def collision(players: dict) -> tuple[str, str, str, str]:
    """A name shared by two players at different positions: ``(name, pos_a, id_a, pos_b)``.

    The hazard this whole resolution path exists for. Found by searching the map rather than
    asserted from memory, so the test keeps working when Sleeper's roster of collisions moves.
    """
    by_name: dict[str, list[dict]] = {}
    for pid, record in sorted(players.items()):
        by_name.setdefault(_full_name(record), []).append({**record, "player_id": pid})
    for name, group in by_name.items():
        positions = {r.get("position") for r in group}
        offensive = [r for r in group if r.get("position") in {"QB", "RB", "WR", "TE"}]
        if len(group) > 1 and len(positions) > 1 and len(offensive) == 1:
            other = next(r for r in group if r is not offensive[0])
            return name, offensive[0]["position"], offensive[0]["player_id"], other["position"]
    pytest.skip("no usable name collision in the fixture")


def proj(player_id: str, name: str, position: str, points: float) -> PlayerProjection:
    return PlayerProjection(
        player_id=player_id,
        name=name,
        position=position,
        points=points,
        projection_source=ProjectionSource.COMPUTED,
        computed_points=points,
    )


# --------------------------------------------------------------------------- parse_dollars


@pytest.mark.parametrize(
    ("raw", "want"),
    [("47", 47.0), ("$47", 47.0), ("47.0", 47.0), ("  47 ", 47.0), ("1,200", 1200.0), ("0", 0.0)],
)
def test_dollar_cells_parse_the_way_a_hand_typed_file_writes_them(raw, want):
    assert parse_dollars(raw) == want


@pytest.mark.parametrize("raw", ["inf", "-inf", "nan", "NaN", "Infinity", "", "  ", "$", "abc"])
def test_non_finite_and_junk_values_raise_rather_than_poisoning_the_sums(raw):
    """``float('inf')`` and ``float('nan')`` both succeed, and both destroy every total.

    This exact hole shipped once already in the ledger's amount parser and made CI fail about
    one run in three. It fails at the cell that carried the bad data, not four modules later.
    """
    with pytest.raises(ValueError):
        parse_dollars(raw)


def test_a_parsed_value_is_always_usable_in_arithmetic():
    assert math.isfinite(parse_dollars("$1,234.56"))


# --------------------------------------------------------------------------- CsvMarketValues


def write_csv(path: Path, rows: list[str], header: str = "name,pos,value") -> Path:
    path.write_text("\n".join([header, *rows]) + "\n")
    return path


def test_a_hand_built_file_resolves_by_name_and_position(tmp_path, players, unique_names):
    picked = unique_names[:5]
    rows = [f"{name},{pos},{10 + i}" for i, (_pid, name, pos) in enumerate(picked)]
    path = write_csv(tmp_path / "auction_values.csv", rows)

    result = CsvMarketValues(path, players).market_values([])

    assert result.source == "csv"
    assert result.unmatched == ()
    assert result.values == {pid: float(10 + i) for i, (pid, _n, _p) in enumerate(picked)}


def test_position_confirmation_attaches_the_value_to_the_right_player(tmp_path, players, collision):
    """The whole reason names are not enough. Two players, one name, different positions."""
    name, offensive_pos, offensive_id, other_pos = collision
    path = write_csv(tmp_path / "v.csv", [f"{name},{offensive_pos},50", f"{name},{other_pos},7"])

    result = CsvMarketValues(path, players).market_values([])

    assert result.values[offensive_id] == 50.0
    assert offensive_id not in {k for k in result.values if result.values[k] == 7.0}


def test_a_row_whose_position_is_wrong_is_reported_not_guessed(tmp_path, players, collision):
    name, offensive_pos, _id, _other = collision
    wrong = "TE" if offensive_pos != "TE" else "QB"
    path = write_csv(tmp_path / "v.csv", [f"{name},{wrong},50"])

    result = CsvMarketValues(path, players).market_values([])

    assert result.values == {}
    assert len(result.unmatched) == 1
    assert name in result.unmatched[0]


def test_a_player_id_column_wins_over_name_resolution(tmp_path, players, collision):
    """The escape hatch for a collision the name and position cannot resolve between them."""
    _name, offensive_pos, offensive_id, _other = collision
    path = write_csv(
        tmp_path / "v.csv",
        [f"not the right name at all,{offensive_pos},{offensive_id},33"],
        header="name,pos,player_id,value",
    )

    result = CsvMarketValues(path, players).market_values([])

    assert result.values == {offensive_id: 33.0}


def test_an_unknown_player_id_is_reported_rather_than_silently_creating_a_player(tmp_path, players):
    path = write_csv(
        tmp_path / "v.csv", ["someone,QB,not-a-real-id,33"], header="name,pos,player_id,value"
    )
    result = CsvMarketValues(path, players).market_values([])
    assert result.values == {}
    assert "not-a-real-id" in result.unmatched[0]


def test_the_shipped_template_reads_cleanly_rather_than_as_forty_broken_rows(
    tmp_path, players, unique_names
):
    """The template documents itself in ``#`` comments. Those must not arrive as failures."""
    pid, name, pos = unique_names[0]
    path = tmp_path / "v.csv"
    path.write_text(
        "\n".join(
            [
                "name,pos,value",
                "# this is a comment and must be skipped",
                "",
                f"{name},{pos},25",
                "   # indented comment",
                "",
            ]
        )
        + "\n"
    )

    result = CsvMarketValues(path, players).market_values([])

    assert result.values == {pid: 25.0}
    assert result.unmatched == ()


def test_reported_line_numbers_point_at_the_users_actual_file_lines(tmp_path, players):
    """A line number that counts post-filter rows is worse than no line number at all."""
    path = tmp_path / "v.csv"
    path.write_text(
        "\n".join(["name,pos,value", "# comment", "# comment", "", "Nobody At All,QB,10"]) + "\n"
    )

    result = CsvMarketValues(path, players).market_values([])

    assert result.unmatched[0].startswith("line 5:"), result.unmatched


@pytest.mark.parametrize("cell", ["", "abc", "inf", "nan"])
def test_an_unreadable_value_is_reported_not_treated_as_zero(tmp_path, players, unique_names, cell):
    _pid, name, pos = unique_names[0]
    path = write_csv(tmp_path / "v.csv", [f"{name},{pos},{cell}"])

    result = CsvMarketValues(path, players).market_values([])

    assert result.values == {}
    assert len(result.unmatched) == 1


def test_a_negative_value_is_rejected(tmp_path, players, unique_names):
    """A negative auction value is not a discount, it is a typo, and it corrupts every sum."""
    _pid, name, pos = unique_names[0]
    path = write_csv(tmp_path / "v.csv", [f"{name},{pos},-5"])

    result = CsvMarketValues(path, players).market_values([])

    assert result.values == {}
    assert "negative" in result.unmatched[0]


def test_a_duplicated_player_takes_the_last_row_and_says_so(tmp_path, players, unique_names):
    pid, name, pos = unique_names[0]
    path = write_csv(tmp_path / "v.csv", [f"{name},{pos},10", f"{name},{pos},40"])

    result = CsvMarketValues(path, players).market_values([])

    assert result.values == {pid: 40.0}
    assert any("duplicate" in note for note in result.notes)


def test_a_missing_file_is_a_note_not_an_exception(tmp_path, players):
    """The file is optional. Its absence is the normal state until draft morning."""
    result = CsvMarketValues(tmp_path / "nope.csv", players).market_values([])
    assert result.values == {}
    assert "no auction-value file" in result.notes[0]


def test_a_file_with_no_value_column_names_the_columns_it_did_find(tmp_path, players):
    path = write_csv(tmp_path / "v.csv", ["a,b"], header="name,pos")
    result = CsvMarketValues(path, players).market_values([])
    assert result.values == {}
    assert "no value column" in result.notes[0]
    assert "name, pos" in result.notes[0]


def test_a_file_with_a_value_column_but_no_way_to_identify_a_player_says_so(tmp_path, players):
    path = write_csv(tmp_path / "v.csv", ["47"], header="value")
    result = CsvMarketValues(path, players).market_values([])
    assert result.values == {}
    assert "player_id column" in result.notes[0]


@pytest.mark.parametrize(
    "header",
    ["Player,Position,Auction", "PLAYER_NAME,POS,$", "name,position,cost", "  Name , Pos , Price "],
)
def test_column_names_are_matched_across_synonyms_and_case(tmp_path, players, unique_names, header):
    """An export from somewhere else should work without the user renaming headers by hand."""
    pid, name, pos = unique_names[0]
    path = write_csv(tmp_path / "v.csv", [f"{name},{pos},17"], header=header)
    assert CsvMarketValues(path, players).market_values([]).values == {pid: 17.0}


# --------------------------------------------------------------------------- AdpMarketValues


def test_rank_transfer_preserves_the_ladder_exactly():
    """The sum invariant holds by construction: the same dollars, reassigned."""
    ladder = [50.0, 30.0, 20.0, 10.0]
    payload = [
        {"player_id": "a", "stats": {"adp_2qb": 4.0}},
        {"player_id": "b", "stats": {"adp_2qb": 1.0}},
        {"player_id": "c", "stats": {"adp_2qb": 3.0}},
        {"player_id": "d", "stats": {"adp_2qb": 2.0}},
    ]
    players = [proj(pid, pid.upper(), "RB", 100.0) for pid in "abcd"]

    result = AdpMarketValues(payload, ladder).market_values(players)

    assert sorted(result.values.values(), reverse=True) == ladder
    assert result.total == sum(ladder)


def test_the_ordering_comes_from_adp_and_not_from_our_points():
    """If it followed points it would be our own model wearing a market's coat."""
    ladder = [50.0, 10.0]
    payload = [
        {"player_id": "cheap_but_early", "stats": {"adp_2qb": 1.0}},
        {"player_id": "good_but_late", "stats": {"adp_2qb": 99.0}},
    ]
    players = [proj("cheap_but_early", "A", "RB", 10.0), proj("good_but_late", "B", "RB", 300.0)]

    result = AdpMarketValues(payload, ladder).market_values(players)

    assert result.values["cheap_but_early"] == 50.0
    assert result.values["good_but_late"] == 10.0


def test_the_undrafted_sentinel_is_absence_of_an_opinion_not_a_very_late_pick():
    """ADP feeds write 999 for "nobody is taking this player". Ranking it would be a lie."""
    ladder = [50.0, 30.0]
    payload = [
        {"player_id": "a", "stats": {"adp_2qb": 5.0}},
        {"player_id": "b", "stats": {"adp_2qb": 999.0}},
        {"player_id": "c", "stats": {"adp_2qb": 7.0}},
    ]
    players = [proj(pid, pid.upper(), "RB", 100.0) for pid in "abc"]

    result = AdpMarketValues(payload, ladder).market_values(players)

    assert "b" not in result.values
    assert set(result.values) == {"a", "c"}
    assert any("no usable adp_2qb" in note for note in result.notes)


def test_players_outside_the_priced_set_are_not_ranked():
    ladder = [50.0, 30.0]
    payload = [
        {"player_id": "a", "stats": {"adp_2qb": 1.0}},
        {"player_id": "stranger", "stats": {"adp_2qb": 2.0}},
    ]
    result = AdpMarketValues(payload, ladder).market_values([proj("a", "A", "RB", 1.0)])
    assert set(result.values) == {"a"}


def test_a_ladder_shorter_than_the_field_prices_only_the_top_of_the_market():
    ladder = [50.0]
    payload = [{"player_id": pid, "stats": {"adp_2qb": i}} for i, pid in enumerate("abc", start=1)]
    players = [proj(pid, pid.upper(), "RB", 1.0) for pid in "abc"]
    result = AdpMarketValues(payload, ladder).market_values(players)
    assert result.values == {"a": 50.0}


def test_a_boolean_adp_is_not_treated_as_a_number():
    """``isinstance(True, int)`` is True in Python, and a True ADP would rank first."""
    payload = [{"player_id": "a", "stats": {"adp_2qb": True}}]
    result = AdpMarketValues(payload, [50.0]).market_values([proj("a", "A", "RB", 1.0)])
    assert result.values == {}


# ------------------------------------------------------------------- InternalMarketValues


def test_the_internal_provider_is_labelled_an_estimate_and_the_csv_is_not():
    """A board priced off our own model must never be presented as a market observation."""
    assert InternalMarketValues({"a": 1.0}).market_values([proj("a", "A", "RB", 1.0)]).is_estimate
    assert MarketValues(source="csv", values={}).is_estimate is False
    assert AdpMarketValues([], []).market_values([]).is_estimate


def test_the_internal_provider_only_reports_players_it_was_asked_about():
    provider = InternalMarketValues({"a": 5.0, "b": 6.0})
    assert provider.market_values([proj("a", "A", "RB", 1.0)]).values == {"a": 5.0}


# --------------------------------------------------------------------- resolve_market_values


def test_real_auction_values_beat_every_fallback(tmp_path, players, unique_names):
    picked = unique_names[:4]
    path = write_csv(
        tmp_path / "v.csv", [f"{name},{pos},{20 + i}" for i, (_p, name, pos) in enumerate(picked)]
    )
    projections = [proj(pid, name, pos, 100.0) for pid, name, pos in picked]

    result = resolve_market_values(
        [
            CsvMarketValues(path, players),
            InternalMarketValues(dict.fromkeys((p.player_id for p in projections), 99.0)),
        ],
        projections,
        required=4,
    )

    assert result.source == "csv"
    assert result.is_estimate is False


def test_a_thin_file_falls_through_and_the_reason_travels_with_the_winner(
    tmp_path, players, unique_names
):
    """Twelve good rows are not a market opinion about a 160-player board."""
    pid, name, pos = unique_names[0]
    path = write_csv(tmp_path / "v.csv", [f"{name},{pos},20"])
    projections = [proj(p, n, ps, 100.0) for p, n, ps in unique_names[:10]]

    result = resolve_market_values(
        [
            CsvMarketValues(path, players),
            InternalMarketValues(dict.fromkeys((p.player_id for p in projections), 99.0)),
        ],
        projections,
        required=10,
    )

    assert result.source == "internal_model"
    assert any("skipped csv" in note and "covered 1 of 10" in note for note in result.notes)
    assert pid not in result.notes  # the reason, not the data, is what carries over


def test_coverage_is_judged_against_the_priced_pool_not_the_players_supplied(
    tmp_path, players, unique_names
):
    """Ten complete rows out of ten supplied is still nothing against a 160-spot auction."""
    projections = [proj(p, n, ps, 100.0) for p, n, ps in unique_names[:10]]
    provider = InternalMarketValues(dict.fromkeys((p.player_id for p in projections), 5.0))

    assert resolve_market_values([provider], projections, required=10).source == "internal_model"
    assert resolve_market_values([provider], projections, required=160).source == "none"


def test_when_everything_falls_short_no_values_are_returned_at_all():
    """Pricing off the weakest source's scraps is worse than saying there is nothing."""
    result = resolve_market_values(
        [InternalMarketValues({"a": 1.0})], [proj("a", "A", "RB", 1.0)], required=100
    )
    assert result.source == "none"
    assert result.values == {}
    assert any("no provider covered" in note for note in result.notes)


def test_calling_with_no_providers_is_a_programming_error():
    with pytest.raises(ValueError, match="no market value providers"):
        resolve_market_values([], [], required=1)


# ------------------------------------------------------------------------------- scaled_to


def test_rescaling_hits_the_target_total():
    scaled = MarketValues(source="csv", values={"a": 100.0, "b": 300.0}).scaled_to(200.0)
    assert scaled.total == 200.0
    assert scaled.values == {"a": 50.0, "b": 150.0}


def test_rescaling_records_the_factor_so_the_original_is_recoverable():
    scaled = MarketValues(source="csv", values={"a": 100.0}).scaled_to(50.0)
    assert any("rescaled by 0.5000" in note for note in scaled.notes)


def test_rescaling_nothing_is_an_error_rather_than_a_division_by_zero():
    with pytest.raises(ValueError, match="sum to 0"):
        MarketValues(source="csv", values={"a": 0.0}).scaled_to(100.0)


# ------------------------------------------------------ the reason this module exists at all


def test_supplied_auction_values_make_the_league_keeper_rule_computable(
    tmp_path, players, unique_names
):
    """``floor(0.75 * auction_value)`` is the league's actual rule and needs a real value.

    The commissioner has confirmed the 75% rule will be applied on draft day. Sleeper publishes
    no auction value (Finding 3), so without this file every keeper price is a guess. With it,
    the retention price is arithmetic.
    """
    from draft_intel.domain.keepers import retention_price

    pid, name, pos = unique_names[0]
    path = write_csv(tmp_path / "v.csv", [f"{name},{pos},$47"])

    values = CsvMarketValues(path, players).market_values([])

    assert retention_price(int(values.values[pid])) == 35  # floor(0.75 * 47)


def test_the_clamp_keeps_a_dollar_player_from_becoming_a_free_one(tmp_path, players, unique_names):
    """floor(0.75 * 1) == 0, and a $0 pick breaks money conservation and the max-bid reserve."""
    from draft_intel.domain.keepers import retention_price

    pid, name, pos = unique_names[0]
    path = write_csv(tmp_path / "v.csv", [f"{name},{pos},1"])
    values = CsvMarketValues(path, players).market_values([])
    assert retention_price(int(values.values[pid])) == 1
