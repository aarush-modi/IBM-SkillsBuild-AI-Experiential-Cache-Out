"""Settings dialog (DESIGN §8 table and §10). Edits a copy of settings; the caller saves it.

Exposes the top-level timing keys with the ranges from section 8, plus camera, overlay, alert
sound, Pomodoro lengths and data retention. Tuning blocks (detectors, posture, vision ...)
stay file-only.
"""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from app.ui.widgets import button, label


def hug(*widgets: QWidget) -> QHBoxLayout:
    """Widgets at their natural width, left-aligned (form rows otherwise stretch them)."""
    row = QHBoxLayout()
    row.setSpacing(8)
    for w in widgets:
        row.addWidget(w)
    row.addStretch()
    return row


def spacer() -> QWidget:
    w = QWidget()
    w.setFixedHeight(6)
    return w

DISTRACTIONS = [("phone", "Phone"), ("looking_away", "Looking away"), ("desk_object", "Desk object"),
                ("away", "Away from desk")]
RETENTION = [("Keep forever", None), ("7 days", 7), ("30 days", 30), ("90 days", 90)]


def form() -> QFormLayout:
    f = QFormLayout()
    f.setContentsMargins(4, 24, 4, 8)
    f.setHorizontalSpacing(28)
    f.setVerticalSpacing(14)
    f.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
    return f


def tab(f: QFormLayout) -> QWidget:
    w = QWidget()
    outer = QVBoxLayout(w)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addLayout(f)
    outer.addStretch()
    return w


def spin(lo: int, hi: int, value: float, suffix: str) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(int(round(value)))
    s.setSuffix(suffix)
    return s


class SettingsDialog(QDialog):
    test_alert_requested = Signal()
    delete_requested = Signal()
    find_cameras_requested = Signal()

    def __init__(self, settings: dict[str, Any], in_session: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FocusBand settings")
        self.setMinimumWidth(600)
        self.original = settings
        s = settings

        # Distractions: 15 s to 5 min per type.
        self.thresholds = {k: spin(15, 300, s["distraction_threshold_s"][k], " s") for k, _ in DISTRACTIONS}
        dist = form()
        for k, name in DISTRACTIONS:
            dist.addRow(f"{name}: remind after", self.thresholds[k])
        dist.addRow(spacer())
        self.repeat_on = QCheckBox("Repeat while still distracted, every")
        self.repeat_on.setChecked(s["repeat_alert_s"] is not None)
        self.repeat = spin(1, 10, (s["repeat_alert_s"] or 120) / 60, " min")
        self.repeat_on.toggled.connect(self.repeat.setEnabled)
        self.repeat.setEnabled(self.repeat_on.isChecked())
        dist.addRow(self.repeat_on, self.repeat)
        self.escalate = QCheckBox("Stronger sound from the 3rd reminder")
        self.escalate.setChecked(s["escalate_after_repeats"] is not None)
        dist.addRow(self.escalate)
        self.snooze = spin(5, 30, s["snooze_s"] / 60, " min")
        dist.addRow("Snooze length", self.snooze)
        self.auto_pause = spin(5, 30, s["auto_pause_away_s"] / 60, " min")
        dist.addRow("Pause the session after away for", self.auto_pause)

        # Posture and Pomodoro.
        self.posture = spin(1, 10, s["posture_threshold_s"] / 60, " min")
        self.work = spin(10, 90, s["pomodoro"]["work_min"], " min")
        self.brk = spin(3, 30, s["pomodoro"]["break_min"], " min")
        other = form()
        other.addRow("Posture: remind after bad posture for", self.posture)
        other.addRow("Pomodoro focus", self.work)
        other.addRow("Pomodoro break", self.brk)

        # Camera, display and alerts.
        self.camera = QComboBox()
        self.set_cameras([s["camera_index"]], s["camera_index"])
        find = button("Find cameras")
        find.setEnabled(not in_session)
        find.clicked.connect(self.find_cameras_requested)
        cam_row = hug(self.camera, find)
        self.overlay = QCheckBox("Show the skeleton overlay by default")
        self.overlay.setChecked(bool(s["overlay"]))
        self.ping = QCheckBox("Play a sound with each alert")
        self.ping.setChecked(bool(s["alerts"]["ping"]))
        test = button("Send test alert")
        test.clicked.connect(self.test_alert_requested)
        band = label("FocusBand band: coming soon (design only)", "muted")
        dev = form()
        dev.addRow("Camera", cam_row)
        dev.addRow(self.overlay)
        dev.addRow(self.ping)
        dev.addRow(spacer())
        dev.addRow(hug(test))
        dev.addRow(band)

        # Data.
        self.retention = QComboBox()
        for name, days in RETENTION:
            self.retention.addItem(name, days)
        self.retention.setCurrentIndex(next(
            (i for i, (_, d) in enumerate(RETENTION) if d == s["delete_sessions_after_days"]), 0))
        delete = button("Delete my data…", "danger")
        delete.clicked.connect(self.delete_requested)
        data = form()
        data.addRow("Delete sessions older than", self.retention)
        data.addRow(label("Your sessions, posture scores and calibration stay on this computer.", "muted"))
        data.addRow(spacer())
        data.addRow(hug(delete))

        self.tabs = QTabWidget()
        self.tabs.tabBar().setDrawBase(False)
        for f, name in ((dist, "Distractions"), (other, "Posture and Pomodoro"), (dev, "Camera and alerts"),
                        (data, "Your data")):
            self.tabs.addTab(tab(f), name)

        save = button("Save", "primary")
        cancel = button("Cancel", "ghost")
        save.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(16)
        layout.addWidget(label("Settings", "big", wrap=False))
        layout.addWidget(self.tabs, 1)
        if in_session:
            layout.addWidget(label("Changes apply from the next session; the alert sound changes now.", "muted"))
        layout.addLayout(buttons)

    def set_cameras(self, indexes: list[int], current: int) -> None:
        self.camera.clear()
        for i in sorted(set(indexes) | {current}):
            self.camera.addItem(f"Camera {i}", i)
        self.camera.setCurrentIndex(self.camera.findData(current))

    def result_settings(self) -> dict[str, Any]:
        s = copy.deepcopy(self.original)
        for k, _ in DISTRACTIONS:
            s["distraction_threshold_s"][k] = self.thresholds[k].value()
        s["repeat_alert_s"] = self.repeat.value() * 60 if self.repeat_on.isChecked() else None
        default_escalate = self.original["escalate_after_repeats"] or 3
        s["escalate_after_repeats"] = default_escalate if self.escalate.isChecked() else None
        s["snooze_s"] = self.snooze.value() * 60
        s["auto_pause_away_s"] = self.auto_pause.value() * 60
        s["posture_threshold_s"] = self.posture.value() * 60
        s["pomodoro"]["work_min"] = self.work.value()
        s["pomodoro"]["break_min"] = self.brk.value()
        s["camera_index"] = self.camera.currentData()
        s["overlay"] = self.overlay.isChecked()
        s["alerts"]["ping"] = self.ping.isChecked()
        s["delete_sessions_after_days"] = self.retention.currentData()
        return s
