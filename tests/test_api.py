"""DI-061 — the price table route, and the overrides behind it.

The board is built from the real fixtures, because a page that renders from synthetic data and
falls over on the real board is not worth having. No player name is hardcoded: the tests pick
whichever player the board ranks first and work from there.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from draft_intel.api.app import create_app, price_rows
from draft_intel.api.store import OverrideStore, ValueOverride

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path: Path) -> OverrideStore:
    """A store on a scratch file, so no test can write to the real config."""
    return OverrideStore(tmp_path / "value_overrides.yaml")


@pytest.fixture
def client(store: OverrideStore) -> TestClient:
    return TestClient(create_app(ROOT, store))


@pytest.fixture(scope="module")
def board_rows() -> list:
    """The unmodified board. Module-scoped because building it runs the whole pipeline."""
    return price_rows(ROOT, OverrideStore(Path("/nonexistent/value_overrides.yaml")))


# ------------------------------------------------------------------ the table


def test_the_table_prices_every_available_player(board_rows: list) -> None:
    """140 roster spots remain after the keepers, and the page prices all of them."""
    assert len(board_rows) == 140
    assert all(row.live_value >= 0 for row in board_rows)
    assert board_rows == sorted(board_rows, key=lambda r: (-r.live_value, r.name))


def test_keepers_are_not_on_the_page(board_rows: list) -> None:
    """They are off the board. Pricing them here would invite a bid on somebody already held."""
    from draft_intel.prep import build_pipeline

    kept = {p.player_id for p in build_pipeline(ROOT).board.players if p.is_keeper}
    assert kept, "the fixture has keepers; otherwise this test proves nothing"
    assert not kept & {row.player_id for row in board_rows}


def test_an_untouched_row_reports_the_model_and_nothing_else(board_rows: list) -> None:
    row = board_rows[0]
    assert row.overridden is False
    assert row.live_value == row.model_live_value
    assert row.delta == 0.0
    assert row.note == ""


def test_the_page_renders_the_rows_it_priced(client: TestClient, board_rows: list) -> None:
    page = client.get("/prices")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    body = page.text
    assert board_rows[0].name in body
    assert f"{board_rows[0].model_live_value:.2f}" in body


# ------------------------------------------------------------------ overriding


def test_an_override_changes_the_price_and_keeps_the_model_beside_it(
    client: TestClient, board_rows: list
) -> None:
    """§4.8's rule, which is the whole reason this route exists rather than an editable CSV:
    the model's number is retained permanently. "The model said $17.74 and I said $40" is a
    different fact from "$40", and on the night the difference is what makes the figure
    trustworthy or not."""
    target = board_rows[0]
    response = client.post(
        f"/api/prices/{target.player_id}", json={"live_value": 99.0, "note": "my read"}
    )

    assert response.status_code == 200
    row = response.json()
    assert row["live_value"] == 99.0
    assert row["model_live_value"] == target.model_live_value, "the model's number survives"
    assert row["overridden"] is True
    assert row["note"] == "my read"


def test_an_override_survives_a_restart(
    client: TestClient, store: OverrideStore, board_rows: list
) -> None:
    """The half of the ask that matters: come back later and the edit is still there. Read
    through a *new* store on the same file, which is what a restarted process does."""
    target = board_rows[0]
    client.post(f"/api/prices/{target.player_id}", json={"live_value": 55.0})

    reopened = OverrideStore(store.path).load()
    assert reopened[target.player_id].live_value == 55.0

    fresh = TestClient(create_app(ROOT, OverrideStore(store.path)))
    row = next(r for r in fresh.get("/api/prices").json() if r["player_id"] == target.player_id)
    assert row["live_value"] == 55.0 and row["overridden"] is True


def test_clearing_an_override_falls_back_to_the_model_not_to_zero(
    client: TestClient, board_rows: list
) -> None:
    """A cleared price must not read as "worth nothing" — that is a bid recommendation."""
    target = board_rows[0]
    client.post(f"/api/prices/{target.player_id}", json={"live_value": 1.0})

    cleared = client.delete(f"/api/prices/{target.player_id}").json()
    assert cleared["live_value"] == target.model_live_value
    assert cleared["overridden"] is False


def test_an_override_naming_nobody_is_refused(client: TestClient) -> None:
    """The rule `apply_overrides` already enforces, at the edge instead. Storing it silently
    leaves the user believing a correction was applied."""
    response = client.post("/api/prices/not-a-player", json={"live_value": 10.0})
    assert response.status_code == 404


def test_a_negative_price_is_refused(client: TestClient, board_rows: list) -> None:
    """A negative value is never a real price, and this project has already been bitten by one
    reaching a ledger."""
    response = client.post(f"/api/prices/{board_rows[0].player_id}", json={"live_value": -5})
    assert response.status_code == 422


def test_only_the_named_player_moves(client: TestClient, board_rows: list) -> None:
    """An edit is a per-player correction, not a rescale. §4.8 is explicit that nothing is
    renormalised behind the user's back."""
    target, neighbour = board_rows[0], board_rows[1]
    client.post(f"/api/prices/{target.player_id}", json={"live_value": 99.0})

    after = {r["player_id"]: r for r in client.get("/api/prices").json()}
    assert after[neighbour.player_id]["live_value"] == neighbour.live_value
    assert after[neighbour.player_id]["overridden"] is False


# ------------------------------------------------------------------ the file


def test_the_file_is_editable_by_hand(store: OverrideStore, board_rows: list) -> None:
    """The user was promised they could go in and change these later. That means the file is an
    interface, so it carries a header explaining every field, and a hand-written entry loads."""
    store.set(ValueOverride(player_id=board_rows[0].player_id, name="x", live_value=12.0))
    text = store.path.read_text()

    assert "edit by hand" in text
    assert "live_value" in text and "blacklisted" in text
    assert store.load()[board_rows[0].player_id].live_value == 12.0


def test_every_read_goes_to_disk_so_a_hand_edit_is_never_ignored(store: OverrideStore) -> None:
    """A cached copy would quietly discard exactly the edits the file exists to accept."""
    store.set(ValueOverride(player_id="p1", name="A", live_value=5.0))
    assert store.load()["p1"].live_value == 5.0

    store.path.write_text("overrides:\n- player_id: p1\n  name: A\n  live_value: 42.0\n")
    assert store.load()["p1"].live_value == 42.0, "the store cached and ignored the file"


def test_an_entry_that_changes_nothing_is_removed_rather_than_stored(
    store: OverrideStore,
) -> None:
    """Clearing every field in the UI should do what it looks like, not leave an inert row."""
    store.set(ValueOverride(player_id="p1", name="A", live_value=5.0))
    assert "p1" in store.load()

    store.set(ValueOverride(player_id="p1", name="A"))
    assert "p1" not in store.load()


def test_entries_are_written_in_a_stable_order(store: OverrideStore) -> None:
    """So a diff shows the edit rather than a reshuffle — these are judgements worth reviewing."""
    for pid in ("p3", "p1", "p2"):
        store.set(ValueOverride(player_id=pid, name=pid, live_value=1.0))
    order = [line for line in store.path.read_text().splitlines() if "player_id" in line]
    assert order == sorted(order)


def test_a_missing_file_is_no_overrides_rather_than_an_error(tmp_path: Path) -> None:
    assert OverrideStore(tmp_path / "absent.yaml").load() == {}


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
