.PHONY: install lint types test ci replay smoke prep serve cockpit rehearsal rehearsal-live

install:
	uv sync

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

types:
	uv run mypy

test:
	uv run pytest -q --cov --cov-report=term-missing

ci: lint types test

replay:
	uv run python -m draft_intel.cli replay

smoke:
	uv run python -m draft_intel.cli smoke

# Charter 4.9: the Sprint 2 gate. The user should be arguing with this board at least
# three days before the draft.
prep:
	uv run python -m draft_intel.cli prep

serve:
	uv run uvicorn draft_intel.api.app:app --reload --port 8000

# The draft-night cockpit. Polls the real draft, folds the ledger live, and answers what the
# player on the block is worth and who can outbid you. `serve` above does NOT poll -- that is
# deliberate, so opening the price table never opens a socket to Sleeper.
cockpit:
	uv run uvicorn --factory "draft_intel.api.app:cockpit" --port 8000

# Sprint 4's gate: the completed mock draft fed through the cockpit one poll at a time, with
# every invariant checked after every pick, then the four chaos cases. Exits non-zero on any
# violation, so it can gate a release.
rehearsal:
	uv run python tools/rehearsal.py

# The same 160 picks against the LIVE league: identity from Sleeper's own rosters and users,
# the real owners.yaml, the real seats. Picks are re-attributed by owner rather than by slot,
# because the mock and the live league seat people differently. Fails while any keeper cannot
# be placed -- which is the point: it is telling you Saturday is not ready yet.
rehearsal-live:
	uv run python tools/rehearsal.py --live
