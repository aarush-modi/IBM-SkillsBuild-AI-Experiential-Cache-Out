"""SessionLogic (detectors + posture + state machine) and SessionRecorder into SQLite."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.contracts import PATTERN_POSTURE, Detection, FrameFeatures, HandInfo
from app.logic.calibration import Baseline, Calibration
from app.logic.session import SessionLogic, SessionUpdate
from app.storage.db import Database
from app.storage.recorder import SessionRecorder
from app.storage.settings import DEFAULTS

FPS = 5
WALL = 1_700_000_000.0
BASE = Baseline(
    head_yaw=0.0, head_pitch=-5.0, head_roll=0.0, shoulder_width=0.3, shoulder_angle=0.0,
    shoulder_mid=(0.5, 0.45), nose_to_shoulder_y=0.8, face_width=0.2,
)
PHONE = dict(hands=[HandInfo((0.6, 0.6, 0.7, 0.7), grasp=True)],
             objects=[Detection("cell phone", 0.9, (0.62, 0.6, 0.68, 0.7))])
SLOUCH = dict(nose_to_shoulder_y=0.8 * 0.7)


def feat(t: float, **kw: Any) -> FrameFeatures:
    base: dict[str, Any] = dict(
        t=t, person_present=True, shoulder_visibility=0.95, head_yaw=0.0, head_pitch=-5.0, head_roll=0.0,
        shoulder_width=0.3, shoulder_angle=0.0, shoulder_mid=(0.5, 0.45), nose_to_shoulder_y=0.8,
        face_width=0.2, face_bbox=(0.4, 0.2, 0.6, 0.4), hands=[], objects=[],
    )
    base.update(kw)
    return FrameFeatures(**base)


class Run:
    def __init__(self, s: dict[str, Any] | None = None) -> None:
        self.logic = SessionLogic(s or copy.deepcopy(DEFAULTS), Calibration(BASE, None), WALL)
        self.t = 0.0
        self.updates: list[SessionUpdate] = []

    def hold(self, seconds: float, **kw: Any) -> SessionUpdate:
        start = self.t
        for i in range(round(seconds * FPS)):
            self.updates.append(self.logic.update(feat(round(start + i / FPS, 6), **kw)))
        self.t = start + seconds
        return self.updates[-1]


def test_phone_alert_flows_through() -> None:
    r = Run()
    r.hold(65, **PHONE)
    alerts = [a for u in r.updates for a in u.alerts]
    assert [(a.kind, a.label) for a in alerts] == [("distraction", "phone")]


def test_posture_alert_and_event() -> None:
    r = Run()
    r.hold(160, **SLOUCH)
    alerts = [a for u in r.updates for a in u.alerts]
    assert [(a.kind, a.label, a.pattern) for a in alerts] == [("posture", "slouching", PATTERN_POSTURE)]
    opened = [e for u in r.updates for e in u.events if e.kind == "posture"]
    assert opened and opened[0].label == "slouching" and opened[0].started_at == pytest.approx(27, abs=1)


def test_posture_alert_muted_while_snoozed() -> None:
    r = Run()
    r.hold(1)
    r.logic.snooze()
    r.hold(200, **SLOUCH)
    assert not any(u.alerts for u in r.updates)


def test_pause_closes_posture_event_and_skips_frames() -> None:
    r = Run()
    r.hold(40, **SLOUCH)
    events = r.logic.pause("break")
    assert [e.kind for e in events] == ["posture", "break"] and events[0].ended_at is not None
    u = r.hold(300, **SLOUCH)
    assert u.focus.state == "paused" and u.posture.score is None and not u.alerts
    r.logic.resume()
    u = r.hold(2)
    assert u.focus.state == "focused"


def test_recorder_writes_session_events_and_samples(tmp_path: Path) -> None:
    db = Database(tmp_path / "db.sqlite")
    r = Run()
    rec = SessionRecorder(db, WALL)
    r.hold(70, **PHONE)
    r.hold(6)
    r.hold(40, **SLOUCH)
    for u in r.updates:
        rec.events(u.events)
        if u.sample:
            rec.sample(u.sample)
    rec.events(r.logic.end())
    rec.finish(r.t, r.updates[-1].focus.focus_seconds)

    rows = db.events(rec.session_id)
    kinds = [(e["kind"], e["label"]) for e in rows]
    assert ("distraction", "phone") in kinds and ("alert", "phone") in kinds and ("posture", "slouching") in kinds
    assert all(e["ended_at"] is not None for e in rows)  # everything closed at the end
    distraction = next(e for e in rows if e["kind"] == "distraction")
    start = datetime.fromisoformat(distraction["started_at"])
    assert start.tzinfo is not None
    assert start.timestamp() == pytest.approx(WALL, abs=1)

    session = db.session(rec.session_id)
    assert session is not None and session["ended_at"] is not None
    assert session["focus_seconds"] > 0
    samples = db.posture_samples(rec.session_id)
    assert [s["t"] for s in samples][:3] == [10, 20, 30]
    assert session["avg_posture_score"] == pytest.approx(
        sum(s["score"] for s in samples if s["score"] is not None)
        / len([s for s in samples if s["score"] is not None])
    )
    db.close()


def test_delete_old_sessions_keeps_calibration(tmp_path: Path) -> None:
    with Database(tmp_path / "db.sqlite") as db:
        now = datetime.now().astimezone()
        old = db.start_session((now - timedelta(days=40)).isoformat(timespec="seconds"))
        new = db.start_session((now - timedelta(days=2)).isoformat(timespec="seconds"))
        db.add_event(old, "distraction", "phone", now.isoformat())
        db.add_posture_sample(old, 10, 90.0, None)
        db.save_calibration({"version": 3})

        assert db.delete_sessions_before(now - timedelta(days=30)) == 1
        assert db.session(old) is None and db.events(old) == [] and db.posture_samples(old) == []
        assert db.session(new) is not None
        assert db.latest_calibration() == {"version": 3}
