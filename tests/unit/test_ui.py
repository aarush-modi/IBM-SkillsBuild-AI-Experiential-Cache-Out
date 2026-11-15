"""The app's main window, offscreen, with a fake camera and pipeline and a temporary data folder."""

from __future__ import annotations

import copy
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.alerts.ble_band import BleBandSink  # noqa: E402
from app.alerts.dispatcher import Dispatcher  # noqa: E402
from app.runtime import Engine, LogicWorker, VisionWorker  # noqa: E402
from app.storage import settings as settings_mod  # noqa: E402
from app.storage.db import DB_NAME, Database  # noqa: E402
from app.storage.settings import DEFAULTS  # noqa: E402
from app.ui import wizard as wizard_mod  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.settings import SettingsDialog  # noqa: E402
from tests.unit.test_runtime import FakeCamera, FakePipeline, Sink  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[MainWindow]:
    monkeypatch.setattr(wizard_mod, "GET_READY_S", 0.0)
    settings = copy.deepcopy(DEFAULTS)
    settings["calibration"]["upright_s"] = 1
    db_path = tmp_path / DB_NAME
    sink = Sink()

    def engine(s: dict[str, Any]) -> Engine:
        def vision(s: dict[str, Any], on_frame: Any, on_status: Any) -> VisionWorker:
            return VisionWorker(s, on_frame, on_status, pipeline_factory=lambda _: FakePipeline(),
                                camera_factory=lambda _: FakeCamera())

        def logic(on_update: Any, on_status: Any, settings: dict[str, Any]) -> LogicWorker:
            return LogicWorker(on_update, on_status,
                               dispatcher_factory=lambda _: Dispatcher([BleBandSink(), sink], 2),
                               db_factory=lambda: Database(db_path), settings=settings)

        return Engine(s, vision_factory=vision, logic_factory=logic)

    w = MainWindow(settings, settings_path=tmp_path / "settings.json", db_factory=lambda: Database(db_path),
                   engine_factory=engine, data_folder=tmp_path)
    w._test_sink = sink  # type: ignore[attr-defined]
    yield w
    w.quit()


def pump(qapp: QApplication, until: Callable[[], bool], timeout: float = 8.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def calibrate(qapp: QApplication, w: MainWindow) -> None:
    w.welcome.agree.setChecked(True)
    w.welcome.continue_btn.click()
    assert w.stack.currentWidget() is w.wizard
    pump(qapp, lambda: w.engine.models_ready)
    w.wizard.primary.click()                      # Start the upright step
    pump(qapp, lambda: w.wizard.state == "result")
    assert w.wizard.step_result is not None and w.wizard.step_result.passed
    w.wizard.primary.click()                      # Next
    w.wizard.skip_btn.click()                     # no window
    pump(qapp, lambda: w.stack.currentWidget() is w.home)


def test_first_run_consent_calibrate_and_session(qapp: QApplication, window: MainWindow, tmp_path: Path) -> None:
    w = window
    assert w.stack.currentWidget() is w.welcome
    assert not w.welcome.continue_btn.isEnabled()
    calibrate(qapp, w)
    assert settings_mod.load(tmp_path / "settings.json")["consent_given"] is True
    assert w.calibration is not None and w.home.start_btn.isEnabled()

    w.home.start_btn.click()
    assert w.stack.currentWidget() is w.session and w.in_session
    pump(qapp, lambda: w.session.timer.text() != "0:00:00")
    assert w.session.chip.text() == "FOCUSED"

    w.session.pause_btn.click()
    assert w.session.paused_reason == "pause" and w.session.pause_btn.text() == "Resume"
    pump(qapp, lambda: not w.engine.camera_on)
    w.session.pause_btn.click()
    pump(qapp, lambda: w.engine.camera_on)

    w.session.end_btn.click()
    pump(qapp, lambda: w.stack.currentWidget() is w.home)
    assert not w.in_session and "focused" in w.home.last_session.text()


def test_settings_round_trip(qapp: QApplication) -> None:
    s = copy.deepcopy(DEFAULTS)
    dlg = SettingsDialog(s, in_session=False)
    dlg.thresholds["phone"].setValue(30)
    dlg.repeat_on.setChecked(False)
    dlg.ping.setChecked(False)
    dlg.retention.setCurrentIndex(2)
    out = dlg.result_settings()
    assert out["distraction_threshold_s"]["phone"] == 30
    assert out["repeat_alert_s"] is None and out["alerts"]["ping"] is False
    assert out["delete_sessions_after_days"] == 30
    assert s == DEFAULTS  # the original is untouched
    assert DEFAULTS["distraction_threshold_s"]["phone"] == 60


def test_pomodoro_break_pauses_and_resumes(qapp: QApplication, window: MainWindow) -> None:
    w = window
    calibrate(qapp, w)
    w.settings["pomodoro"].update(work_min=0.02, break_min=0.02)  # about 1 s each
    w.home.pomodoro.setChecked(True)
    w.home.start_btn.click()
    pump(qapp, lambda: w.session.paused_reason == "pomodoro")
    pump(qapp, lambda: w.session.paused_reason is None)
    sink = w._test_sink  # type: ignore[attr-defined]
    pump(qapp, lambda: [a.label for a in sink.sent if a.kind == "pomodoro"] == ["break", "work"])


def test_delete_my_data(qapp: QApplication, window: MainWindow, tmp_path: Path,
                        monkeypatch: pytest.MonkeyPatch) -> None:
    w = window
    calibrate(qapp, w)
    assert (tmp_path / DB_NAME).exists() and (tmp_path / "settings.json").exists()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    w.delete_my_data()
    assert not (tmp_path / "settings.json").exists()
    assert w.stack.currentWidget() is w.welcome and w.calibration is None
    assert not w.settings["consent_given"]
