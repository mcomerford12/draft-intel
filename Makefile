.PHONY: install lint types test ci replay smoke prep

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
