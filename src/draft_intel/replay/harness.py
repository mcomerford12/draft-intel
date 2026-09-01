"""Replay a completed draft through the ingestion pipeline.

The charter makes this the primary product surface during development, not test scaffolding:
the user cannot rehearse against a live auction, so a replay of a real completed draft is the
only way to see the system work before draft night.

Replay feeds the picks feed forward one pick at a time, diffing whole snapshots exactly as
the live poller does, so the code under test is the production path rather than a stand-in.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from draft_intel.models import Event, PickSnapshot
from draft_intel.sleeper.poller import diff_snapshots, parse_picks


def load_picks(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, list):
        raise TypeError(f"{path} does not contain a picks array")
    return payload


def replay_events(
    payload: list[dict[str, Any]], *, seq_start: int = 1
) -> Iterator[tuple[int, Event]]:
    """Yield ``(pick_index, event)`` as the draft unfolds one settled pick at a time.

    Each step presents the pipeline with the feed as it would have looked at that moment, so
    the snapshot diff does real work rather than seeing the finished array in one go.
    """
    ordered = sorted(payload, key=lambda p: p.get("pick_no", 0))
    previous: dict[int, PickSnapshot] = {}
    seq = seq_start
    for i in range(1, len(ordered) + 1):
        current = parse_picks(ordered[:i]).picks
        for event in diff_snapshots(previous, current):
            yield i, event.model_copy(update={"seq": seq})
            seq += 1
        previous = current


def replay_all(payload: list[dict[str, Any]], *, seq_start: int = 1) -> list[Event]:
    """The full event log for a completed draft."""
    return [event for _, event in replay_events(payload, seq_start=seq_start)]


def to_case_a(payload: list[dict[str, Any]], keeper_pick_nos: set[int]) -> list[dict[str, Any]]:
    """Synthesise the Case A twin of a Case B fixture.

    Case A is keepers pre-loaded by the commissioner, arriving with ``is_keeper: true``.
    Case B is the same keepers arriving as ordinary picks because the setup did not take.

    **This transform alone does not make an equivalence test meaningful.** ``is_keeper`` never
    reaches ``DerivedState``, so folding both payloads with the same manifest-backed
    classifier produces identical output no matter what that classifier does -- an earlier
    version of the gate passed with the classifier replaced by a constant function.

    The test must additionally give each case only the detection mechanism it would really
    have: an empty manifest for Case A, so ``is_keeper`` has to do the work, and the full
    manifest for Case B, where ``is_keeper`` is false on every keeper. Agreement then means
    two independent mechanisms reached the same state, which is the actual guarantee.
    """
    out: list[dict[str, Any]] = []
    for raw in payload:
        copy = dict(raw)
        if copy.get("pick_no") in keeper_pick_nos:
            copy["is_keeper"] = True
        out.append(copy)
    return out
