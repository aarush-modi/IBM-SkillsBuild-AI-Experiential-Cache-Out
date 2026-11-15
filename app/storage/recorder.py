"""Writes one session to the database as it happens (DESIGN §8 and §11).

Turns the logic layer's EventRecords (session seconds, open then close) and posture samples
into rows, with wall-clock ISO timestamps. Only times, labels and scores are stored.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from app.logic.events import EventRecord
from app.logic.posture import PostureSample
from app.storage.db import Database


class SessionRecorder:
    def __init__(self, db: Database, wall_start: float) -> None:
        self.db = db
        self.wall_start = wall_start
        self.session_id = db.start_session(self.iso(0.0))
        self._rows: dict[int, int] = {}  # event key -> events.id
        self._scores: list[float] = []

    def iso(self, t: float) -> str:
        """Session seconds as local wall-clock time with UTC offset."""
        return datetime.fromtimestamp(self.wall_start + t).astimezone().isoformat(timespec="seconds")

    def events(self, records: Iterable[EventRecord]) -> list[int]:
        """Store records; returns the events.id of each, in order (alerts need it for their sink)."""
        ids = []
        for r in records:
            row = self._rows.get(r.key)
            if row is None:
                row = self.db.add_event(
                    self.session_id, r.kind, r.label, self.iso(r.started_at),
                    self.iso(r.ended_at) if r.ended_at is not None else None,
                )
                if r.ended_at is None:
                    self._rows[r.key] = row
            else:
                assert r.ended_at is not None
                self.db.end_event(row, self.iso(r.ended_at), r.label)
                del self._rows[r.key]
            ids.append(row)
        return ids

    def sample(self, s: PostureSample) -> None:
        self.db.add_posture_sample(self.session_id, s.t, s.score, s.worst_issue)
        if s.score is not None:
            self._scores.append(s.score)

    def finish(self, t: float, focus_seconds: float) -> None:
        avg = sum(self._scores) / len(self._scores) if self._scores else None
        self.db.end_session(self.session_id, self.iso(t), round(focus_seconds), avg)
