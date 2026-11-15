"""Vision and logic threads through the Engine, with a fake camera and pipeline."""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from app.alerts.ble_band import BleBandSink
from app.alerts.dispatcher import Dispatcher
from app.contracts import Alert, FrameFeatures
from app.logic.calibration import Baseline, Calibration
from app.runtime import Engine, LogicWorker, Polled, VisionWorker
from app.storage.db import Database
from app.storage.settings import DEFAULTS
from app.vision.capture import CameraError, Frame
from app.vision.pipeline import PreviewFrame

BASE = Baseline(0.0, -5.0, 0.0, 0.3, 0.0, (0.5, 0.45), 0.8, 0.2)
CAL = Calibration(BASE, None)
IMG = np.zeros((48, 64, 3), dtype=np.uint8)


class FakeCamera:
    opened: list[FakeCamera] = []

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.is_open = False
        self.ts = 0

    def open(self) -> None:
        if self.fail:
            raise CameraError("no camera")
        self.is_open = True
        FakeCamera.opened.append(self)

    def read(self) -> Frame | None:
        time.sleep(0.005)
        self.ts += 200  # 5 fps of session time, much faster in wall time
        return Frame(IMG, self.ts)

    def close(self) -> None:
        self.is_open = False


class FakePipeline:
    def __init__(self) -> None:
        self.start: int | None = None
        self.closed = False

    def process(self, frame: Frame) -> tuple[FrameFeatures, PreviewFrame]:
        if self.start is None:
            self.start = frame.timestamp_ms
        f = FrameFeatures(
            t=(frame.timestamp_ms - self.start) / 1000, person_present=True, shoulder_visibility=0.95,
            head_yaw=0.0, head_pitch=-5.0, head_roll=0.0, shoulder_width=0.3, shoulder_angle=0.0,
            shoulder_mid=(0.5, 0.45), nose_to_shoulder_y=0.8, face_width=0.2, face_bbox=None,
            hands=[], objects=[],
        )
        return f, PreviewFrame(image=frame.image)

    def reset(self) -> None:
        self.start = None

    def close(self) -> None:
        self.closed = True


class Sink:
    name = "desktop"

    def __init__(self) -> None:
        self.sent: list[Alert] = []

    async def available(self) -> bool:
        return True

    async def send(self, alert: Alert) -> bool:
        self.sent.append(alert)
        return True


def make_engine(tmp_path: Path, camera_fail: bool = False) -> tuple[Engine, Sink, Path]:
    settings = copy.deepcopy(DEFAULTS)
    sink = Sink()
    db_path = tmp_path / "db.sqlite"

    def vision(s: dict[str, Any], on_frame: Any, on_status: Any) -> VisionWorker:
        return VisionWorker(s, on_frame, on_status, pipeline_factory=lambda _: FakePipeline(),
                            camera_factory=lambda _: FakeCamera(fail=camera_fail))

    def logic(on_update: Any, on_status: Any, settings: dict[str, Any]) -> LogicWorker:
        return LogicWorker(on_update, on_status, dispatcher_factory=lambda _: Dispatcher([BleBandSink(), sink], 2),
                           db_factory=lambda: Database(db_path), settings=settings)

    return Engine(settings, vision_factory=vision, logic_factory=logic), sink, db_path


def wait_for(engine: Engine, cond: Callable[[Polled], bool], timeout: float = 5.0) -> list[Polled]:
    seen: list[Polled] = []
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        p = engine.poll()
        seen.append(p)
        if cond(p):
            return seen
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def has_status(kind: str) -> Callable[[Polled], bool]:
    return lambda p: any(s.kind == kind for s in p.statuses)


def test_session_runs_and_is_stored(tmp_path: Path) -> None:
    engine, _, db_path = make_engine(tmp_path)
    try:
        wait_for(engine, has_status("models_ready"))
        engine.start_session(CAL)
        wait_for(engine, lambda p: p.update is not None and p.update.focus.t > 2)
        assert engine.camera_on and engine.mode == "session"
        engine.end_session()
        polled = wait_for(engine, has_status("session_ended"))
        session_id = next(s.data for p in polled for s in p.statuses if s.kind == "session_ended")
        assert engine.mode == "idle"
    finally:
        engine.shutdown()
    assert not any(c.is_open for c in FakeCamera.opened)  # camera released
    with Database(db_path) as db:
        row = db.session(session_id)
        assert row is not None and row["ended_at"] is not None and row["focus_seconds"] >= 1


def test_pause_releases_camera_and_resume_reopens(tmp_path: Path) -> None:
    engine, _, _ = make_engine(tmp_path)
    try:
        wait_for(engine, has_status("models_ready"))
        engine.start_session(CAL)
        wait_for(engine, has_status("camera_on"))
        engine.pause("break")
        wait_for(engine, has_status("camera_off"))
        assert not engine.camera_on
        engine.resume()
        wait_for(engine, has_status("camera_on"))
        wait_for(engine, lambda p: p.update is not None and p.update.focus.state == "focused")
    finally:
        engine.shutdown()


def test_calibration_mode_routes_features_to_the_ui(tmp_path: Path) -> None:
    engine, _, _ = make_engine(tmp_path)
    try:
        wait_for(engine, has_status("models_ready"))
        engine.start_calibration()
        polled = wait_for(engine, lambda p: len(p.calibration_features) > 0)
        assert all(p.update is None for p in polled)
        engine.stop_calibration()
        wait_for(engine, has_status("camera_off"))
    finally:
        engine.shutdown()


def test_notify_goes_through_the_dispatcher(tmp_path: Path) -> None:
    engine, sink, _ = make_engine(tmp_path)
    try:
        alert = Alert("pomodoro", "break", 4, 0.0)
        engine.notify(alert)
        wait_for(engine, has_status("alert_delivered"))
        assert sink.sent == [alert]
    finally:
        engine.shutdown()


def test_camera_error_is_reported(tmp_path: Path) -> None:
    engine, _, _ = make_engine(tmp_path, camera_fail=True)
    try:
        wait_for(engine, has_status("models_ready"))
        engine.start_session(CAL)
        polled = wait_for(engine, has_status("camera_error"))
        assert "no camera" in next(s.detail for p in polled for s in p.statuses if s.kind == "camera_error")
        assert not engine.camera_on
    finally:
        engine.shutdown()
