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

    # --- lifecycle --------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
