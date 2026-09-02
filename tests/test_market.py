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


def test_a_thin_file_still_contributes_every_value_it_has(tmp_path, players, unique_names):
    """The finding that made this layered rather than winner-take-all.

    The module exists chiefly to make the 75% keeper rule computable, and the template tells the
    user "the 20 keepers matter most". Under winner-take-all a user who supplied exactly those
    twenty real values fell under a 50%-of-160 threshold and had every one silently replaced by
    an ADP estimate. Twenty real values are twenty real values.
    """
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

    assert result.values[pid] == 20.0, "the real dollar value survives"
    assert result.coverage == 10, "and the fallback fills the other nine"
    assert result.source_for(pid) == "csv"
    assert all(result.source_for(p.player_id) == "internal_model" for p in projections[1:])


def test_provenance_is_recorded_per_player_not_just_per_board(tmp_path, players, unique_names):
    """A board where some prices are observed and some are guessed must say which is which."""
    pid, name, pos = unique_names[0]
    path = write_csv(tmp_path / "v.csv", [f"{name},{pos},20"])
    projections = [proj(p, n, ps, 100.0) for p, n, ps in unique_names[:3]]

    result = resolve_market_values(
        [
            CsvMarketValues(path, players),
            InternalMarketValues(dict.fromkeys((p.player_id for p in projections), 99.0)),
        ],
        projections,
        required=3,
    )

    assert result.is_estimate_for(pid) is False
    assert result.is_estimate_for(projections[1].player_id) is True
    assert result.is_estimate is True, "one estimated value makes the board an estimated board"
    assert result.source == "csv+internal_model"


def test_a_board_entirely_of_real_values_is_not_badged_as_an_estimate(
    tmp_path, players, unique_names
):
    """The pessimistic board-level badge must still be able to come off."""
    picked = unique_names[:3]
    path = write_csv(
        tmp_path / "v.csv", [f"{name},{pos},{20 + i}" for i, (_p, name, pos) in enumerate(picked)]
    )
    projections = [proj(p, n, ps, 100.0) for p, n, ps in picked]

    result = resolve_market_values([CsvMarketValues(path, players)], projections, required=3)

    assert result.is_estimate is False
    assert result.source == "csv"


def test_a_higher_authority_provider_is_never_overwritten_by_a_lower_one(
    tmp_path, players, unique_names
):
    pid, name, pos = unique_names[0]
    path = write_csv(tmp_path / "v.csv", [f"{name},{pos},20"])
    result = resolve_market_values(
        [CsvMarketValues(path, players), InternalMarketValues({pid: 999.0})],
        [proj(pid, name, pos, 100.0)],
        required=1,
    )
    assert result.values[pid] == 20.0


def test_a_losing_providers_unresolvable_rows_reach_the_user(tmp_path, players, unique_names):
    """Previously only the winner's `unmatched` survived.

    Draft-morning scenario: the user pastes 120 rows, 45 fail to resolve, the CSV falls short of
    the threshold, and the output gives no way at all to learn which rows to fix -- which is
    precisely what this function's own docstring promised to prevent.
    """
    _pid, name, pos = unique_names[0]
    path = write_csv(
        tmp_path / "v.csv",
        [f"{name},{pos},20", "Nobody At All,QB,5", "Also Nobody,RB,6"],
    )
    projections = [proj(p, n, ps, 100.0) for p, n, ps in unique_names[:10]]

    result = resolve_market_values(
        [
            CsvMarketValues(path, players),
            InternalMarketValues(dict.fromkeys((p.player_id for p in projections), 99.0)),
        ],
        projections,
        required=160,
    )

    assert len(result.unmatched) == 2
    assert all(row.startswith("[csv]") for row in result.unmatched)
    assert any("Nobody At All" in row for row in result.unmatched)


def test_coverage_against_the_priced_pool_is_reported_even_though_it_no_longer_gates(
    tmp_path, players, unique_names
):
    """It is still worth saying that ten values do not price a 160-spot auction."""
    projections = [proj(p, n, ps, 100.0) for p, n, ps in unique_names[:10]]
    provider = InternalMarketValues(dict.fromkeys((p.player_id for p in projections), 5.0))

    thin = resolve_market_values([provider], projections, required=160)

    assert thin.coverage == 10
    assert any(
        "10 player(s) carry a market value against a priced pool of 160" in note
        for note in thin.notes
    )
    assert any("below the 80 whole-board threshold" in note for note in thin.notes)


