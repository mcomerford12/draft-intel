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
