"""SQLite storage on a temporary file."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from app.storage.db import Database, now_iso


def test_creates_all_tables(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "focusband.sqlite"
    Database(path).close()
    with sqlite3.connect(path) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert names == {"sessions", "events", "posture_samples", "calibration"}


def test_reopening_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "focusband.sqlite"
    with Database(path) as db:
        db.save_calibration({"a": 1})
    with Database(path) as db:
        assert db.latest_calibration() == {"a": 1}


def test_latest_calibration_is_newest(tmp_path: Path) -> None:
    with Database(tmp_path / "db.sqlite") as db:
        assert db.latest_calibration() is None
        first = db.save_calibration({"n": 1})
        second = db.save_calibration({"n": 2})
        assert second > first
        assert db.latest_calibration() == {"n": 2}


def test_timestamps_are_iso_with_offset() -> None:
    parsed = datetime.fromisoformat(now_iso())
    assert parsed.tzinfo is not None
