"""DI-061 / DI-062 — the price table route, and the overrides behind it.

The board is built from the real fixtures, because a page that renders from synthetic data and
falls over on the real board is not worth having. No player name is hardcoded: the tests pick
whichever player the board ranks first and work from there.

DI-062 is the half DI-061 did not do. The ask was to override *all* the projected auction
values; what shipped was one field for the 140 available players, with keepers off the page and
three of the four stored fields inert. So most of what follows is about things that were
silently doing nothing: a points override that never reached VORP, a market override that never
reached the keeper rule, and twenty players who were not on the page at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from draft_intel.api.app import PriceRow, create_app, price_rows
from draft_intel.prep import build_pipeline
from draft_intel.store.overrides import OverrideStore, ValueOverride

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path: Path) -> OverrideStore:
    """A store on a scratch file, so no test can write to the real config."""
    return OverrideStore(tmp_path / "value_overrides.yaml")


@pytest.fixture
def client(store: OverrideStore) -> TestClient:
    return TestClient(create_app(ROOT, store))


@pytest.fixture(scope="module")
def board_rows() -> list[PriceRow]:
    """The unmodified board. Module-scoped because building it runs the whole pipeline."""
    return price_rows(ROOT, OverrideStore(Path("/nonexistent/value_overrides.yaml")))


def _available(rows: list[PriceRow]) -> PriceRow:
    return next(row for row in rows if not row.is_keeper)


def _keeper(rows: list[PriceRow]) -> PriceRow:
    return next(row for row in rows if row.is_keeper)


# ------------------------------------------------------------------ the table


def test_the_table_prices_every_player_on_the_board(board_rows: list[PriceRow]) -> None:
    """ "All of them" is 160: the 140 still to be auctioned and the 20 already held.

    DI-061 showed 140 and called it every player. A keeper's market value is the input to the
    league's retention rule, so leaving them off the page left the single most consequential
    auction value in the league unreachable.
    """
    assert len(board_rows) == 160
    assert sum(row.is_keeper for row in board_rows) == 20
    assert all(row.live_value >= 0 for row in board_rows)


def test_keepers_sort_last_and_carry_no_live_price(board_rows: list[PriceRow]) -> None:
    """Their live value is zero by construction — they are off the board. Ranking them in with
    everybody else would file all twenty at the bottom under a price that is not a price, and
    the page must not offer a bid box for somebody who cannot be bid on."""
    keepers = [row for row in board_rows if row.is_keeper]
    assert board_rows[-len(keepers) :] == keepers
    assert all(row.live_value == 0 for row in keepers)
    assert all(row.market_value > 0 for row in keepers), "but they still have a market value"


def test_the_board_matches_the_pipeline_make_prep_runs(board_rows: list[PriceRow]) -> None:
    """One chain, two surfaces. The report and the page cannot quote different numbers."""
    built = build_pipeline(ROOT, overrides=OverrideStore(Path("/nonexistent/x.yaml")))
    assert {row.player_id for row in board_rows} == {
        p.player_id for p in built.board.players if p.in_pool_full
    }


def test_an_untouched_row_reports_the_model_and_nothing_else(board_rows: list[PriceRow]) -> None:
    row = board_rows[0]
    assert row.overridden is False
    assert row.live_value == row.model_live_value
    assert row.points == row.model_points
    assert row.market_value == row.model_market_value
    assert row.delta == 0.0 and row.note == ""


def test_the_page_renders_the_rows_it_priced(
    client: TestClient, board_rows: list[PriceRow]
) -> None:
    page = client.get("/prices")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    body = page.text
    assert board_rows[0].name in body
    assert f"{board_rows[0].model_live_value:.2f}" in body
    assert _keeper(board_rows).name in body, "keepers are on the page too"


def test_the_json_carries_whether_a_row_was_overridden(
    client: TestClient, board_rows: list[PriceRow]
) -> None:
    """`overridden` and `delta` were plain properties, which pydantic does not serialise: the
    JSON contract silently omitted the two fields carrying §4.8's whole point, that a number the
    user typed is distinguishable from a number that was measured."""
    rows = client.get("/api/prices").json()
    row = next(r for r in rows if r["player_id"] == board_rows[0].player_id)
    assert row["overridden"] is False
    assert row["delta"] == 0.0


# ------------------------------------------------------------ the four fields


def test_a_live_override_changes_the_price_and_keeps_the_model_beside_it(
    client: TestClient, board_rows: list[PriceRow]
) -> None:
    """§4.8's rule, which is the whole reason this route exists rather than an editable CSV:
    the model's number is retained permanently. "The model said $17.74 and I said $40" is a
    different fact from "$40", and on the night the difference is what makes the figure
    trustworthy or not."""
    target = _available(board_rows)
    response = client.post(
        f"/api/prices/{target.player_id}", json={"live_value": 99.0, "note": "my read"}
    )

    assert response.status_code == 200
    row = response.json()
    assert row["live_value"] == 99.0
    assert row["model_live_value"] == target.model_live_value, "the model's number survives"
    assert row["overridden"] is True
    assert row["note"] == "my read"


def test_a_points_override_re_derives_vorp_and_the_price(
    client: TestClient, board_rows: list[PriceRow]
) -> None:
    """The one that was doing nothing. A points override is a claim about the *player*, and
    replacement level is computed from points, so it has to be applied upstream of the baseline.
    Stored downstream it moved a displayed points column and left VORP and dollars untouched --
    a board whose own numbers disagreed with each other."""
    target = _available(board_rows)
    row = client.post(f"/api/prices/{target.player_id}", json={"points": target.points + 80}).json()

    assert row["points"] == target.points + 80
    assert row["vorp"] > target.vorp, "VORP follows from points, so it must move"
    assert row["live_value"] > target.live_value, "and so must the dollars"
    assert row["model_points"] == target.points, "the model's projection survives"
    assert row["model_vorp"] == target.model_vorp


def test_a_market_override_reaches_the_league_keeper_rule(
    client: TestClient, store: OverrideStore, board_rows: list[PriceRow]
) -> None:
    """The other one that was doing nothing, and the one that matters most.

    ``floor(0.75 * auction_value)`` is the league's actual retention rule. Its input is the
    *provider* market value, so an override stored beside the model's book value never reached
    it: the user could type a keeper's auction value and watch their retention price not move.
    """
    keeper = _keeper(board_rows)
    before = build_pipeline(ROOT, overrides=store).keepers
    was = next(line for line in before.lines if line.player_id == keeper.player_id)

    client.post(f"/api/prices/{keeper.player_id}", json={"market_value": 88.0})

    after = build_pipeline(ROOT, overrides=store).keepers
    now = next(line for line in after.lines if line.player_id == keeper.player_id)
    assert now.market_value == 88
    assert now.rule_price == 66, "floor(0.75 x 88)"
    assert now.rule_price != was.rule_price


def test_a_market_override_clears_the_estimate_badge_for_that_player(
    client: TestClient, board_rows: list[PriceRow]
) -> None:
    """The badge means "nobody supplied a real auction value for this player". A number the user
    typed is one. It is the per-player alternative to assembling the whole auction_values.csv,
    which is the only other way to clear it and is a much larger job."""
    keeper = _keeper(board_rows)
    assert keeper.market_is_estimate, "no CSV in the fixture, so everything starts estimated"

    row = client.post(f"/api/prices/{keeper.player_id}", json={"market_value": 42.0}).json()
    assert row["market_is_estimate"] is False
    assert row["model_market_value"] == keeper.market_value, "what it replaced is retained"


def test_the_blacklist_zeroes_the_bid_but_not_the_valuation(
    client: TestClient, board_rows: list[PriceRow]
) -> None:
    """ "Never bid" is a statement about this auction, not a claim the player is worthless.
    Zeroing their market value too would quietly move keeper surplus and the inflation figure
    on the strength of a personal read about one player."""
    target = _available(board_rows)
    row = client.post(f"/api/prices/{target.player_id}", json={"blacklisted": True}).json()

    assert row["live_value"] == 0.0
    assert row["blacklisted"] is True and row["overridden"] is True
    assert row["market_value"] == target.market_value, "still worth what they are worth"


# ------------------------------------------------------------------ the edges


def test_a_keeper_cannot_be_given_a_live_price(
    client: TestClient, board_rows: list[PriceRow]
) -> None:
    """Not a small mistake to store quietly: a live price for a keeper is a bid recommendation
    for somebody who is already rostered and cannot be bid on."""
    response = client.post(f"/api/prices/{_keeper(board_rows).player_id}", json={"live_value": 30})
    assert response.status_code == 422
    assert "keeper" in response.json()["detail"]


def test_editing_one_field_leaves_the_others_alone(
    client: TestClient, board_rows: list[PriceRow]
) -> None:
    """A request that omits a field means "leave it", not "clear it". Typing in one box must not
    wipe the override sitting in the next one — and `None` alone cannot express the difference,
    which is why the route reads `model_fields_set` rather than testing for null."""
    target = _available(board_rows)
    client.post(f"/api/prices/{target.player_id}", json={"live_value": 50.0, "note": "keep me"})
    row = client.post(f"/api/prices/{target.player_id}", json={"market_value": 30.0}).json()

    assert row["live_value"] == 50.0
    assert row["market_value"] == 30.0
    assert row["note"] == "keep me"


def test_sending_a_field_as_null_clears_just_that_field(
    client: TestClient, board_rows: list[PriceRow]
) -> None:
    """Emptying a box on the page sends null for that one field. It must fall back to the model
    for that field and leave every other override standing."""
    target = _available(board_rows)
    client.post(f"/api/prices/{target.player_id}", json={"live_value": 50.0, "market_value": 30.0})
    row = client.post(f"/api/prices/{target.player_id}", json={"live_value": None}).json()

    assert row["live_value"] == target.model_live_value
    assert row["market_value"] == 30.0, "the other override is untouched"


def test_clearing_an_override_falls_back_to_the_model_not_to_zero(
    client: TestClient, board_rows: list[PriceRow]
) -> None:
    """A cleared price must not read as "worth nothing" — that is a bid recommendation."""
    target = _available(board_rows)
    client.post(f"/api/prices/{target.player_id}", json={"live_value": 1.0})

    cleared = client.delete(f"/api/prices/{target.player_id}").json()
    assert cleared["live_value"] == target.model_live_value
    assert cleared["overridden"] is False


def test_an_override_survives_a_restart(
    client: TestClient, store: OverrideStore, board_rows: list[PriceRow]
) -> None:
    """The half of the ask that matters: come back later and the edit is still there. Read
    through a *new* store on the same file, which is what a restarted process does."""
    target = _available(board_rows)
    client.post(f"/api/prices/{target.player_id}", json={"live_value": 55.0})

    reopened = OverrideStore(store.path).load()
    assert reopened[target.player_id].live_value == 55.0

    fresh = TestClient(create_app(ROOT, OverrideStore(store.path)))
    row = next(r for r in fresh.get("/api/prices").json() if r["player_id"] == target.player_id)
    assert row["live_value"] == 55.0 and row["overridden"] is True


def test_make_prep_reads_the_same_overrides_the_page_writes(
    client: TestClient, store: OverrideStore, board_rows: list[PriceRow]
) -> None:
    """Otherwise the page and the printed board quote different prices for the same player, and
    the user has no way to tell which one they are arguing with."""
    target = _available(board_rows)
    client.post(f"/api/prices/{target.player_id}", json={"live_value": 77.0})

    built = build_pipeline(ROOT, overrides=store)
    priced = next(p for p in built.board.players if p.player_id == target.player_id)
    assert priced.baseline_value == 77.0
    model = next(p for p in built.model_board.players if p.player_id == target.player_id)
    assert model.baseline_value == target.model_live_value, "the model's board is kept intact"


def test_an_override_naming_nobody_is_refused(client: TestClient) -> None:
    """The rule `apply_overrides` already enforces, at the edge instead. Storing it silently
    leaves the user believing a correction was applied."""
    response = client.post("/api/prices/not-a-player", json={"live_value": 10.0})
    assert response.status_code == 404


def test_a_stored_override_naming_nobody_is_reported_not_raised(store: OverrideStore) -> None:
    """The API refuses to create one, but the file is hand-editable and is read by `make prep`
    at 8am on draft day. A player who fell out of the projection feed overnight must not take
    the report down — so the pipeline carries the orphan out to be displayed."""
    store.set(ValueOverride(player_id="not-a-player", name="Nobody", live_value=5.0))
    built = build_pipeline(ROOT, overrides=store)

    assert built.orphan_overrides == ("not-a-player",)
    assert len(built.board.players) > 0, "and the board is built anyway"


def test_a_negative_price_is_refused(client: TestClient, board_rows: list[PriceRow]) -> None:
    """A negative value is never a real price, and this project has already been bitten by one
    reaching a ledger."""
    response = client.post(
        f"/api/prices/{_available(board_rows).player_id}", json={"live_value": -5}
    )
    assert response.status_code == 422


def test_only_the_named_player_moves(client: TestClient, board_rows: list[PriceRow]) -> None:
    """An edit is a per-player correction, not a rescale. §4.8 is explicit that nothing is
    renormalised behind the user's back."""
    target, neighbour = board_rows[0], board_rows[1]
    client.post(f"/api/prices/{target.player_id}", json={"live_value": 99.0})

    after = {r["player_id"]: r for r in client.get("/api/prices").json()}
    assert after[neighbour.player_id]["live_value"] == neighbour.live_value
    assert after[neighbour.player_id]["overridden"] is False


