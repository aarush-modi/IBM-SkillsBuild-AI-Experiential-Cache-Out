"""Welcome and consent page, shown on first run (DESIGN §2 and §10)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from app.ui.widgets import card, label

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
        self.continue_btn = QPushButton("Continue to calibration")
        self.continue_btn.setObjectName("primary")
        self.continue_btn.setEnabled(False)
        delete_btn = QPushButton("Delete my data")
        delete_btn.setObjectName("danger")

        self.agree.toggled.connect(self.continue_btn.setEnabled)
        self.continue_btn.clicked.connect(self.accepted)
        delete_btn.clicked.connect(self.delete_requested)

        buttons = QHBoxLayout()
        buttons.addWidget(delete_btn)
        buttons.addStretch()
        buttons.addWidget(self.continue_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 32)
        layout.setSpacing(16)
        layout.addWidget(label("Welcome to FocusBand", "title"))
        layout.addWidget(label(WHAT_IT_DOES, "muted"))
        layout.addWidget(card(label("What the camera sees", "subtitle"), label(WHAT_IT_SEES)))
        layout.addWidget(card(label("What is stored", "subtitle"), label(WHAT_IT_STORES)))
        layout.addWidget(label(CAMERA_NOTE, "muted"))
        layout.addStretch()
        layout.addWidget(self.agree)
        layout.addLayout(buttons)
