"""Calibration wizard page (DESIGN §7 and §10): upright baseline, then the optional window step.

The judgement is in app/logic/calibration.py; this page shows the live preview, a countdown,
progress and a pass or retry result per step, and feeds the steps the FrameFeatures that the
Engine routes here while calibrating.
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout, QWidget

from app.contracts import FrameFeatures
from app.logic import calibration as C
from app.ui.widgets import Banner, PreviewView, card, label

GET_READY_S = 3.0  # UI countdown before each step

STEPS = {
    "upright": ("Step 1 of 2: Sit up straight",
                "Sit tall with your shoulders back and look at your screen, as you would when working well."),
    "window": ("Step 2 of 2: Window direction (optional)",
               "If there's a window you tend to look out of, turn your head toward it and hold it there. "
               "Skip this if there isn't one."),
}


class WizardPage(QWidget):
    finished = Signal(object)   # Calibration
    cancelled = Signal()

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__()
        self.settings = settings
        self.preview = PreviewView("Starting the camera…")
        self.heading = label("", "subtitle")
        self.instruction = label("")
        self.status = label("", "big")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.result = Banner("warn")
        self.primary = QPushButton("Start")
        self.primary.setObjectName("primary")
        self.skip_btn = QPushButton("Skip this step")
        self.cancel_btn = QPushButton("Cancel")

        self.primary.clicked.connect(self._on_primary)
        self.skip_btn.clicked.connect(self._skip_window)
        self.cancel_btn.clicked.connect(self.cancelled)

        side = card(self.heading, self.instruction, self.status, self.progress, self.result)
        side.setMinimumWidth(320)
        buttons = QHBoxLayout()
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch()
        buttons.addWidget(self.skip_btn)
        buttons.addWidget(self.primary)
        right = QVBoxLayout()
        right.addWidget(side)
        right.addStretch()
        right.addLayout(buttons)
        body = QHBoxLayout()
        body.addWidget(self.preview, 3)
        body.addLayout(right, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(16)
        layout.addWidget(label("Calibration", "title"))
        layout.addWidget(label("About 15 seconds. FocusBand judges your posture and where you look "
                               "against how you sit now, so sit the way you'd like to work.", "muted"))
        layout.addLayout(body)
        self.reset()

    # --- state --------------------------------------------------------------------------

    def reset(self) -> None:
        self.phase = "upright"
        self.state = "intro"            # intro | ready | collect | result
        self.step: C._Step[Any] | None = None
        self.step_result: C.StepResult[Any] | None = None
        self.baseline: C.Baseline | None = None
        self.window_yaw: float | None = None
        self.ready_until = 0.0
        self._render()

    def _on_primary(self) -> None:
        if self.state in ("intro", "result") and not (self.step_result and self.step_result.passed):
            self._begin_step()          # Start, or Try again
        elif self.state == "result":
            self._advance()             # Next / Finish

    def _begin_step(self) -> None:
        self.state = "ready"
        self.step = None
        self.step_result = None
        self.ready_until = time.monotonic() + GET_READY_S
        self._render()

    def _advance(self) -> None:
        if self.phase == "upright":
            assert self.step_result is not None
            self.baseline = self.step_result.value
            self.phase = "window"
            self.state = "intro"
            self.step_result = None
            self._render()
        else:
            if self.step_result is not None and self.step_result.passed:
                self.window_yaw = self.step_result.value
            self._finish()

    def _skip_window(self) -> None:
        self.window_yaw = None
        self._finish()

    def _finish(self) -> None:
        assert self.baseline is not None
        self.finished.emit(C.Calibration(self.baseline, self.window_yaw))

    # --- per UI tick and per frame ---------------------------------------------------------

    def feed(self, features: list[FrameFeatures]) -> None:
        if self.state == "ready" and time.monotonic() >= self.ready_until:
            self.state = "collect"
            self.step = C.UprightStep(self.settings) if self.phase == "upright" else C.WindowStep(
                self.settings, self.baseline)  # type: ignore[arg-type]
        if self.state != "collect" or self.step is None:
            return
        for f in features:
            self.step.add(f)
            if self.step.done():
                self.step_result = self.step.result()
                self.state = "result"
                break

    def tick(self) -> None:
        self._render()

    def _render(self) -> None:
        heading, text = STEPS[self.phase]
        self.heading.setText(heading)
        self.instruction.setText(text)
        self.skip_btn.setVisible(self.phase == "window")
        self.result.set(None)
        self.progress.setValue(0)
        if self.state == "intro":
            self.status.setText("")
            self.primary.setText("Start")
        elif self.state == "ready":
            self.status.setText(f"Starting in {max(0.0, self.ready_until - time.monotonic()):.0f}…")
            self.primary.setEnabled(False)
            return
        elif self.state == "collect":
            waiting = isinstance(self.step, C.WindowStep) and self.step.waiting
            self.status.setText("Turn your head toward the window…" if waiting else "Hold still…")
            self.progress.setValue(int(100 * (self.step.progress if self.step else 0)))
            self.primary.setEnabled(False)
            return
        elif self.state == "result" and self.step_result is not None:
            if self.step_result.passed:
                self.status.setText("Done ✓")
                self.progress.setValue(100)
                self.primary.setText("Next" if self.phase == "upright" else "Finish")
            else:
                self.status.setText("Let's try that again")
                self.result.set(self.step_result.reason)
                self.primary.setText("Try again")
        self.primary.setEnabled(True)
