"""Welcome and consent page, shown on first run (DESIGN §2 and §10)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QVBoxLayout, QWidget

from app.ui.widgets import button, card, divider, label, plain

COLUMN_W = 680

WHAT_IT_DOES = (
    "FocusBand watches you through your webcam while a session is running and lets you know, "
    "with a sound and a notification, when you've been distracted for a minute or your posture "
    "has slipped for a couple of minutes."
)
WHAT_IT_SEES = (
    "The camera looks for your head, shoulders and hands, and for objects such as a phone. "
    "Everything is worked out on this computer. No video or photo is ever saved, and nothing "
    "is sent anywhere: FocusBand makes no internet connections while it runs."
)
WHAT_IT_STORES = (
    "It keeps session times, distraction and posture events, posture scores and your calibration "
    "in a small file in your user folder. You can delete all of it at any time from this screen "
    "or from Settings."
)
CAMERA_NOTE = (
    "The camera is on only during a session or calibration, and turns off when you pause, take a "
    "break or end the session. Your computer may ask for camera and notification permission."
)


class WelcomePage(QWidget):
    accepted = Signal()
    delete_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.agree = QCheckBox("I understand how FocusBand uses my camera")
        self.continue_btn = button("Continue to calibration", "primary")
        self.continue_btn.setEnabled(False)
        delete_btn = button("Delete my data", "ghost")

        self.agree.toggled.connect(self.continue_btn.setEnabled)
        self.continue_btn.clicked.connect(self.accepted)
        delete_btn.clicked.connect(self.delete_requested)

        points = card(spacing=18, margins=(28, 26, 28, 26))
        for i, (heading, text) in enumerate((("What the camera sees", WHAT_IT_SEES),
                                             ("What is stored", WHAT_IT_STORES),
                                             ("When the camera is on", CAMERA_NOTE))):
            if i:
                points.body.addWidget(divider())
            block = QVBoxLayout()
            block.setSpacing(6)
            block.addWidget(label(heading, "strong"))
            block.addWidget(label(text, "muted"))
            points.body.addLayout(block)

        buttons = QHBoxLayout()
        buttons.addWidget(delete_btn)
        buttons.addStretch()
        buttons.addWidget(self.continue_btn)

        column = QVBoxLayout()
        column.setSpacing(0)
        column.addWidget(label("Welcome to FocusBand", "title"))
        column.addSpacing(10)
        column.addWidget(label(WHAT_IT_DOES, "lead"))
        column.addSpacing(28)
        column.addWidget(points)
        column.addSpacing(28)
        column.addWidget(self.agree)
        column.addSpacing(20)
        column.addLayout(buttons)
        column.addStretch()
        body = plain(column)
        body.setMaximumWidth(COLUMN_W)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(40, 48, 40, 36)
        layout.addStretch()
        layout.addWidget(body, 1)
        layout.addStretch()