def test_the_page_shows_the_deviation_an_override_creates(
    client: TestClient, board_rows: list[PriceRow]
) -> None:
    """§4.8's visible number. Values are not renormalised, so the board stops summing to the
    money in the room the moment anything is edited, and that gap is displayed rather than
    smoothed away — otherwise a single edit would silently move every other price."""
    assert "deviation" not in client.get("/prices").text

    client.post(f"/api/prices/{_available(board_rows).player_id}", json={"live_value": 199.0})
    page = client.get("/prices").text
    assert "deviation" in page and "not</strong> renormalised" in page


# ------------------------------------------------------------------ the file


def test_the_file_is_editable_by_hand(store: OverrideStore, board_rows: list[PriceRow]) -> None:
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


# ------------------------------------------------------- DI-064: cockpit routes


def _cockpit(store: OverrideStore, picks: list) -> TestClient:
    """The app with a fake draft wired in, and polling off.

    `poll=False` is the default and is load-bearing: a test suite that quietly opens a socket to
    the live draft is one that fails on draft night for reasons nobody can reproduce.
    """
    from draft_intel.api.live import LiveDraft
    from tests.test_live import FakeClient

    live = LiveDraft(ROOT, league_id="L", draft_id="D", store=store, client=FakeClient(picks))
    return TestClient(create_app(ROOT, store, live_draft=live))


