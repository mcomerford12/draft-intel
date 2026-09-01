.PHONY: install lint types test ci replay smoke

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
