"""Stats across days (FR-15) from stored sessions."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.logic.report import build_report
from app.logic.stats import PeriodStats, build_stats
from app.storage.db import Database

TODAY = date(2026, 11, 15)


def at(day: date, hour: int, minute: float = 0) -> datetime:
    return (datetime(day.year, day.month, day.day, hour) + timedelta(minutes=minute)).astimezone()


def add_session(db: Database, day: date, minutes: int, focus_min: int, distractions: int = 0,
                pause_min: int = 0, scores: tuple[float, ...] = ()) -> None:
    start = at(day, 9)
    sid = db.start_session(start.isoformat(timespec="seconds"))
    for i in range(distractions):
        db.add_event(sid, "distraction", "phone", at(day, 9, 5 + i * 2).isoformat(), at(day, 9, 6 + i * 2).isoformat())
    if pause_min:
        db.add_event(sid, "pause", None, at(day, 9, 30).isoformat(), at(day, 9, 30 + pause_min).isoformat())
    for i, sc in enumerate(scores):
        db.add_posture_sample(sid, (i + 1) * 10, sc, None)
    db.end_session(sid, at(day, 9, minutes).isoformat(timespec="seconds"), focus_min * 60, None)


def stats_from(db: Database, n_days: int) -> PeriodStats:
    cutoff = at(TODAY - timedelta(days=n_days - 1), 0)
    reports = [build_report(s, db.events(s["id"]), db.posture_samples(s["id"]), 0) for s in db.sessions_since(cutoff)]
    return build_stats(reports, TODAY, n_days)


def test_days_totals_and_rates(tmp_path: Path) -> None:
    with Database(tmp_path / "db.sqlite") as db:
        add_session(db, TODAY, minutes=60, focus_min=50, distractions=2, scores=(90.0, 80.0))
        add_session(db, TODAY, minutes=30, focus_min=25, distractions=1, pause_min=10, scores=(60.0,))
        add_session(db, TODAY - timedelta(days=2), minutes=120, focus_min=100, distractions=4)
        add_session(db, TODAY - timedelta(days=10), minutes=60, focus_min=60)  # outside 7 days
        st = stats_from(db, 7)

    assert [d.day for d in st.days] == [TODAY - timedelta(days=6 - i) for i in range(7)]
    today = st.days[-1]
    assert today.sessions == 2 and today.focus_s == 75 * 60
    assert today.active_s == pytest.approx(80 * 60)  # 90 min minus a 10 min pause
    assert today.distractions_per_hour == pytest.approx(3 / (80 / 60))
    assert today.posture_avg == pytest.approx((90 + 80 + 60) / 3)  # weighted by samples
    two_days_ago = st.days[-3]
    assert two_days_ago.sessions == 1 and two_days_ago.posture_avg is None
    empty = st.days[0]
    assert empty.sessions == 0 and empty.focus_s == 0 and empty.distractions_per_hour is None

    total = st.total
    assert total.sessions == 3 and total.focus_s == 175 * 60 and total.distractions == 7
    assert total.posture_avg == pytest.approx((90 + 80 + 60) / 3)


def test_thirty_days_includes_older_sessions(tmp_path: Path) -> None:
    with Database(tmp_path / "db.sqlite") as db:
        add_session(db, TODAY - timedelta(days=10), minutes=60, focus_min=60)
        st = stats_from(db, 30)
    assert len(st.days) == 30 and st.total.sessions == 1


def test_no_sessions(tmp_path: Path) -> None:
    with Database(tmp_path / "db.sqlite") as db:
        st = stats_from(db, 7)
    assert st.total.sessions == 0 and st.total.posture_avg is None and st.total.distractions_per_hour is None
