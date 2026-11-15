"""Session page (DESIGN §10): live preview with the skeleton overlay, camera-on indicator,
timer, focus state chip, posture score, tip banner, Pause, Break, Snooze and End."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.logic.pomodoro import PomodoroTick
from app.logic.session import SessionUpdate
from app.ui import theme
from app.ui.widgets import Banner, PreviewView, card, label
from app.vision.overlay import draw_overlay, posture_line_colors
from app.vision.pipeline import PreviewFrame

ALERT_BANNER_S = 8.0  # how long an alert stays on the in-app banner

LABELS = {
    "phone": "Phone", "desk_object": "Desk object", "looking_away": "Looking away",
    "window": "Window", "away": "Away",
}


def clock(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60}:{s % 60:02d}"


class SessionPage(QWidget):
    pause_toggled = Signal()
    break_requested = Signal()
    snooze_toggled = Signal()
    end_requested = Signal()
    recalibrate_requested = Signal()
    overlay_toggled = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.preview = PreviewView("Camera off")
        self.camera_dot = QLabel("● Camera on")
        self.overlay_box = QCheckBox("Skeleton overlay")
        self.chip = QLabel("FOCUSED")
        self.chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer = label("0:00:00", "timer", wrap=False)
        self.focus_time = label("Focused 0:00:00", "muted")
        self.countdown = label("", "muted")
        self.pomodoro = label("", "muted")
        self.posture = label("–", "big")
        self.tip = Banner("tip")
        self.hint = Banner("warn")
        self.alert = Banner("warn")
        self.moved = Banner("warn")
        self.recal_btn = QPushButton("Recalibrate")
        self.recal_btn.hide()
        self.pause_btn = QPushButton("Pause")
        self.break_btn = QPushButton("Break")
        self.snooze_btn = QPushButton("Snooze 10 min")
        self.end_btn = QPushButton("End session")
        self.end_btn.setObjectName("danger")

        self.overlay_box.toggled.connect(self.overlay_toggled)
        self.pause_btn.clicked.connect(self.pause_toggled)
        self.break_btn.clicked.connect(self.break_requested)
        self.snooze_btn.clicked.connect(self.snooze_toggled)
        self.end_btn.clicked.connect(self.end_requested)
        self.recal_btn.clicked.connect(self.recalibrate_requested)

        status = card(self.chip, self.timer, self.focus_time, self.countdown, self.pomodoro, spacing=6)
        status.setMinimumWidth(280)
        posture = card(label("Posture score", "muted"), self.posture, spacing=4)
        side = QVBoxLayout()
        side.addWidget(status)
        side.addWidget(posture)
        side.addWidget(self.moved)
        side.addWidget(self.recal_btn)
        side.addStretch()

        under = QHBoxLayout()
        under.addWidget(self.camera_dot)
        under.addStretch()
        under.addWidget(self.overlay_box)
        left = QVBoxLayout()
        left.addWidget(self.preview, 1)
        left.addLayout(under)

        top = QHBoxLayout()
        top.addLayout(left, 3)
        top.addLayout(side, 1)

        buttons = QGridLayout()
        for i, b in enumerate((self.pause_btn, self.break_btn, self.snooze_btn)):
            buttons.addWidget(b, 0, i)
        buttons.setColumnStretch(3, 1)
        buttons.addWidget(self.end_btn, 0, 4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(12)
        layout.addLayout(top, 1)
        layout.addWidget(self.alert)
        layout.addWidget(self.hint)
        layout.addWidget(self.tip)
        layout.addLayout(buttons)

        self.overlay = True
        self.paused_reason: str | None = None
        self.snoozed = False
        self._last: SessionUpdate | None = None
        self._alert_until = 0.0
        self.set_state("focused")

    # --- called by the main window --------------------------------------------------------

    def begin(self, overlay: bool) -> None:
        self.overlay = overlay
        self.overlay_box.setChecked(overlay)
        self.paused_reason = None
        self.snoozed = False
        self._last = None
        self.moved.set(None)
        self.recal_btn.hide()
        self.alert.set(None)
        self.tip.set(None)
        self.hint.set(None)
        self.timer.setText("0:00:00")
        self.focus_time.setText("Focused 0:00:00")
        self.posture.setText("–")
        self.set_paused(None)

    def show_preview(self, preview: PreviewFrame) -> None:
        if self.paused_reason is not None:
            return
        if self.overlay:
            colors = posture_line_colors(self._last.posture.past_threshold) if self._last else None
            self.preview.show_image(draw_overlay(preview, line_colors=colors))
        else:
            self.preview.show_image(preview.image)

    def show_update(self, u: SessionUpdate) -> None:
        self._last = u
        f = u.focus
        self.snoozed = f.snoozed_for_s > 0
        self.timer.setText(clock(f.t))
        self.focus_time.setText(f"Focused {clock(f.focus_seconds)}")
        if f.state == "paused":
            return
        name = LABELS.get(f.label or "", "")
        self.set_state(f.state, name)
        if f.state == "pending" and f.alert_in_s is not None:
            self.countdown.setText(f"{name}: reminder in {mmss(f.alert_in_s)} unless you refocus")
        elif f.state == "distracted":
            nxt = "" if f.next_repeat_in_s is None else f", next in {mmss(f.next_repeat_in_s)}"
            self.countdown.setText(f"Look back at your screen for 5 s to clear it{nxt}")
        else:
            self.countdown.setText("")
        if self.snoozed:
            self.countdown.setText(f"Alerts snoozed for {mmss(f.snoozed_for_s)}")
        self.snooze_btn.setText("Unsnooze" if self.snoozed else "Snooze 10 min")
        p = u.posture
        self.posture.setText("–" if p.score is None else f"{p.score:.0f}")
        self.tip.set(p.tip)
        self.hint.set(u.camera_hint)
        if u.camera_moved:
            self.moved.set("Your camera seems to have moved since calibration. Recalibrate for accurate results.")
            self.recal_btn.show()

    def show_alert(self, text: str) -> None:
        self.alert.set(text)
        self._alert_until = time.monotonic() + ALERT_BANNER_S

    def set_paused(self, reason: str | None) -> None:
        """reason: 'pause', 'break', 'away', 'pomodoro', or None when running."""
        self.paused_reason = reason
        running = reason is None
        self.camera_dot.setText("● Camera on" if running else "○ Camera off")
        self.camera_dot.setStyleSheet(f"color: {theme.current().focused if running else theme.current().muted};")
        self.pause_btn.setText("Pause" if running else "Resume")
        self.break_btn.setEnabled(running)
        self.snooze_btn.setEnabled(running)
        if not running:
            text = {
                "break": "On a break. Camera off.", "pomodoro": "Pomodoro break. Camera off.",
                "away": "Paused: you were away for a while. Camera off.",
            }.get(reason or "", "Paused. Camera off.")
            self.preview.show_placeholder(text)
            self.set_state("paused", {"break": "Break", "pomodoro": "Break"}.get(reason or "", ""))
            self.countdown.setText("")
            self.tip.set(None)
            self.hint.set(None)

    def set_pomodoro(self, tick: PomodoroTick | None) -> None:
        if tick is None:
            self.pomodoro.setText("")
        else:
            phase = "Focus" if tick.phase == "work" else "Break"
            self.pomodoro.setText(f"Pomodoro: {phase} {mmss(tick.left_s)} left")

    def set_state(self, state: str, detail: str = "") -> None:
        text = {"focused": "FOCUSED", "pending": "DISTRACTED?", "distracted": "DISTRACTED", "paused": "PAUSED"}[state]
        self.chip.setText(f"{text} · {detail}" if detail and state != "focused" else text)
        self.chip.setStyleSheet(theme.chip_style(state))

    def tick(self) -> None:
        if self._alert_until and time.monotonic() > self._alert_until:
            self.alert.set(None)
            self._alert_until = 0.0