def _cockpit_with_draft(store: OverrideStore, picks: list) -> tuple[TestClient, Any]:
    """As above, but hands back the LiveDraft so a test can drive its polling directly."""
    from draft_intel.api.live import LiveDraft
    from tests.test_live import FakeClient

    live = LiveDraft(ROOT, league_id="L", draft_id="D", store=store, client=FakeClient(picks))
    return TestClient(create_app(ROOT, store, live_draft=live)), live


def test_the_cockpit_renders_before_any_poll_without_pretending_to_be_live(
    store: OverrideStore,
) -> None:
    """It boots at 6:55pm against a draft that has not started. It must render, and it must not
    present a board it has never read as a board it has."""
    page = _cockpit(store, []).get("/live")
    assert page.status_code == 200
    assert "NOT LIVE" in page.text
    assert "never connected" in page.text
    assert "nobody on the block" in page.text


def test_the_cockpit_reports_the_ledger_it_polled(store: OverrideStore) -> None:
    """The Sprint 1 golden figures, reaching the user through the HTTP surface they will use."""
    import asyncio
    import json

    picks = json.loads((ROOT / "fixtures" / "picks.json").read_text())
    client, live = _cockpit_with_draft(store, picks)
    asyncio.run(live.poll_once())

    snap = client.get("/api/live").json()
    assert snap["picks_seen"] == 160
    assert snap["competitive_picks"] == 140
    assert snap["total_remaining"] == 21
    assert {t["slot"]: t["spent"] for t in snap["teams"]}[3] == 195
    assert client.get("/live").status_code == 200


