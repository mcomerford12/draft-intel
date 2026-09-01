"""Append-only event persistence on SQLite.

The store is deliberately dumb: events go in, events come out in sequence order, and nothing
is ever updated or deleted. All the intelligence lives in the fold. That is what makes
crash-restart recovery a non-event - there is no derived state on disk that could be stale or
half-written, so resuming is just replaying the log.

WAL mode so a reader never blocks the poller, and so an unclean shutdown mid-draft recovers.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import Engine, Integer, String, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from draft_intel.models import (
    BudgetAdjustment,
    Event,
    ManualKeeper,
    PickAmended,
    PickObserved,
    PickRemoved,
    Reclassify,
    Revert,
)

_KINDS: dict[str, type[BaseModel]] = {
    "pick_observed": PickObserved,
    "pick_removed": PickRemoved,
    "pick_amended": PickAmended,
    "budget_adjustment": BudgetAdjustment,
    "manual_keeper": ManualKeeper,
    "reclassify": Reclassify,
    "revert": Revert,
}


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column()
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(String)


def make_engine(path: str | Path) -> Engine:
    """Open (or create) the event database with WAL enabled."""
    engine = create_engine(f"sqlite:///{path}", future=True)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    Base.metadata.create_all(engine)
    return engine


class EventStore:
    """Append-only log. The sequence number assigned here is the log's ordering."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, events: Iterable[Event]) -> list[Event]:
        """Persist events, returning them stamped with their assigned sequence numbers."""
        out: list[Event] = []
        with Session(self._engine) as session:
            for ev in events:
                row = EventRow(
                    ts=ev.ts or time.time(),
                    kind=ev.kind,
                    payload=ev.model_dump_json(exclude={"seq", "ts"}),
                )
                session.add(row)
                session.flush()
                out.append(ev.model_copy(update={"seq": row.seq, "ts": row.ts}))
            session.commit()
        return out

    def load(self) -> list[Event]:
        """Replay the whole log in sequence order."""
        with Session(self._engine) as session:
            rows = session.scalars(select(EventRow).order_by(EventRow.seq)).all()
        events: list[Event] = []
        for row in rows:
            cls = _KINDS.get(row.kind)
            if cls is None:  # pragma: no cover - defensive against a future kind
                continue
            data = json.loads(row.payload)
            data["seq"] = row.seq
            data["ts"] = row.ts
            events.append(cast(Event, cls.model_validate(data)))
        return events

    def count(self) -> int:
        with Session(self._engine) as session:
            return len(session.scalars(select(EventRow.seq)).all())
