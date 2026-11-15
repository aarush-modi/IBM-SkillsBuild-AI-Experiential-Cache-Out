"""SQLite storage (DESIGN §11). Local only; nothing stored here can reconstruct an image.

All four tables are created on open. This module stores plain values and JSON; it does not
import app/logic, so the logic layer converts its own types (e.g. Calibration.to_dict).
A Database belongs to the thread that opened it (the logic thread).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from app.storage.settings import app_data_dir

DB_NAME = "focusband.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  focus_seconds INTEGER DEFAULT 0,
  avg_posture_score REAL
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  session_id INTEGER REFERENCES sessions(id),
  kind TEXT NOT NULL,
  label TEXT,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  alert_sink TEXT
);

CREATE TABLE IF NOT EXISTS posture_samples (
  session_id INTEGER REFERENCES sessions(id),
  t INTEGER NOT NULL,
  score REAL,
  worst_issue TEXT
);

CREATE TABLE IF NOT EXISTS calibration (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  values_json TEXT NOT NULL
);
"""


def default_path() -> Path:
    return app_data_dir() / DB_NAME


def now_iso() -> str:
    """Local time with UTC offset, as the schema requires."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    # --- calibration -----------------------------------------------------------------

    def save_calibration(self, values: dict[str, Any], created_at: str | None = None) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO calibration (created_at, values_json) VALUES (?, ?)",
                (created_at or now_iso(), json.dumps(values)),
            )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def latest_calibration(self) -> dict[str, Any] | None:
        """The newest calibration's values, or None if the user has never calibrated."""
        row = self._conn.execute(
            "SELECT values_json FROM calibration ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        values: dict[str, Any] = json.loads(row[0])
        return values

    # --- sessions, events and posture samples ----------------------------------------

    def start_session(self, started_at: str) -> int:
        with self._conn:
            cur = self._conn.execute("INSERT INTO sessions (started_at) VALUES (?)", (started_at,))
        assert cur.lastrowid is not None
        return cur.lastrowid

    def end_session(
        self, session_id: int, ended_at: str, focus_seconds: int, avg_posture_score: float | None
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE sessions SET ended_at = ?, focus_seconds = ?, avg_posture_score = ? WHERE id = ?",
                (ended_at, focus_seconds, avg_posture_score, session_id),
            )

    def add_event(
        self, session_id: int, kind: str, label: str | None, started_at: str,
        ended_at: str | None = None, alert_sink: str | None = None,
    ) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO events (session_id, kind, label, started_at, ended_at, alert_sink) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, kind, label, started_at, ended_at, alert_sink),
            )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def end_event(self, event_id: int, ended_at: str, label: str | None) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE events SET ended_at = ?, label = COALESCE(?, label) WHERE id = ?",
                (ended_at, label, event_id),
            )

    def set_alert_sink(self, event_id: int, sink: str) -> None:
        with self._conn:
            self._conn.execute("UPDATE events SET alert_sink = ? WHERE id = ?", (sink, event_id))

    def add_posture_sample(self, session_id: int, t: int, score: float | None, worst_issue: str | None) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO posture_samples (session_id, t, score, worst_issue) VALUES (?, ?, ?, ?)",
                (session_id, t, score, worst_issue),
            )

    def session(self, session_id: int) -> dict[str, Any] | None:
        self._conn.row_factory = sqlite3.Row
        try:
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(row) if row else None
        finally:
            self._conn.row_factory = None

    def events(self, session_id: int) -> list[dict[str, Any]]:
        self._conn.row_factory = sqlite3.Row
        try:
            rows = self._conn.execute("SELECT * FROM events WHERE session_id = ? ORDER BY id", (session_id,))
            return [dict(r) for r in rows]
        finally:
            self._conn.row_factory = None

    def posture_samples(self, session_id: int) -> list[dict[str, Any]]:
        self._conn.row_factory = sqlite3.Row
        try:
            rows = self._conn.execute(
                "SELECT t, score, worst_issue FROM posture_samples WHERE session_id = ? ORDER BY t", (session_id,)
            )
            return [dict(r) for r in rows]
        finally:
            self._conn.row_factory = None

    def delete_sessions_before(self, cutoff: datetime) -> int:
        """Delete sessions that started before `cutoff`, with their events and posture
        samples (DESIGN §11, delete_sessions_after_days). Calibration is kept. Returns the
        number of sessions deleted."""
        cutoff = cutoff.astimezone()  # aware, so it compares with any stored UTC offset
        old = [
            sid for sid, started in self._conn.execute("SELECT id, started_at FROM sessions").fetchall()
            if datetime.fromisoformat(started) < cutoff
        ]
        with self._conn:
            for sid in old:
                self._conn.execute("DELETE FROM events WHERE session_id = ?", (sid,))
                self._conn.execute("DELETE FROM posture_samples WHERE session_id = ?", (sid,))
                self._conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        return len(old)

    # --- lifecycle --------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
