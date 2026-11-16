"""The main window: one window that switches pages (Welcome → Calibration → Home → Session),
a Settings dialog, and the tray icon. It drives the Engine and polls it on a UI timer, so
Qt widgets are only ever touched on the UI thread.
"""

from __future__ import annotations

import copy
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget

from app.alerts import messages
from app.contracts import PATTERN_TEST, Alert
from app.logic.calibration import Calibration, OutdatedCalibration
from app.logic.pomodoro import Pomodoro
from app.logic.report import build_report
from app.runtime import Engine, Status
from app.storage import settings as settings_mod
from app.storage.db import Database, delete_all_data
from app.storage.settings import DEFAULTS
from app.ui import theme
from app.ui.home import HomePage
from app.ui.report import TOP_ISSUES, ReportPage
from app.ui.session import SessionPage
from app.ui.settings import SettingsDialog
from app.ui.tray import Tray, dot_icon
from app.ui.welcome import WelcomePage
from app.ui.wizard import WizardPage

log = logging.getLogger(__name__)

TICK_MS = 33  # UI refresh: about 30 Hz, independent of the vision rate


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: dict[str, Any],
        settings_path: Path | None = None,
        db_factory: Callable[[], Database] = Database,
        engine_factory: Callable[[dict[str, Any]], Engine] = Engine,
        data_folder: Path | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("FocusBand")
        self.setWindowIcon(dot_icon(theme.current().accent))
        self.resize(1100, 720)
        self.settings = settings
        self.settings_path = settings_path
        self.data_folder = data_folder
        self._db_factory = db_factory
        self._engine_factory = engine_factory
        self.db = db_factory()
        self.engine = engine_factory(settings)
        self.calibration = self._load_calibration()
        self.in_session = False
        self.pomodoro: Pomodoro | None = None
        self._recalibrate_after_end = False
        self._quitting = False
        self._told_about_tray = False

        self.welcome = WelcomePage()
        self.wizard = WizardPage(settings)
        self.home = HomePage()
        self.session = SessionPage()
        self.report = ReportPage(settings["posture"]["bad_score"])
        self.stack = QStackedWidget()
        for page in (self.welcome, self.wizard, self.home, self.session, self.report):
            self.stack.addWidget(page)
        self.setCentralWidget(self.stack)
        self.tray = Tray()

        self.welcome.accepted.connect(self._consented)
        self.welcome.delete_requested.connect(self.delete_my_data)
        self.wizard.finished.connect(self._calibrated)
        self.wizard.cancelled.connect(self._cancel_calibration)
        self.home.start_requested.connect(self.start_session)
        self.home.recalibrate_requested.connect(self.recalibrate)
        self.home.settings_requested.connect(self.open_settings)
        self.home.report_requested.connect(self.show_report)
        self.report.done.connect(lambda: self.stack.setCurrentWidget(self.home))
        self.session.pause_toggled.connect(self.toggle_pause)
        self.session.break_requested.connect(lambda: self._pause("break"))
        self.session.snooze_toggled.connect(self.toggle_snooze)
        self.session.end_requested.connect(self.end_session)
        self.session.recalibrate_requested.connect(self._recalibrate_from_session)
        self.session.overlay_toggled.connect(self._overlay_toggled)
        self.tray.open_requested.connect(self.bring_to_front)
        self.tray.session_toggled.connect(self._tray_session)
        self.tray.pause_toggled.connect(self.toggle_pause)
        self.tray.quit_requested.connect(self.quit)

        self.home.apply_settings(settings)
        self._refresh_home()
        if not settings["consent_given"]:
            self.stack.setCurrentWidget(self.welcome)
        else:
            self.engine.prepare_alerts()
            if self.calibration is None:
                self.recalibrate()
            else:
                self.stack.setCurrentWidget(self.home)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_MS)

    # --- settings and calibration --------------------------------------------------------

    def _save_settings(self) -> None:
        settings_mod.save(self.settings, self.settings_path)

    def _load_calibration(self) -> Calibration | None:
        saved = self.db.latest_calibration()
        if saved is None:
            return None
        try:
            return Calibration.from_dict(saved)
        except OutdatedCalibration:
            return None

    def _consented(self) -> None:
        self.settings["consent_given"] = True
        self._save_settings()
        self.engine.prepare_alerts()  # macOS asks for notification permission here, once
        self.recalibrate()

    def recalibrate(self) -> None:
        self.wizard.reset()
        self.stack.setCurrentWidget(self.wizard)
        self.engine.start_calibration()

    def _calibrated(self, cal: Calibration) -> None:
        self.engine.stop_calibration()
        self.db.save_calibration(cal.to_dict())
        self.calibration = cal
        self._refresh_home()
        self.stack.setCurrentWidget(self.home)

    def _cancel_calibration(self) -> None:
        self.engine.stop_calibration()
        self.stack.setCurrentWidget(self.home)

    # --- sessions -----------------------------------------------------------------------

    def start_session(self, pomodoro: bool) -> None:
        if self.calibration is None or not self.engine.models_ready or self.in_session:
            return
        self.settings["pomodoro"]["enabled"] = pomodoro
        self._save_settings()
        self.engine.start_session(self.calibration)
        self.in_session = True
        self.pomodoro = Pomodoro.from_settings(self.settings, time.monotonic()) if pomodoro else None
        self.session.begin(bool(self.settings["overlay"]))
        self.stack.setCurrentWidget(self.session)

    def toggle_pause(self) -> None:
        if not self.in_session:
            return
        if self.session.paused_reason is None:
            self._pause("pause")
        else:
            self.engine.resume()
            self.session.set_paused(None)

    def _pause(self, reason: str) -> None:
        if not self.in_session or self.session.paused_reason is not None:
            return
        self.engine.pause("break" if reason in ("break", "pomodoro") else "pause")
        self.session.set_paused(reason)

    def toggle_snooze(self) -> None:
        if self.session.snoozed:
            self.engine.unsnooze()
        else:
            self.engine.snooze()

    def end_session(self) -> None:
        if self.in_session:
            self.engine.end_session()

    def _recalibrate_from_session(self) -> None:
        self._recalibrate_after_end = True
        self.end_session()

    def _overlay_toggled(self, on: bool) -> None:
        self.session.overlay = on

    def _session_ended(self, session_id: int | None) -> None:
        self.in_session = False
        self.pomodoro = None
        self._refresh_home()
        if self._recalibrate_after_end:
            self._recalibrate_after_end = False
            self.recalibrate()
        elif session_id is None or not self.show_report(session_id):
            self.stack.setCurrentWidget(self.home)

    def show_report(self, session_id: int) -> bool:
        """Show the report for a stored session; False if there is nothing to show."""
        session = self.db.session(session_id)
        if session is None or not session.get("ended_at"):
            return False
        report = build_report(session, self.db.events(session_id), self.db.posture_samples(session_id), TOP_ISSUES)
        self.report.show_report(report)
        self.stack.setCurrentWidget(self.report)
        return True

    def _tray_session(self) -> None:
        if self.in_session:
            self.end_session()
        else:
            self.bring_to_front()
            self.start_session(bool(self.settings["pomodoro"]["enabled"]))

    # --- settings dialog and data -----------------------------------------------------------

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self.in_session, self)
        dlg.test_alert_requested.connect(
            lambda: self.engine.notify(Alert("test", "test", PATTERN_TEST, time.time())))
        dlg.find_cameras_requested.connect(lambda: self._find_cameras(dlg))
        deleted: list[bool] = []

        def on_delete() -> None:
            deleted.append(True)
            dlg.reject()

        dlg.delete_requested.connect(on_delete)
        if dlg.exec():
            self.settings = dlg.result_settings()
            self._save_settings()
            self.engine.update_settings(self.settings)
            self.wizard.settings = self.settings
            self.home.apply_settings(self.settings)
        if deleted:
            self.delete_my_data()

    def _find_cameras(self, dlg: SettingsDialog) -> None:
        from app.vision.capture import list_cameras

        dlg.set_cameras(list_cameras(), dlg.camera.currentData())

    def delete_my_data(self) -> None:
        answer = QMessageBox.question(
            self, "Delete my data",
            "Delete all sessions, posture scores, your calibration and your settings? This can't be undone.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.end_session()
        self.engine.shutdown()
        self.db.close()
        removed = delete_all_data(self.data_folder)
        log.info("Deleted %d data files", len(removed))
        self.settings = copy.deepcopy(DEFAULTS)
        self.db = self._db_factory()
        self.engine = self._engine_factory(self.settings)
        self.calibration = None
        self.in_session = False
        self.pomodoro = None
        self.wizard.settings = self.settings
        self.home.apply_settings(self.settings)
        self._refresh_home()
        self.welcome.agree.setChecked(False)
        self.stack.setCurrentWidget(self.welcome)

    # --- UI tick ------------------------------------------------------------------------------

    def _tick(self) -> None:
        p = self.engine.poll()
        for st in p.statuses:
            self._status(st)
        page = self.stack.currentWidget()
        if p.preview is not None:
            if page is self.wizard:
                self.wizard.preview.show_image(p.preview.image)
            elif page is self.session and self.in_session:
                self.session.show_preview(p.preview)
        if p.calibration_features and page is self.wizard:
            self.wizard.feed(p.calibration_features)
        if p.update is not None and self.in_session:
            self.session.show_update(p.update)
        for a in p.alerts:
            self.session.show_alert(f"{messages.title(a)}: {messages.body(a)}")
        if self.pomodoro is not None and self.in_session:
            self._pomodoro_tick()
        if page is self.wizard:
            self.wizard.tick()
        self.session.tick()
        self._update_tray()

    def _pomodoro_tick(self) -> None:
        assert self.pomodoro is not None
        t = self.pomodoro.tick(time.monotonic())
        self.session.set_pomodoro(t)
        if t.changed_to == "break":
            self._pause("pomodoro")
            self.engine.notify(Alert("pomodoro", "break", PATTERN_TEST, time.time()))
        elif t.changed_to == "work":
            if self.session.paused_reason == "pomodoro":
                self.engine.resume()
                self.session.set_paused(None)
            self.engine.notify(Alert("pomodoro", "work", PATTERN_TEST, time.time()))

    def _status(self, st: Status) -> None:
        if st.kind == "models_ready":
            self._refresh_home()
        elif st.kind == "error":
            QMessageBox.critical(self, "FocusBand", st.detail)
        elif st.kind == "camera_error":
            in_wizard = self.stack.currentWidget() is self.wizard
            if self.in_session:
                self.end_session()
            elif in_wizard:
                self._cancel_calibration()
            QMessageBox.warning(self, "Camera problem", st.detail)
        elif st.kind == "auto_paused":
            self.session.set_paused("away")
        elif st.kind == "session_ended":
            self._session_ended(st.data)

    def _refresh_home(self) -> None:
        self.home.set_ready(self.engine.models_ready, self.calibration is not None)
        self.home.set_last_session(self.db.latest_session())

    def _update_tray(self) -> None:
        paused = self.in_session and self.session.paused_reason is not None
        last = self.session._last
        state = "paused" if paused else (last.focus.state if (last and self.in_session) else "focused")
        self.tray.set_state(state, self.in_session, paused,
                            can_start=self.engine.models_ready and self.calibration is not None)

    # --- window and quitting ------------------------------------------------------------------

    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._quitting and self.tray.available:
            event.ignore()
            self.hide()
            if not self._told_about_tray:
                self._told_about_tray = True
                self.tray.message("FocusBand is still running", "Use the menu bar or tray icon to reopen or quit.")
            return
        self.quit()
        event.accept()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.timer.stop()
        self.end_session()
        self.engine.shutdown()
        self.db.close()
        self.tray.icon.hide()
        self.close()
        from PySide6.QtWidgets import QApplication

        QApplication.quit()