def test_nothing_is_on_the_block_until_a_poll_has_actually_succeeded(
    store: OverrideStore, board_rows: list[PriceRow]
) -> None:
    """Deliberate, and the opposite of a convenience.

    With no picks every team has $200 and 16 slots, so a max bid *is* computable from config
    alone — and quoting one would be a lie. Having never reached Sleeper, the tool does not know
    the draft has not started; forty picks may already have happened. A confident "$185" on top
    of no reading is worse than an empty box.
    """
    client = _cockpit(store, [])
    body = client.post(
        "/api/live/nominate", json={"player_id": _available(board_rows).player_id}
    ).json()
    assert body["block"] is None
    assert body["stale"] is True


def test_nominating_an_unknown_player_is_refused(store: OverrideStore) -> None:
    """Same rule as the price table: a nomination naming nobody is a typo, and accepting it
    silently leaves a cockpit showing "nobody on the block" while the room bids."""
    response = _cockpit(store, []).post("/api/live/nominate", json={"player_id": "not-a-player"})
    assert response.status_code == 404


def test_search_returns_candidates_to_nominate(store: OverrideStore) -> None:
    client = _cockpit(store, [])
    rows = client.get("/api/live/search", params={"q": "a"}).json()
    assert rows and all({"player_id", "name", "position"} <= set(row) for row in rows)
    assert client.get("/api/live/search", params={"q": ""}).json() == []


