"""Home page: start a session (optionally with Pomodoro), recalibrate, open settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from app.ui.widgets import card, label


def minutes(seconds: float) -> str:
    m = int(round(seconds / 60))
    if m >= 60:
        return f"{m // 60} h" + (f" {m % 60} min" if m % 60 else "")
    return f"{m} min"


class HomePage(QWidget):
    start_requested = Signal(bool)   # Pomodoro on?
    recalibrate_requested = Signal()
    settings_requested = Signal()
    report_requested = Signal(int)   # session id

    def __init__(self) -> None:
        super().__init__()
        self.status = label("Loading the vision models…", "muted")
        self.start_btn = QPushButton("Start session")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(48)
        self.pomodoro = QCheckBox("Pomodoro")
        self.pomodoro_note = label("", "muted")
        self.last_session = label("No sessions yet.", "muted")
        self.report_btn = QPushButton("View report")
        self.report_btn.hide()
        self._last_id: int | None = None
        recal = QPushButton("Recalibrate")
        settings_btn = QPushButton("Settings")

        self.start_btn.clicked.connect(lambda: self.start_requested.emit(self.pomodoro.isChecked()))
        recal.clicked.connect(self.recalibrate_requested)
        self.report_btn.clicked.connect(
            lambda: self.report_requested.emit(self._last_id) if self._last_id is not None else None)
        settings_btn.clicked.connect(self.settings_requested)

        start_card = card(label("Ready when you are", "subtitle"), self.status, self.start_btn,
                          self.pomodoro, self.pomodoro_note)
        start_card.setMaximumWidth(460)
        last_card = card(label("Last session", "subtitle"), self.last_session, self.report_btn)
        last_card.setMaximumWidth(460)
        extra = QHBoxLayout()
        extra.addWidget(recal)
        extra.addWidget(settings_btn)
        extra.addStretch()

        column = QVBoxLayout()
        column.setSpacing(16)
        column.addWidget(label("FocusBand", "title"))
        column.addWidget(start_card)
        column.addWidget(last_card)
        column.addLayout(extra)
        column.addStretch()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(48, 56, 48, 32)
        layout.addStretch()
        layout.addLayout(column)
        layout.addStretch()
        self.set_ready(False, True)

    def apply_settings(self, settings: dict[str, Any]) -> None:
        p = settings["pomodoro"]
        self.pomodoro.setChecked(bool(p["enabled"]))
        self.pomodoro_note.setText(f"{p['work_min']} min focus, {p['break_min']} min break, repeating. "
                                   "Breaks turn the camera off.")

    def set_ready(self, models_ready: bool, calibrated: bool) -> None:
        if not models_ready:
            self.status.setText("Loading the vision models…")
        elif not calibrated:
            self.status.setText("Calibrate first, so FocusBand knows how you sit.")
        else:
            self.status.setText("The camera turns on when you start.")
        self.start_btn.setEnabled(models_ready and calibrated)

    def set_last_session(self, row: dict[str, Any] | None) -> None:
        if not row or not row.get("ended_at"):
            self.last_session.setText("No sessions yet.")
            self._last_id = None
            self.report_btn.hide()
            return
        self._last_id = int(row["id"])
        self.report_btn.show()
        start = datetime.fromisoformat(row["started_at"])
        total = (datetime.fromisoformat(row["ended_at"]) - start).total_seconds()
        score = row.get("avg_posture_score")
        posture = f", average posture {score:.0f}" if score is not None else ""
        self.last_session.setText(
            f"{start:%a %d %b, %H:%M}: {minutes(total)}, of which {minutes(row['focus_seconds'] or 0)} "
            f"focused{posture}."
        )
