"""Settings dialog (DESIGN §8 table and §10). Edits a copy of settings; the caller saves it.

Exposes the top-level timing keys with the ranges from section 8, plus camera, overlay, alert
sound, Pomodoro lengths and data retention. Tuning blocks (detectors, posture, vision ...)
stay file-only.
"""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from app.ui.widgets import label

DISTRACTIONS = [("phone", "Phone"), ("looking_away", "Looking away"), ("desk_object", "Desk object"),
                ("away", "Away from desk")]
RETENTION = [("Keep forever", None), ("7 days", 7), ("30 days", 30), ("90 days", 90)]


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
        self.setMinimumWidth(520)
        self.original = settings
        s = settings

        # Distractions: 15 s to 5 min per type.
        self.thresholds = {k: spin(15, 300, s["distraction_threshold_s"][k], " s") for k, _ in DISTRACTIONS}
        dist = QFormLayout()
        for k, name in DISTRACTIONS:
            dist.addRow(f"{name}: remind after", self.thresholds[k])
        self.repeat_on = QCheckBox("Repeat while still distracted, every")
        self.repeat_on.setChecked(s["repeat_alert_s"] is not None)
        self.repeat = spin(1, 10, (s["repeat_alert_s"] or 120) / 60, " min")
        self.repeat_on.toggled.connect(self.repeat.setEnabled)
        self.repeat.setEnabled(self.repeat_on.isChecked())
        rep = QHBoxLayout()
        rep.addWidget(self.repeat_on)
        rep.addWidget(self.repeat)
        rep.addStretch()
        dist.addRow(rep)
        self.escalate = QCheckBox("Stronger sound from the 3rd reminder")
        self.escalate.setChecked(s["escalate_after_repeats"] is not None)
        dist.addRow(self.escalate)
        self.snooze = spin(5, 30, s["snooze_s"] / 60, " min")
        dist.addRow("Snooze length", self.snooze)
        self.auto_pause = spin(5, 30, s["auto_pause_away_s"] / 60, " min")
        dist.addRow("Pause the session after away for", self.auto_pause)
        dist_box = QGroupBox("Distractions")
        dist_box.setLayout(dist)

        # Posture and Pomodoro.
        self.posture = spin(1, 10, s["posture_threshold_s"] / 60, " min")
        self.work = spin(10, 90, s["pomodoro"]["work_min"], " min")
        self.brk = spin(3, 30, s["pomodoro"]["break_min"], " min")
        other = QFormLayout()
        other.addRow("Posture: remind after bad posture for", self.posture)
        other.addRow("Pomodoro focus", self.work)
        other.addRow("Pomodoro break", self.brk)
        other_box = QGroupBox("Posture and Pomodoro")
        other_box.setLayout(other)

        # Camera, display and alerts.
        self.camera = QComboBox()
        self.set_cameras([s["camera_index"]], s["camera_index"])
        find = QPushButton("Find cameras")
        find.setEnabled(not in_session)
        find.clicked.connect(self.find_cameras_requested)
        cam_row = QHBoxLayout()
        cam_row.addWidget(self.camera, 1)
        cam_row.addWidget(find)
        self.overlay = QCheckBox("Show the skeleton overlay by default")
        self.overlay.setChecked(bool(s["overlay"]))
        self.ping = QCheckBox("Play a sound with each alert")
        self.ping.setChecked(bool(s["alerts"]["ping"]))
        test = QPushButton("Send test alert")
        test.clicked.connect(self.test_alert_requested)
        band = label("FocusBand band: coming soon (design only)", "muted")
        dev = QFormLayout()
        dev.addRow("Camera", cam_row)
        dev.addRow(self.overlay)
        dev.addRow(self.ping)
        dev.addRow(test)
        dev.addRow(band)
        dev_box = QGroupBox("Camera and alerts")
        dev_box.setLayout(dev)

        # Data.
        self.retention = QComboBox()
        for name, days in RETENTION:
            self.retention.addItem(name, days)
        self.retention.setCurrentIndex(next(
            (i for i, (_, d) in enumerate(RETENTION) if d == s["delete_sessions_after_days"]), 0))
        delete = QPushButton("Delete my data…")
        delete.setObjectName("danger")
        delete.clicked.connect(self.delete_requested)
        data = QFormLayout()
        data.addRow("Delete sessions older than", self.retention)
        data.addRow(delete)
        data_box = QGroupBox("Your data")
        data_box.setLayout(data)

        save = QPushButton("Save")
        save.setObjectName("primary")
        cancel = QPushButton("Cancel")
        save.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        for box in (dist_box, other_box, dev_box, data_box):
            layout.addWidget(box)
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
