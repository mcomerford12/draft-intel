"""Shared guards for the whole suite.

There is one, and it exists because the failure already happened: a test constructed a
``LiveDraft`` against the repo root without passing scratch stores, so its POST wrote a -$36
budget correction into the project's own ``config/corrections.yaml``. Six later tests and the
rehearsal then folded that correction and failed — none of them anywhere near the test that
caused it, and the rehearsal reporting "first failure at pick 1 of 160" for a reason that had
nothing to do with pick 1.

The individual fix is to pass the scratch stores. The general fix is this: **no test may leave
the real ``config/`` different from how it found it.** Every writable store in this project
takes an injectable path precisely so tests can point it somewhere harmless, and a guard is
what turns that from a convention into a rule.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def _fingerprint() -> dict[str, tuple[int, float]]:
    """Every file in ``config/``, by size and mtime. Cheap enough to run per test."""
    return {
        str(path.relative_to(CONFIG)): (path.stat().st_size, path.stat().st_mtime)
        for path in sorted(CONFIG.rglob("*"))
        if path.is_file()
    }


@pytest.fixture(autouse=True)
def _config_is_read_only() -> Iterator[None]:
    """Fail the test that dirties the real config, rather than the six that inherit it.

    Reported against the culprit, which is the whole point: a correction written into
    ``config/`` by one test surfaces as a wrong ledger in unrelated ones, and the trail back is
    long. The files this catches — ``corrections.yaml``, ``seats.yaml``,
    ``value_overrides.yaml`` — are all inputs the pipeline folds, so polluting one silently
    changes what every other test is asserting against.
    """
    before = _fingerprint()
    yield
    after = _fingerprint()
    if before == after:
        return

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(name for name in before.keys() & after.keys() if before[name] != after[name])
    raise AssertionError(
        "this test modified the real config/ directory. Point the store at tmp_path instead — "
        "every store takes an injectable path for exactly this reason.\n"
        f"  created: {added or 'none'}\n"
        f"  deleted: {removed or 'none'}\n"
        f"  changed: {changed or 'none'}"
    )