def test_the_cockpit_and_the_price_table_agree_on_a_players_value(
    store: OverrideStore, board_rows: list[PriceRow]
) -> None:
    """Two surfaces, one pipeline. If they can disagree, the user has no way to tell which one
    they are bidding off."""
    import asyncio

    target = _available(board_rows)
    client, live = _cockpit_with_draft(store, [])
    asyncio.run(live.poll_once())
    client.post(f"/api/prices/{target.player_id}", json={"live_value": 64.0})

    block = client.post("/api/live/nominate", json={"player_id": target.player_id}).json()["block"]
    assert block["my_value"] == 64.0, "the cockpit bids off the number the price table shows"


# --------------------------------------- DI-070: forms must survive the repaint


def _cockpit_at(store: OverrideStore, cursor: int) -> tuple[TestClient, Any]:
    import asyncio
    import json

    from draft_intel.api.live import LiveDraft
    from draft_intel.store.corrections import CorrectionStore
    from draft_intel.store.seats import SeatStore
    from tests.test_live import FIXTURE_SEATING, FakeClient

    picks = sorted(
        json.loads((ROOT / "fixtures" / "picks.json").read_text()), key=lambda p: p["pick_no"]
    )
    # Every writable store on the scratch path beside `store`. Omitting these let a test POST a
    # correction into the repo's own config/corrections.yaml, which every later test and the
    # rehearsal then folded -- six failures and a rehearsal that died at pick 1.
    scratch = store.path.parent
    live = LiveDraft(
        ROOT,
        league_id="L",
        draft_id="D",
        store=store,
        seats=SeatStore(scratch / "seats.yaml"),
        corrections=CorrectionStore(scratch / "corrections.yaml"),
        client=FakeClient(picks[:cursor], seating=FIXTURE_SEATING),
    )
    asyncio.run(live.poll_once())
    return TestClient(create_app(ROOT, store, live_draft=live)), live


def _split(page: str) -> tuple[str, str]:
    """The repainted region and the stable shell, split exactly as the page's own JS does."""
    body, tail = page.split('<div id="app">', 1)[1].split("</div>\n<h2>who is up", 1)
    return body, tail


def test_the_repaint_boundary_the_javascript_relies_on_still_splits(
    store: OverrideStore,
) -> None:
    """`repaint()` slices the page on these two literals. Move either and the cockpit silently
    stops updating — the fetch succeeds, the split yields nothing useful, and the board freezes
    while the connection line keeps saying `live`."""
    client, _ = _cockpit_at(store, 60)
    body, tail = _split(client.get("/live").text)
    assert len(body) > 100 and len(tail) > 100