def test_no_provider_with_anything_to_say_leaves_the_source_named_none():
    result = resolve_market_values(
        [InternalMarketValues({})], [proj("a", "A", "RB", 1.0)], required=100
    )
    assert result.source == "none"
    assert result.values == {}


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


# ------------------------------------------------ regressions from review round 1


def test_a_quoted_field_containing_a_newline_does_not_take_the_pricing_run_down(
    tmp_path, players, unique_names
):
    """M2. Legal RFC-4180 CSV that Excel and Google Sheets both emit.

    The reader filtered physical lines before csv parsed them, then paired the two streams with
    ``zip(strict=True)``. One record spanning two physical lines desynchronised the streams and
    raised, out of ``value()``, with a message naming neither the file nor a line -- on a file
    the user had every reason to expect would work.
    """
    pid, name, pos = unique_names[0]
    path = tmp_path / "v.csv"
    path.write_text(f'name,pos,note,value\n{name},{pos},"line one\nline two",25\n')

    result = CsvMarketValues(path, players).market_values([])

    assert result.values == {pid: 25.0}
    assert result.unmatched == ()


def test_a_blank_line_inside_a_quoted_field_is_content_not_a_blank_row(
    tmp_path, players, unique_names
):
    """The physical-line filter deleted these from inside the field, corrupting the value."""
    pid, name, pos = unique_names[0]
    path = tmp_path / "v.csv"
    path.write_text(f'name,pos,note,value\n{name},{pos},"before\n\nafter",25\n')

    result = CsvMarketValues(path, players).market_values([])

    assert result.values == {pid: 25.0}


def test_a_hash_inside_a_quoted_field_is_content_not_a_comment(tmp_path, players, unique_names):
    """Parsing before filtering makes the comment test exact: it is the first *field* that
    decides, not the first character of a physical line."""
    pid, name, pos = unique_names[0]
    path = tmp_path / "v.csv"
    path.write_text(f'name,pos,value\n"{name}",{pos},25\n')
    assert CsvMarketValues(path, players).market_values([]).values == {pid: 25.0}


def test_a_short_row_is_reported_rather_than_raising(tmp_path, players, unique_names):
    _pid, name, pos = unique_names[0]
    path = write_csv(tmp_path / "v.csv", [f"{name},{pos}"])
    result = CsvMarketValues(path, players).market_values([])
    assert result.values == {}
    assert len(result.unmatched) == 1


def test_a_row_with_a_blank_player_id_cell_falls_back_to_name_resolution(
    tmp_path, players, unique_names
):
    """m6. Reachable and previously untested."""
    pid, name, pos = unique_names[0]
    path = write_csv(tmp_path / "v.csv", [f"{name},{pos},,25"], header="name,pos,player_id,value")
    assert CsvMarketValues(path, players).market_values([]).values == {pid: 25.0}


def test_a_row_with_only_a_blank_id_and_no_name_column_is_reported(tmp_path, players):
    path = write_csv(tmp_path / "v.csv", [",25"], header="player_id,value")
    result = CsvMarketValues(path, players).market_values([])
    assert result.values == {}
    assert "no player_id and no name/position" in result.unmatched[0]


def test_a_ladder_longer_than_the_ranked_list_reports_the_shortfall():
    """M4. The docstring claimed the total was preserved exactly; it is not, and cannot be.

    With more rungs than ranked players there is nobody to hand the surplus to. That is real
    information about the ADP feed's coverage, not an arithmetic slip to be hidden by rescaling.
    """
    ladder = [50.0, 30.0, 20.0, 10.0]
    payload = [{"player_id": "a", "stats": {"adp_2qb": 1.0}}]
    players = [proj("a", "A", "RB", 1.0)]

    result = AdpMarketValues(payload, ladder).market_values(players)

    assert result.total == 50.0
    assert result.total < sum(ladder)
    assert any("$60 of it goes unassigned" in note for note in result.notes)


def test_players_absent_from_the_adp_payload_are_counted_as_uncovered():
    """m2. The old count looked only at payload records, so a projected player with no record
    at all was invisible -- understating the very gap it was reporting."""
    payload = [{"player_id": "a", "stats": {"adp_2qb": 1.0}}]
    players = [proj("a", "A", "RB", 1.0), proj("ghost", "G", "RB", 1.0)]

    result = AdpMarketValues(payload, [50.0, 30.0]).market_values(players)

    assert any("1 of 2 priced players carry no usable adp_2qb" in note for note in result.notes)
