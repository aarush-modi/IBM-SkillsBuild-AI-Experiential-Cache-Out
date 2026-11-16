"""Home page: start a session (optionally with Pomodoro), the last session at a glance, and the
way to the dashboard, recalibration and settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui import theme
from app.ui.tray import dot_icon
from app.ui.widgets import button, card, label, plain, set_eyebrow, tile

COLUMN_W = 620


def minutes(seconds: float) -> str:
    m = int(round(seconds / 60))
    if m >= 60:
        return f"{m // 60} h" + (f" {m % 60} min" if m % 60 else "")
    return f"{m} min"


def greeting(hour: int) -> str:
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


class HomePage(QWidget):
    start_requested = Signal(bool)   # Pomodoro on?
    recalibrate_requested = Signal()
    settings_requested = Signal()
    report_requested = Signal(int)   # session id
    dashboard_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        # Top bar: brand on the left, navigation on the right.
        mark = QLabel()
        mark.setPixmap(dot_icon(theme.current().accent).pixmap(18, 18))
        nav = QHBoxLayout()
        nav.setSpacing(4)
        nav.addWidget(mark)
        nav.addSpacing(6)
        nav.addWidget(label("FocusBand", "brand", wrap=False))
        nav.addStretch()
        for text, signal in (("Dashboard", self.dashboard_requested), ("Recalibrate", self.recalibrate_requested),
                             ("Settings", self.settings_requested)):
            b = button(text, "ghost")
            b.clicked.connect(signal)
            nav.addWidget(b)

        self.hello = label(greeting(datetime.now().hour), "title", wrap=False)
        self.status = label("Loading the vision models…", "lead")

        self.start_btn = button("Start session", "primary")
        self.start_btn.setMinimumHeight(52)
        self.pomodoro = QCheckBox("Pomodoro")
        self.start_btn.clicked.connect(lambda: self.start_requested.emit(self.pomodoro.isChecked()))
        self.pomodoro_note = label("", "muted")
        pomo = QHBoxLayout()
        pomo.setSpacing(12)
        pomo.addWidget(self.pomodoro)
        pomo.addWidget(self.pomodoro_note, 1)
        start_card = card(self.start_btn, pomo, spacing=18, margins=(24, 24, 24, 20))

        # Last session: a heading row and three tiles, or an empty state.
        self.last_session = label("Last session", "eyebrow", wrap=False)
        self.report_btn = button("View report  →", "link")
        self.report_btn.hide()
        self.report_btn.clicked.connect(
            lambda: self.report_requested.emit(self._last_id) if self._last_id is not None else None)
        self._last_id: int | None = None
        head = QHBoxLayout()
        head.addWidget(self.last_session)
        head.addStretch()
        head.addWidget(self.report_btn)
        self.tiles = QHBoxLayout()
        self.tiles.setSpacing(12)
        self.tiles_box = plain(self.tiles)
        self.empty = card(label("No sessions yet. Your first report will appear here.", "muted"),
                          margins=(24, 20, 24, 20))

        column = QVBoxLayout()
        column.setSpacing(0)
        column.addWidget(self.hello)
        column.addSpacing(8)
        column.addWidget(self.status)
        column.addSpacing(28)
        column.addWidget(start_card)
        column.addSpacing(40)
        column.addLayout(head)
        column.addSpacing(12)
        column.addWidget(self.tiles_box)
        column.addWidget(self.empty)
        column.addStretch()
        body = plain(column)
        body.setMaximumWidth(COLUMN_W)

        center = QHBoxLayout()
        center.addStretch()
        center.addWidget(body, 1)
        center.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 20, 32, 32)
        layout.setSpacing(0)
        layout.addLayout(nav)
        layout.addSpacing(48)
        layout.addLayout(center, 1)
        self.set_ready(False, True)
        self.set_last_session(None)

    def apply_settings(self, settings: dict[str, Any]) -> None:
        p = settings["pomodoro"]
        self.pomodoro.setChecked(bool(p["enabled"]))
        self.pomodoro_note.setText(f"{p['work_min']} min focus, {p['break_min']} min break. "
                                   "Breaks turn the camera off.")

    def set_ready(self, models_ready: bool, calibrated: bool) -> None:
        self.hello.setText(greeting(datetime.now().hour))
        if not models_ready:
            self.status.setText("Getting ready: loading the vision models…")
        elif not calibrated:
            self.status.setText("Calibrate first, so FocusBand knows how you sit.")
        else:
            self.status.setText("Ready when you are. The camera turns on only when you start.")
        self.start_btn.setEnabled(models_ready and calibrated)

    def set_last_session(self, row: dict[str, Any] | None) -> None:
        while self.tiles.count():
            item = self.tiles.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if not row or not row.get("ended_at"):
            set_eyebrow(self.last_session, "Last session")
            self._last_id = None
            self.report_btn.hide()
            self.tiles_box.hide()
            self.empty.show()
            return
        self._last_id = int(row["id"])
        self.report_btn.show()
        self.tiles_box.show()
        self.empty.hide()
        start = datetime.fromisoformat(row["started_at"])
        total = (datetime.fromisoformat(row["ended_at"]) - start).total_seconds()
        focus = float(row["focus_seconds"] or 0)
        set_eyebrow(self.last_session, f"Last session · {start:%a %d %b, %H:%M}")
        score = row.get("avg_posture_score")
        ratio = f"{100 * focus / total:.0f}%" if total > 0 else "–"
        for value, caption in ((minutes(total), "total"), (ratio, f"focused · {minutes(focus)}"),
                               (f"{score:.0f}" if score is not None else "–", "average posture")):
            t = tile(value, caption)
            self.tiles.addWidget(t, 1)
        self.tiles.setAlignment(Qt.AlignmentFlag.AlignLeft)