def test_every_form_lives_outside_the_repainted_region(store: OverrideStore) -> None:
    """The defect this card fixes. `#app` is replaced wholesale every two seconds, so an input
    inside it loses what you were typing on a timer — mid-auction, while the room waits.

    Asserted on *where the markup is* rather than by driving a browser, because that is the
    property: a form in `#app` is unusable no matter how it behaves in isolation.
    """
    client, _ = _cockpit_at(store, 60)
    body, tail = _split(client.get("/live").text)

    for control in ("corr-slot", "corr-amt", "corr-why", "corr-go", "seat-slot", "seat-go"):
        assert control not in body, f"{control} would be wiped every repaint"
        assert control in tail, f"{control} is missing from the stable shell"


def test_the_keeper_form_is_on_the_page_and_outside_the_repaint(store: OverrideStore) -> None:
    """Charter §2's primary price path, with a surface at last: pick a team, search a player,
    type what they were kept for."""
    client, _ = _cockpit_at(store, 60)
    body, tail = _split(client.get("/live").text)

    for control in ("keeper-slot", "keeper-q", "keeper-amt", "keeper-hits", "keeper-go"):
        assert control in tail and control not in body
    assert "add keeper" in tail


def test_what_should_refresh_stays_inside_the_repainted_region(store: OverrideStore) -> None:
    """The other half. Corrections in force and seat assignments must update as the draft moves
    — putting *them* in the shell would freeze them at page load."""
    client, live = _cockpit_at(store, 60)
    import asyncio

    slot = live.snapshot().teams[0].slot
    client.post(
        "/api/live/corrections/budget",
        json={"slot": slot, "remaining": 50, "reason": "room says 50"},
    )
    asyncio.run(live.poll_once())

    body, _tail = _split(client.get("/live").text)
    assert "corrections in force" in body.lower()
    assert "you said $50" in body
    assert "room says 50" in body


def test_the_keeper_button_starts_disabled(store: OverrideStore) -> None:
    """A keeper needs a player, and a player needs picking from the search. An enabled button
    with nothing selected posts a keeper for nobody."""
    client, _ = _cockpit_at(store, 60)
    _body, tail = _split(client.get("/live").text)
    assert 'id="keeper-go" disabled' in tail


# ------------------------------------------- DI-073: the reclassification surface
#
# `Reclassify` was the last event type the ledger consumed and nothing produced. Every test
# below is about the one property that matters: the correction has to reach the *analytics*.
# A row written to YAML that leaves `competitive_picks` where it was would satisfy a test that
# only checked the store, and would be worthless at 9pm.


def test_the_pick_list_reports_the_class_each_pick_currently_carries(store: OverrideStore) -> None:
    """Newest first, with the current class on every row. Without the class you cannot see
    whether you are about to change anything."""
    client, _ = _cockpit_at(store, 60)
    rows = client.get("/api/live/picks?limit=5").json()

    assert [row["pick_no"] for row in rows] == [60, 59, 58, 57, 56]
    assert all(row["pick_class"] in {"KEEPER", "COMPETITIVE", "FLAGGED"} for row in rows)
    assert all(row["owner"] and row["name"] for row in rows)


def test_the_pick_list_searches_by_number_and_by_name(store: OverrideStore) -> None:
    client, _ = _cockpit_at(store, 60)
    by_number = client.get("/api/live/picks?q=42").json()
    assert [row["pick_no"] for row in by_number] == [42]

    name = by_number[0]["name"]
    by_name = client.get(f"/api/live/picks?q={name}").json()
    assert 42 in [row["pick_no"] for row in by_name]


