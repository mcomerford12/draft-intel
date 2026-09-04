"""DI-039 — the tier sheet and the `make prep` report. The Sprint 2 gate.

The report test runs the whole pipeline against the real fixtures, which is the point: a
section that renders from synthetic data and falls over on the real board is not a gate.

No player name is hardcoded. The report's own content is asserted structurally.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from draft_intel.prep import build_report, main
from draft_intel.quant.tiers import BREAK_MULTIPLE, MIN_TIER_SAMPLE, tier_sheet

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------- tier sheet


def rows(position: str, *values: float) -> list[tuple[str, str, str, float]]:
    return [(f"{position}{i}", f"{position}-{i}", position, v) for i, v in enumerate(values)]


def test_a_clear_cliff_is_found_as_a_tier_break():
    """Four players around $40, then a drop to $10. The break is where the money is."""
    sheet = tier_sheet(rows("RB", 42, 41, 40, 39, 10, 9, 8, 7))
    tiers = sheet["RB"]
    assert len(tiers) == 2
    assert tiers[0].size == 4
    assert tiers[0].gap_below == 29.0
    assert tiers[1].size == 4


def test_an_evenly_spaced_position_is_one_tier():
    """No gap stands out, so declaring breaks would be inventing structure."""
    sheet = tier_sheet(rows("WR", *[float(40 - i) for i in range(12)]))
    assert len(sheet["WR"]) == 1


def test_the_threshold_is_relative_so_a_cheap_position_is_not_shredded():
    """A $4 gap is a chasm among $8 tight ends and noise among $40 running backs. A fixed
    dollar cutoff carves one position into slivers and calls the other a single tier."""
    expensive = tier_sheet(rows("RB", 60, 56, 52, 48, 44, 40, 36, 32))
    cheap = tier_sheet(rows("TE", 15, 14, 13, 12, 11, 10, 9, 8))
    assert len(expensive["RB"]) == len(cheap["TE"]) == 1, "both evenly spaced, both one tier"


def test_the_median_is_used_rather_than_the_mean():
    """The gap below the best player at a position is routinely several times every other gap.
    A mean drags the threshold up until nothing else qualifies -- including the real cliff."""
    # One huge gap at the top, then a genuine cliff further down.
    sheet = tier_sheet(rows("RB", 90, 40, 39, 38, 37, 12, 11, 10))
    assert len(sheet["RB"]) >= 3, "both the top gap and the lower cliff are found"


def test_a_position_too_thin_to_measure_is_one_tier_rather_than_omitted():
    """A kicker list is still a list the user reads."""
    sheet = tier_sheet(rows("K", 5, 4, 1))
    assert len(sheet["K"]) == 1
    assert sheet["K"][0].size == 3


def test_the_sample_floor_suppresses_a_break_a_thin_board_would_otherwise_declare():
    """The version above cannot see the floor working: its gaps fall under the threshold anyway,
    so removing the `min_sample` guard entirely left it passing. Four players, three gaps, and
    the last one is sixteen times the median -- a "cliff" measured against a distribution of two
    numbers. Below the floor the honest answer is one tier, because there is nothing to call
    that gap unusual against."""
    thin = rows("K", 20, 19, 18, 2)
    assert len(tier_sheet(thin)["K"]) == 1, "four players: no distribution, no breaks"
    # The same board with the floor lowered does find the break, so the gap is genuinely
    # break-sized and this test is measuring the floor rather than the threshold.
    assert len(tier_sheet(thin, min_sample=3)["K"]) == 2


def test_a_position_where_every_player_costs_the_same_is_one_tier():
    """Every gap is zero, so there is no distribution to call anything unusual against."""
    sheet = tier_sheet(rows("K", *[1.0] * MIN_TIER_SAMPLE))
    assert len(sheet["K"]) == 1


def test_players_are_ordered_by_value_within_a_tier():
    sheet = tier_sheet(rows("RB", 10, 40, 20, 30, 39, 38, 37, 36))
    values = [value for _pid, _name, value in sheet["RB"][0].players]
    assert values == sorted(values, reverse=True)


def test_a_larger_break_multiple_finds_fewer_tiers():
    """The knob does what it says, which is worth pinning before anybody tunes it."""
    board = rows("RB", 90, 40, 39, 38, 37, 12, 11, 10)
    assert len(tier_sheet(board, break_multiple=1.5)["RB"]) >= len(
        tier_sheet(board, break_multiple=BREAK_MULTIPLE * 4)["RB"]
    )


# ------------------------------------------------------- the report, end to end


@pytest.fixture(scope="module")
def report() -> str:
    """The whole pipeline against the real fixtures. Slow on purpose: this is the gate."""
    return build_report(ROOT, targets=2)


def test_every_charter_section_is_present(report: str) -> None:
    """§4.9 lists seven deliverables. All seven render."""
    for heading in (
        "1. THE PRICED BOARD",
        "2. STRUCTURAL KEEPER INFLATION",
        "3. KEEPER SURPLUS BOARD",
        "4. POSITIONAL MARKET MAP",
        "5. TIER SHEET",
        "6. BUDGET SCENARIOS",
        "7. TARGET LIST",
    ):
        assert heading in report, f"missing section: {heading}"


def test_the_percentile_deviation_is_stated_in_the_report_itself(report: str) -> None:
    """§4.9 item 1 asks for p25/p50/p75. Those labels imply a sampling distribution, and the
    500-run Monte Carlo that would produce one is Sprint 3. The report says so where the user
    reads it, not only in a docstring they never will."""
    assert "NOT p25/p50/p75" in report
    assert "Monte Carlo" in report


def test_both_keeper_scenarios_are_reported(report: str) -> None:
    """Prices as loaded and prices under the 75% rule are different auctions, and presenting
    one without the other is how a draft gets bid at the wrong level all night."""
    assert "prices under the 75% rule" in report
    assert "prices as loaded" in report


def test_the_estimate_badge_survives_all_the_way_to_the_page(report: str) -> None:
    """No auction values file is present in the repo, so every rule-implied figure is an
    estimate and the page has to say it."""
    assert "ESTIMATE" in report
    assert "auction_values.csv" in report


def test_the_config_tripwire_runs_before_anything_is_priced(report: str) -> None:
    """The known-stale draft settings are surfaced above the board, not buried."""
    header = report.split("2. STRUCTURAL")[0]
    assert "draft.rounds" in header
    assert "auction pool" in header


def test_the_target_list_is_not_all_quarterbacks(report: str) -> None:
    """Ranking the precompute by raw points returned twelve quarterbacks and nothing else,
    because in a 2QB league a QB outscores every running back on the board. VORP is measured
    against each position's own replacement level, which is the axis that makes the list mean
    "worth bidding on" rather than "scores most".

    Asserted here on the real board because that is where the defect appeared. That the ranking
    genuinely spans positions is pinned separately and cheaply by
    ``test_the_precompute_ranks_by_vorp_not_raw_points``; this test runs on a short list.
    """
    section = report.split("7. TARGET LIST")[1].split("OPPONENT AFFORDABILITY")[0]
    positions = {
        line.split()[-4] for line in section.splitlines() if line.startswith("  ") and "$" in line
    } & {"QB", "RB", "WR", "TE", "K"}
    assert positions
    assert positions != {"QB"}


def test_no_walk_away_curve_on_the_real_board_is_broken(report: str) -> None:
    """A non-monotone curve means the optimizer is not returning optima, and every walk-away
    number in the report would be meaningless."""
    assert "BROKEN" not in report


def test_the_report_writes_a_file_as_well_as_printing(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "prep.txt"
    assert main(ROOT, destination, targets=1) == 0
    assert destination.exists()
    assert "DRAFT INTELLIGENCE" in destination.read_text()


# ------------------------------ review round 2: provenance, derivation, and the band


def test_retention_prices_prefer_the_manifest_over_the_mock_draft(report: str) -> None:
    """B1. Every price came from `fixtures/picks.json` -- a *mock draft* -- rendered as "prices
    as loaded" with per-team paid columns and named per-keeper alerts, as though it described
    this league. Setting a manifest price to commissioner authority changed nothing.

    The manifest is now consulted first, and when it cannot supply every price the report says
    whose numbers it is showing instead.
    """
    assert "KEEPER PRICE PROVENANCE" in report
    assert "the MOCK draft's picks feed -- NOT this league" in report
    assert "DIFFERENT DRAFT'S RESULTS" in report


def test_a_manifest_price_wins_over_the_mock(tmp_path: Path) -> None:
    """The authority order from `config/keepers.yaml`, exercised end to end."""
    import shutil

    root = tmp_path / "repo"
    shutil.copytree(ROOT / "config", root / "config")
    shutil.copytree(ROOT / "fixtures", root / "fixtures")

    manifest = root / "config" / "keepers.yaml"
    text = manifest.read_text()
    marker = '{name: "Josh Allen",          pos: QB, player_id: null, price: null'
    assert marker in text, "manifest layout changed; this test pins a real substitution"
    manifest.write_text(
        text.replace(
            marker,
            '{name: "Josh Allen",          pos: QB, player_id: null, price: 10',
        ).replace("price: 10, price_source: null}", "price: 10, price_source: commissioner}", 1)
    )

    report = build_report(root, targets=1)

    assert "MIXED: 1 from config/keepers.yaml" in report
    assert "loaded at $39" not in report, "the mock's figure must no longer win"


def test_the_priced_board_names_which_scenario_each_column_prices(report: str) -> None:
    """M2. The old band sorted the two inflations into low/high and always rendered upward from
    the live price, which is correct only while keepers happen to be loaded *above* the 75%
    rule. Flip that -- the charter's own keeper thesis -- and the true alternate price fell
    outside the band, on the opposite side, under a byte-identical label."""
    section = report.split("1. THE PRICED BOARD")[1].split("5. TIER SHEET")[0]
    assert "AS-LOADED scenario" in section
    assert "rule $" in section
    assert "NOT p25/p50/p75" in section
    assert "low" not in section.split("book $")[0].split("\n")[-2], "no unsigned low/high band"


def test_the_report_derives_the_users_seat_and_keeper_spend(report: str) -> None:
    """M4. An earlier version hardcoded a $55 keeper spend that was another manager's figure,
    and the report contradicted its own surplus board by $7 four screens earlier."""
    keeper_row = next(
        line for line in report.splitlines() if line.startswith("  Me ") and "$" not in line
    )
    paid = int(keeper_row.split()[-3])
    assert f"after your ${paid} of keepers" in report
    assert f"From ${200 - paid} across 14 slots" in report


def test_effective_buying_power_divides_by_the_league_not_by_keeper_holders(report: str) -> None:
    """m1. Dividing by the teams that happen to hold keepers inflated every other team by $22
    the moment one team kept nobody -- which `max_keepers: 1` makes entirely possible."""
    section = report.split("3. KEEPER SURPLUS BOARD")[1].split("4. POSITIONAL")[0]
    rows = [line for line in section.splitlines() if line.startswith("  ") and line.split()[1:]]
    powers = [int(line.split()[-1]) for line in rows if line.split()[-1].lstrip("-").isdigit()]
    assert powers
    # $200/team is the divisor; no row can exceed budget + its own surplus.
    assert max(powers) < 250


def test_the_positional_map_allocates_every_flex_slot(report: str) -> None:
    """m2. An even three-way split with a floor discarded 2 of 20 FLEX slots, so the need column
    summed to 78 while the line two rows below printed 80 -- the same page, both numbers."""
    section = report.split("4. POSITIONAL MARKET MAP")[1].split("1. THE PRICED BOARD")[0]
    needs = [
        int(line.split()[2])
        for line in section.splitlines()
        if line.startswith("  ")
        and len(line.split()) >= 3
        and line.split()[0] in {"QB", "RB", "WR", "TE", "K"}
    ]
    stated = int(section.split("starting slots and")[0].split()[-1])
    assert sum(needs) == stated, f"need column sums to {sum(needs)}, page states {stated}"


def test_the_budget_scenarios_vary_the_allocation_not_just_the_budget(report: str) -> None:
    """§4.9's question is "if I spend $75 on two QBs, what does the rest look like" -- an
    allocation. An earlier version varied one keeper-cost scalar and printed three rows with
    the identical shape, which answers a different question."""
    section = report.split("6. BUDGET SCENARIOS")[1].split("7. TARGET LIST")[0]
    assert "no pre-commitment" in section
    assert "two QBs at the top" in section
    assert "(-" in section or "(+" in section, "the cost of pre-committing is shown"


# ------------- evaluation round 2: the report's own arithmetic, not just its section headings


def test_the_page_reconciles_its_own_pool_arithmetic_against_the_config(report: str) -> None:
    """97% line coverage, ~8% mutation coverage. `roster_live = roster_full` -- deleting the
    keeper subtraction outright -- left every test green while the page printed 160 roster spots
    against a 20-keeper league and re-priced the top asset by $4.59. Line coverage measures which
    statements ran, not which numbers were checked, and nothing here was checking the numbers.

    Derived from `config/league.yaml` and the manifest, so the assertion tracks the config
    instead of pinning a figure that a settings change would falsify.
    """
    from draft_intel.config import load_league_config
    from draft_intel.domain.keepers import load_manifest

    config = load_league_config(ROOT / "config" / "league.yaml")
    kept = len(load_manifest(ROOT / "config" / "keepers.yaml").entries)

    line = next(line for line in report.splitlines() if "roster spots remain" in line)
    starting_slots, roster_spots = (int(w) for w in line.split() if w.isdigit())

    assert roster_spots == config.auction_pool - kept, (
        "roster spots remaining is the auction pool less the players already kept"
    )
    assert starting_slots == sum(config.starters.values()) * config.teams - kept, (
        "a kept player is already sitting in a starting slot; that slot is not still open"
    )
    assert roster_spots < config.auction_pool, "the subtraction has to actually happen"


def test_the_positional_need_column_sums_to_the_starting_slots_the_page_states(
    report: str,
) -> None:
    """The same class of check one line further on: the map's own column against the map's own
    total. `seat_keepers({})` -- ignoring which positions the keepers occupy -- printed 100
    starting slots against a true 80, and no test compared the two."""
    section = report.split("4. POSITIONAL MARKET MAP")[1].split("1. THE PRICED BOARD")[0]
    stated = int(section.split("starting slots and")[0].split()[-1])
    needs = [
        int(line.split()[2])
        for line in section.splitlines()
        if line.startswith("  ")
        and len(line.split()) >= 3
        and line.split()[0] in {"QB", "RB", "WR", "TE", "K"}
    ]
    assert needs and sum(needs) == stated


def test_the_as_loaded_scenario_reports_the_money_actually_paid_for_the_keepers(
    report: str,
) -> None:
    """`keeper_spend = 0` -- deleting the sum outright -- passed the whole suite. Every existing
    assertion about the figure read it back off the report and checked it against itself, which
    is satisfied by any number including zero.

    Checked here against the picks feed the report sources it from, and against the league's own
    money identity: what the keepers cost plus what is left to bid must be the whole pot.
    """
    import json

    from draft_intel.config import load_league_config
    from draft_intel.domain.keepers import load_manifest, resolve_manifest

    config = load_league_config(ROOT / "config" / "league.yaml")
    players = json.loads((ROOT / "fixtures" / "players_slim.json").read_text())
    resolved = resolve_manifest(load_manifest(ROOT / "config" / "keepers.yaml"), players)
    kept = {pid for _owner, pid in resolved}
    picks = json.loads((ROOT / "fixtures" / "picks.json").read_text())
    paid = sum(int(p["metadata"]["amount"]) for p in picks if p["player_id"] in kept)

    assert paid > 0, "the fixture must actually contain keeper money for this to test anything"

    # Two scenarios print this line; the as-loaded one is the mock's own money.
    scenarios = {
        int(line.split("SK $")[1].split(",")[0]): int(line.split("live money $")[1].split(",")[0])
        for line in report.splitlines()
        if "SK $" in line and "live money" in line
    }
    assert paid in scenarios, f"no scenario reports the ${paid} actually paid; saw {scenarios}"
    assert scenarios[paid] == config.teams * config.budget - paid, (
        "money left to bid is the pot less what the keepers cost"
    )
    assert all(v > 0 for v in scenarios.values())


def test_the_board_reconciles_the_talent_it_prices_against_the_money_in_the_room(
    report: str,
) -> None:
    """Every price on this page scales with live money, and nothing was checking that it did.
    Deleting the keeper-spend sum outright moved the top asset $26.60 -> $37.32 and re-priced all
    140 players by 40%, with the whole suite green: 97% line coverage measures which statements
    ran, not which numbers were checked.

    The identity is the one an auction has to satisfy -- the board prices exactly the money that
    will be spent on it -- so it is now printed where the user can check it by eye too.
    """
    from draft_intel.config import load_league_config

    config = load_league_config(ROOT / "config" / "league.yaml")
    line = next(line for line in report.splitlines() if "Reconciles:" in line)
    priced, live, pot, keepers = (
        int(word.strip("(),.").lstrip("$").replace(",", ""))
        for word in line.split()
        if word.strip("(").startswith("$")
    )
    assert pot == config.teams * config.budget
    assert live == pot - keepers
    assert keepers > 0, "the keepers cost real money; zero means the sum was not taken"
    assert abs(priced - live) <= 1, f"board prices ${priced} against ${live} of live money"


def test_the_surplus_board_shows_both_value_bases_it_mixes(report: str) -> None:
    """Section 3 printed `book 50` two lines above `rule implies $27` for the same player, and
    the two came from different sources: `book` is this model's full-market valuation, which is
    what §4.3 defines surplus against, while the 75% rule is written against Sleeper's auction
    value and so is applied to the market *provider's* consensus.

    Both are correct in their own terms and neither could be derived from the other by anyone
    reading the page, which is the defect. Both bases are now printed and labelled.
    """
    section = report.split("3. KEEPER SURPLUS BOARD")[1].split("4. POSITIONAL")[0]
    assert "this model's full-market value" in section
    assert "market provider's consensus" in section

    header = next(line for line in section.splitlines() if "surplus" in line and "paid" in line)
    columns = header.split()
    assert columns.index("book") < columns.index("mkt") < columns.index("paid")

    rows = [
        line.split()
        for line in section.splitlines()
        if line.startswith("  ") and len(line.split()) >= 7 and line.split()[-1].isdigit()
    ]
    assert rows, "no team rows parsed"
    for row in rows:
        book, mkt, paid, surplus = (
            float(row[-5]),
            float(row[-4]),
            int(row[-3]),
            int(row[-2]),
        )
        assert surplus == round(book - paid), "surplus is book less paid, on the book basis"
        assert mkt > 0, "the consensus basis is populated, not a blank column"


def test_the_page_states_how_many_keepers_actually_resolved(report: str) -> None:
    """ADR-0006 clause 1. The gate says "priced against the real keeper manifest"; this line is
    what stops that quietly becoming "priced against as much of it as happened to resolve".

    The board is built from the manifest either way. What changes with an unresolved keeper is
    that the tool cannot tell which team holds them — which silently moves both the demand and
    the surplus for that seat, with the page looking identical.
    """
    from draft_intel.config import load_league_config

    config = load_league_config(ROOT / "config" / "league.yaml")
    expected = config.teams * config.keepers_per_team

    line = next(line for line in report.splitlines() if "keepers resolved" in line)
    resolved, of_total = (int(word) for word in line.split() if word.isdigit())
    assert of_total == expected, "the denominator is the league's own keeper count"
    assert resolved == expected, "against the fixture all twenty resolve"
    assert "INCOMPLETE" not in line

    # On the fixture the two numbers are equal, so the assertions above pass just as happily
    # against a line that prints the expected count twice and never looks at what resolved.
    # That mutation escaped. The incomplete case is what the line exists for -- it is the live
    # league's state today, at 10 of 20 -- so it is exercised directly.
    from draft_intel.prep import _price_provenance

    short = "\n".join(_price_provenance("somewhere", resolved_count=10, expected_count=20))
    assert "10 of 20" in short
    assert "INCOMPLETE" in short and "DI-043" in short


# ---------------------------------------------------------- DI-062: overrides


def test_the_report_says_nothing_about_overrides_when_there_are_none(report: str) -> None:
    """A heading reading "0 overrides" is noise every week of the year but one."""
    assert "YOUR OVERRIDES" not in report


def test_the_report_declares_every_number_the_user_typed(tmp_path: Path) -> None:
    """§4.8: *never let the user forget they are looking at a number they typed rather than a
    number that was measured.* A printed board that silently uses overridden dollars is exactly
    that forgetting — four days early, and in the form they will carry to the draft.

    Built against a copied tree so the real ``config/`` is never written to.
    """
    import shutil

    from draft_intel.api.app import price_rows
    from draft_intel.prep import build_report
    from draft_intel.store.overrides import OverrideStore, ValueOverride

    root = tmp_path / "repo"
    shutil.copytree(
        ROOT, root, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pyc")
    )
    store = OverrideStore(root / "config" / "value_overrides.yaml")
    rows = price_rows(root, store)
    target = next(row for row in rows if not row.is_keeper)
    store.set(
        ValueOverride(
            player_id=target.player_id,
            name=target.name,
            live_value=target.model_live_value + 20,
            note="my read",
        )
    )
    store.set(ValueOverride(player_id="ghost", name="Nobody", live_value=3.0))

    text = build_report(root, targets=2)
    section = text[text.index("YOUR OVERRIDES") :]

    assert target.name in section
    assert f"${target.model_live_value:.2f}" in section, "what the model said is kept beside it"
    assert "my read" in section
    assert "ghost" in section, "an override naming nobody is reported, not silently dropped"
    # Values are not renormalised, so the board stops summing to the money in the room. That gap
    # is stated rather than closed: one edit must not silently move every other price.
    assert "NOT renormalised" in section
