"""Small shared widgets: the camera preview, cards and banners."""

from __future__ import annotations

import cv2
import numpy as np
import numpy.typing as npt
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget


class PreviewView(QLabel):
    """Shows the newest camera image, scaled to fit. Images are only ever held in memory."""

    def __init__(self, placeholder: str = "Camera off") -> None:
        super().__init__(placeholder)
        self.setObjectName("preview")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(480, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._placeholder = placeholder

    def show_image(self, bgr: npt.NDArray[np.uint8]) -> None:
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        h, w = rgb.shape[:2]
        image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(image).scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(pix)

    def show_placeholder(self, text: str | None = None) -> None:
        self.clear()
        self.setText(text or self._placeholder)


def card(*widgets: QWidget, spacing: int = 10) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(spacing)
    for w in widgets:
        layout.addWidget(w)
    return frame


def label(text: str = "", role: str = "", wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    if role:
        lab.setObjectName(role)
    lab.setWordWrap(wrap)
    return lab


class Banner(QLabel):
    """A tip or warning line; hidden when empty."""

    def __init__(self, role: str = "tip") -> None:
        super().__init__()
        self.setObjectName(role)
        self.setWordWrap(True)
        self.hide()

    def set(self, text: str | None) -> None:
        if text:
            self.setText(text)
            self.show()
        else:
            self.hide()
