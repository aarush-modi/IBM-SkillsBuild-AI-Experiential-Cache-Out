"""The vision and logic threads, and the Engine the UI drives them through (DESIGN §4).

- Vision thread: loads the models once, opens the camera only while it is needed, and turns
  each frame into FrameFeatures (for logic) and a PreviewFrame (for the UI).
- Logic thread: runs one session at a time (SessionLogic), stores it (SessionRecorder) and
  sends alerts (AlertRunner). It owns its own database connection.
- Engine: lives on the UI thread and is the only thing the UI calls. It routes features to the
  logic thread during a session, or to the calibration wizard while calibrating, and hands the
  UI the newest preview and the logic thread's updates. No Qt here: the UI polls poll().

Threads exchange frozen dataclasses and plain tuples through queues; frames stay in memory.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.alerts.dispatcher import Dispatcher
from app.alerts.runner import AlertRunner
from app.contracts import Alert, FrameFeatures
from app.logic.calibration import Calibration
from app.logic.session import SessionLogic, SessionUpdate
from app.storage.db import Database
from app.storage.recorder import SessionRecorder
from app.vision.capture import Camera, CameraError, Frame
from app.vision.pipeline import PreviewFrame

log = logging.getLogger(__name__)

Mode = Literal["idle", "calibrating", "session"]


class PipelineLike(Protocol):
    def process(self, frame: Frame) -> tuple[FrameFeatures, PreviewFrame]: ...
    def reset(self) -> None: ...
    def close(self) -> None: ...


class CameraLike(Protocol):
    def open(self) -> None: ...
    def read(self) -> Frame | None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class Status:
    """A one-off message for the UI: models_ready, camera_on, camera_off, camera_error,
    session_started, session_ended, auto_paused, alert_delivered, error."""
    kind: str
    detail: str = ""
    data: Any = None


# --- vision thread ----------------------------------------------------------------------------

class VisionWorker(threading.Thread):
    def __init__(
        self,
        settings: dict[str, Any],
        on_frame: Callable[[FrameFeatures, PreviewFrame], None],
        on_status: Callable[[Status], None],
        pipeline_factory: Callable[[dict[str, Any]], PipelineLike] | None = None,
        camera_factory: Callable[[dict[str, Any]], CameraLike] | None = None,
    ) -> None:
        super().__init__(name="vision", daemon=True)
        self.settings = settings
        self._on_frame = on_frame
        self._on_status = on_status
        self._pipeline_factory = pipeline_factory or _real_pipeline
        self._camera_factory = camera_factory or Camera.from_settings
        self._commands: queue.Queue[tuple[str, Any]] = queue.Queue()

    def start_camera(self, settings: dict[str, Any], reset_clock: bool) -> None:
        self._commands.put(("start", (settings, reset_clock)))

    def stop_camera(self) -> None:
        self._commands.put(("stop", None))

    def quit(self) -> None:
        self._commands.put(("quit", None))

    def run(self) -> None:
        try:
            pipeline = self._pipeline_factory(self.settings)
        except Exception as e:
            log.exception("Model loading failed")
            self._on_status(Status("error", f"Could not load the models: {e}"))
            return
        self._on_status(Status("models_ready"))
        camera: CameraLike | None = None
        try:
            while True:
                try:
                    cmd, arg = self._commands.get(timeout=None if camera is None else 0)
                except queue.Empty:
                    cmd, arg = "", None
                if cmd == "quit":
                    break
                if cmd == "stop" and camera is not None:
                    camera.close()  # release the camera whenever it isn't needed
                    camera = None
                    self._on_status(Status("camera_off"))
                elif cmd == "start" and camera is None:
                    settings, reset_clock = arg
                    if reset_clock:
                        pipeline.reset()
                    try:
                        camera = self._camera_factory(settings)
                        camera.open()
                        self._on_status(Status("camera_on"))
                    except CameraError as e:
                        camera = None
                        self._on_status(Status("camera_error", str(e)))
                if camera is not None:
                    try:
                        frame = camera.read()
                    except CameraError as e:
                        camera.close()
                        camera = None
                        self._on_status(Status("camera_error", str(e)))
                        continue
                    if frame is not None:
                        features, preview = pipeline.process(frame)
                        self._on_frame(features, preview)
        finally:
            if camera is not None:
                camera.close()
            pipeline.close()


def _real_pipeline(settings: dict[str, Any]) -> PipelineLike:
    from app.vision.pipeline import VisionPipeline

    return VisionPipeline.from_settings(settings)


# --- logic thread -----------------------------------------------------------------------------

class LogicWorker(threading.Thread):
    def __init__(
        self,
        on_update: Callable[[SessionUpdate], None],
        on_status: Callable[[Status], None],
        dispatcher_factory: Callable[[dict[str, Any]], Dispatcher] = Dispatcher.from_settings,
        db_factory: Callable[[], Database] = Database,
        settings: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name="logic", daemon=True)
        self._on_update = on_update
        self._on_status = on_status
        self._dispatcher_factory = dispatcher_factory
        self._db_factory = db_factory
        self._initial_settings = settings
        self.inbox: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._session: SessionLogic | None = None
        self._recorder: SessionRecorder | None = None
        self._runner: AlertRunner | None = None
        self._in_flight: list[tuple[Future[str | None], Alert, int | None]] = []

    def run(self) -> None:
        db = self._db_factory()
        self._runner = AlertRunner(self._dispatcher_factory(self._initial_settings or {}))
        try:
            while True:
                try:
                    cmd, arg = self.inbox.get(timeout=0.2)
                except queue.Empty:
                    cmd, arg = "", None
                if cmd == "quit":
                    self._end_session(db)
                    break
                self._run_command(cmd, arg, db)
                self._collect_deliveries(db)
        finally:
            if self._runner is not None:
                self._runner.close()
            db.close()

    def _run_command(self, cmd: str, arg: Any, db: Database) -> None:
        s = self._session
        if cmd == "start":
            settings, calibration, wall_start = arg
            self._end_session(db)
            self._session = SessionLogic(settings, calibration, wall_start)
            self._recorder = SessionRecorder(db, wall_start)
            self._on_status(Status("session_started", data=self._recorder.session_id))
        elif cmd == "settings":
            # New alert settings (e.g. ping on or off) take effect for the next alert.
            if self._runner is not None:
                self._runner.close()
            self._runner = AlertRunner(self._dispatcher_factory(arg))
        elif cmd == "prepare_alerts" and self._runner is not None:
            try:
                self._runner.prepare(timeout_s=60)
            except TimeoutError:
                pass
        elif cmd == "notify" and self._runner is not None:
            self._in_flight.append((self._runner.submit(arg), arg, None))
        elif s is None:
            return
        elif cmd == "features":
            was_paused = s.paused
            u = s.update(arg)
            self._store_events(u.events, u.alerts)
            if self._recorder is not None and u.sample is not None:
                self._recorder.sample(u.sample)
            self._on_update(u)
            if s.paused and not was_paused:
                self._on_status(Status("auto_paused"))
        elif cmd == "pause":
            self._store_events(s.pause(arg), [])
        elif cmd == "resume":
            self._store_events(s.resume(), [])
        elif cmd == "snooze":
            self._store_events(s.snooze(), [])
        elif cmd == "unsnooze":
            self._store_events(s.unsnooze(), [])
        elif cmd == "end":
            self._end_session(db)

    def _store_events(self, events: list[Any], alerts: list[Alert]) -> None:
        ids = self._recorder.events(events) if self._recorder is not None else []
        alert_ids = [i for i, e in zip(ids, events) if e.kind == "alert"]
        for n, a in enumerate(alerts):
            if self._runner is not None:
                event_id = alert_ids[n] if n < len(alert_ids) else None
                self._in_flight.append((self._runner.submit(a), a, event_id))

    def _collect_deliveries(self, db: Database) -> None:
        for item in [x for x in self._in_flight if x[0].done()]:
            self._in_flight.remove(item)
            future, alert, event_id = item
            sink = future.result()
            if sink and event_id is not None:
                db.set_alert_sink(event_id, sink)
            self._on_status(Status("alert_delivered", sink or "", alert))

    def _end_session(self, db: Database) -> None:
        s, rec = self._session, self._recorder
        if s is None:
            return
        events = s.end()
        if rec is not None:
            rec.events(events)
            rec.finish(s.last_t, s.focus.focus_seconds)
        self._session = self._recorder = None
        self._on_status(Status("session_ended", data=rec.session_id if rec else None))


# --- engine (UI side) -------------------------------------------------------------------------

@dataclass
class Polled:
    preview: PreviewFrame | None = None
    update: SessionUpdate | None = None        # newest session update since last poll
    alerts: list[Alert] = field(default_factory=list)
    statuses: list[Status] = field(default_factory=list)
    calibration_features: list[FrameFeatures] = field(default_factory=list)


class Engine:
    """The UI's handle on the vision and logic threads. Call poll() from a UI timer."""

    def __init__(
        self,
        settings: dict[str, Any],
        vision_factory: Callable[..., VisionWorker] = VisionWorker,
        logic_factory: Callable[..., LogicWorker] = LogicWorker,
    ) -> None:
        self.settings = settings
        self.mode: Mode = "idle"
        self.models_ready = False
        self.camera_on = False
        self._lock = threading.Lock()
        self._preview: PreviewFrame | None = None
        self._updates: queue.Queue[SessionUpdate] = queue.Queue()
        self._statuses: queue.Queue[Status] = queue.Queue()
        self._calibration: queue.Queue[FrameFeatures] = queue.Queue()
        self.vision = vision_factory(settings, self._on_frame, self._statuses.put)
        self.logic = logic_factory(self._updates.put, self._statuses.put, settings=settings)
        self.vision.start()
        self.logic.start()

    # Called on the vision thread.
    def _on_frame(self, features: FrameFeatures, preview: PreviewFrame) -> None:
        with self._lock:
            self._preview = preview
            mode = self.mode
        if mode == "session":
            self.logic.inbox.put(("features", features))
        elif mode == "calibrating":
            self._calibration.put(features)

    def poll(self) -> Polled:
        with self._lock:
            preview, self._preview = self._preview, None
        out = Polled(preview=preview)
        while True:
            try:
                u = self._updates.get_nowait()
            except queue.Empty:
                break
            out.update = u
            out.alerts += u.alerts
        while True:
            try:
                st = self._statuses.get_nowait()
            except queue.Empty:
                break
            if st.kind == "models_ready":
                self.models_ready = True
            elif st.kind == "camera_on":
                self.camera_on = True
            elif st.kind in ("camera_off", "camera_error"):
                self.camera_on = False
            elif st.kind == "auto_paused":
                self.vision.stop_camera()
            elif st.kind == "session_ended":
                with self._lock:
                    self.mode = "idle"
                self.vision.stop_camera()
            out.statuses.append(st)
        while True:
            try:
                out.calibration_features.append(self._calibration.get_nowait())
            except queue.Empty:
                break
        return out

    # --- calibration --------------------------------------------------------------------

    def start_calibration(self) -> None:
        with self._lock:
            self.mode = "calibrating"
        self.vision.start_camera(self.settings, reset_clock=True)

    def stop_calibration(self) -> None:
        with self._lock:
            self.mode = "idle"
        self.vision.stop_camera()

    # --- sessions -----------------------------------------------------------------------

    def start_session(self, calibration: Calibration) -> None:
        self.logic.inbox.put(("start", (self.settings, calibration, time.time())))
        with self._lock:
            self.mode = "session"
        self.vision.start_camera(self.settings, reset_clock=True)

    def pause(self, reason: Literal["pause", "break"] = "pause") -> None:
        self.logic.inbox.put(("pause", reason))
        self.vision.stop_camera()

    def resume(self) -> None:
        self.logic.inbox.put(("resume", None))
        self.vision.start_camera(self.settings, reset_clock=False)

    def snooze(self) -> None:
        self.logic.inbox.put(("snooze", None))

    def unsnooze(self) -> None:
        self.logic.inbox.put(("unsnooze", None))

    def end_session(self) -> None:
        self.logic.inbox.put(("end", None))
        self.vision.stop_camera()

    def notify(self, alert: Alert) -> None:
        """Send an alert outside the session rules (Pomodoro, Send test alert)."""
        self.logic.inbox.put(("notify", alert))

    def update_settings(self, settings: dict[str, Any]) -> None:
        """Saved settings apply to the next session; alert settings apply at once."""
        self.settings = settings
        self.logic.inbox.put(("settings", settings))

    def prepare_alerts(self) -> None:
        self.logic.inbox.put(("prepare_alerts", None))

    def shutdown(self, timeout_s: float = 5.0) -> None:
        self.logic.inbox.put(("quit", None))
        self.vision.quit()
        self.logic.join(timeout_s)
        self.vision.join(timeout_s)
