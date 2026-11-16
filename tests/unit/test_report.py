"""Session report data from stored rows (FR-14)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.logic.posture import TIPS
from app.logic.report import build_report
from app.storage.db import Database

T0 = datetime(2026, 11, 15, 14, 0, 0).astimezone()


def iso(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def make_session(db: Database) -> int:
    sid = db.start_session(iso(0))
    for kind, label, a, b in [
        ("distraction", "phone", 5, 7),        # 2 min
        ("alert", "phone", 6, 6),
        ("distraction", "phone", 20, 21),      # 1 min
        ("alert", "phone", 21, 21),
        ("away", "away", 30, 33),              # 3 min
        ("alert", "away", 31, 31),
        ("break", None, 40, 50),               # 10 min break
        ("posture", "slouching", 52, 56),      # 4 min
        ("posture", "leaning_in", 57, 58),     # 1 min
        ("posture", "slouching", 60, 62),      # 2 min
        ("posture", "head_tilt", 63, 63.5),
        ("snooze", None, 64, 65),
    ]:
        db.add_event(sid, kind, label, iso(a), iso(b))
    for t, score in [(10, 95.0), (20, 90.0), (30, None), (60, 61.0)]:
        db.add_posture_sample(sid, t * 60, score, None)
    db.end_session(sid, iso(70), focus_seconds=50 * 60, avg_posture_score=82.0)
    return sid


def test_report_matches_logged_events(tmp_path: Path) -> None:
    with Database(tmp_path / "db.sqlite") as db:
        sid = make_session(db)
        session = db.session(sid)
        assert session is not None
        r = build_report(session, db.events(sid), db.posture_samples(sid), top_issues=3)

    assert r.total_s == pytest.approx(70 * 60)
    assert r.paused_s == pytest.approx(10 * 60) and r.active_s == pytest.approx(60 * 60)
    assert r.focus_s == 50 * 60 and r.focus_ratio == pytest.approx(50 / 60)
    # Both total 3 min; more events comes first on a tie.
    assert [(d.label, d.count, round(d.seconds / 60)) for d in r.distractions] == [("phone", 2, 3), ("away", 1, 3)]
    assert r.distraction_count == 3 and r.alerts == 3
    assert r.posture_avg == pytest.approx((95 + 90 + 61) / 3)
    assert r.posture_points == [(10.0, 95.0), (20.0, 90.0), (60.0, 61.0)]
    assert [(i.issue, i.count, round(i.seconds / 60, 1)) for i in r.top_issues] == [
        ("slouching", 2, 6.0), ("leaning_in", 1, 1.0), ("head_tilt", 1, 0.5)]
    assert r.top_issues[0].tip == TIPS["slouching"]


def test_top_issues_limit_and_empty_session(tmp_path: Path) -> None:
    with Database(tmp_path / "db.sqlite") as db:
        sid = db.start_session(iso(0))
        db.end_session(sid, iso(5), focus_seconds=300, avg_posture_score=None)
        session = db.session(sid)
        assert session is not None
        r = build_report(session, db.events(sid), db.posture_samples(sid), top_issues=3)
    assert r.distractions == [] and r.top_issues == [] and r.posture_avg is None
    assert r.focus_ratio == pytest.approx(1.0)

    with Database(tmp_path / "db2.sqlite") as db:
        sid = make_session(db)
        session = db.session(sid)
        assert session is not None
        assert len(build_report(session, db.events(sid), [], top_issues=1).top_issues) == 1