def test_reclassifying_a_pick_moves_it_out_of_the_competitive_series(
    store: OverrideStore,
) -> None:
    """**The whole point of the card.** A keeper counted as a bid is a phantom data point in
    inflation, skew, run detection and every tendency profile. The assertion is on
    `competitive_picks`, not on the stored row, because a correction that does not reach the
    analytics has not corrected anything."""
    import asyncio

    client, live = _cockpit_at(store, 60)
    before = live.snapshot().competitive_picks

    target = client.get("/api/live/picks?limit=1").json()[0]
    assert target["pick_class"] == "COMPETITIVE"
    response = client.post(
        "/api/live/corrections/reclassify",
        json={"pick_no": target["pick_no"], "pick_class": "KEEPER", "reason": "ceremonial"},
    )
    assert response.status_code == 200
    assert response.json()["was"] == "COMPETITIVE"

    asyncio.run(live.poll_once())
    assert live.snapshot().competitive_picks == before - 1
    listed = client.get(f"/api/live/picks?q={target['pick_no']}").json()
    assert listed[0]["pick_class"] == "KEEPER", "the list must show the correction it caused"


def test_undoing_a_reclassification_puts_the_pick_back(store: OverrideStore) -> None:
    """A correction nobody dares type is a correction nobody uses. Reverting emits a real
    `Revert` rather than deleting the row, so the fold restores the class exactly."""
    import asyncio

    client, live = _cockpit_at(store, 60)
    before = live.snapshot().competitive_picks
    target = client.get("/api/live/picks?limit=1").json()[0]

    made = client.post(
        "/api/live/corrections/reclassify",
        json={"pick_no": target["pick_no"], "pick_class": "KEEPER"},
    ).json()
    asyncio.run(live.poll_once())
    assert live.snapshot().competitive_picks == before - 1

    client.delete(f"/api/live/corrections/{made['correction']['id']}")
    asyncio.run(live.poll_once())
    assert live.snapshot().competitive_picks == before


@pytest.mark.parametrize(
    ("payload", "status", "why"),
    [
        ({"pick_no": 9999, "pick_class": "KEEPER"}, 404, "a pick the ledger does not hold"),
        ({"pick_no": 60, "pick_class": "COMPETITIVE"}, 422, "a correction that changes nothing"),
        ({"pick_no": 60, "pick_class": "FLAGGED"}, 422, "FLAGGED is not an answer a person gives"),
    ],
)
def test_the_reclassify_endpoint_refuses_what_it_should(
    store: OverrideStore, payload: dict[str, object], status: int, why: str
) -> None:
    """Each refusal is a row that would otherwise sit in the audit trail explaining nothing —
    or, for FLAGGED, a 'correction' that leaves the pick exactly as unresolved as it was."""
    client, _ = _cockpit_at(store, 60)
    assert client.post("/api/live/corrections/reclassify", json=payload).status_code == status, why


def test_a_reclassification_writes_no_slot_and_still_reads_back(store: OverrideStore) -> None:
    """It is keyed on `pick_no` alone. The slot is deliberately absent — late-bound seating
    means a slot copied at 9pm is a staler answer than the pick itself already gives."""
    client, live = _cockpit_at(store, 60)
    client.post("/api/live/corrections/reclassify", json={"pick_no": 60, "pick_class": "KEEPER"})

    stored = live.corrections.load()
    assert [c.slot for c in stored] == [None]
    assert [c.pick_no for c in stored] == [60]
    assert "pick 60" in stored[0].describe()


def test_the_reclassify_form_lives_outside_the_repainted_region(store: OverrideStore) -> None:
    """Same rule as every other form, and the same defect if it is broken: `#app` is replaced
    wholesale every two seconds, so anything typed into a control inside it is wiped."""
    client, live = _cockpit_at(store, 60)
    body, tail = _split(client.get("/live").text)

    for control in ("class-q", "class-to", "class-go", "class-hits"):
        assert control in tail and control not in body
    assert 'id="class-go" disabled' in tail, "nothing selected means nothing to post"

    # ...and the resulting correction shows up in the half that *does* refresh, named by pick
    # rather than by a team it deliberately does not carry.
    import asyncio

    client.post("/api/live/corrections/reclassify", json={"pick_no": 60, "pick_class": "KEEPER"})
    asyncio.run(live.poll_once())
    body, _tail = _split(client.get("/live").text)
    assert "pick 60" in body and "counted as KEEPER" in body
