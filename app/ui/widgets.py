"""Small shared widgets: the camera preview, cards, stat tiles, banners and a segmented control."""

from __future__ import annotations

import cv2
import numpy as np
import numpy.typing as npt
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

PREVIEW_RADIUS = 16


class PreviewView(QLabel):
    """Shows the newest camera image, scaled to fit with rounded corners. Images are only
    ever held in memory."""

    def __init__(self, placeholder: str = "Camera off") -> None:
        super().__init__(placeholder)
        self.setObjectName("preview")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(480, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._placeholder = placeholder
        self._set_empty(True)

    def _set_empty(self, empty: bool) -> None:
        if self.property("empty") != empty:
            self.setProperty("empty", empty)
            self.style().unpolish(self)
            self.style().polish(self)

    def show_image(self, bgr: npt.NDArray[np.uint8]) -> None:
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        h, w = rgb.shape[:2]
        image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        ratio = self.devicePixelRatioF()
        scaled = image.scaled(
            self.size() * ratio, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        pix = QPixmap(scaled.size())
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        r = PREVIEW_RADIUS * ratio
        path.addRoundedRect(QRectF(0, 0, scaled.width(), scaled.height()), r, r)
        painter.setClipPath(path)
        painter.drawImage(0, 0, scaled)
        painter.end()
        pix.setDevicePixelRatio(ratio)
        self._set_empty(False)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setPixmap(pix)

    def show_placeholder(self, text: str | None = None) -> None:
        self.clear()
        self._set_empty(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText(text or self._placeholder)


class Card(QFrame):
    """A rounded surface; add content to .body."""

    def __init__(self, spacing: int, margins: tuple[int, int, int, int], role: str) -> None:
        super().__init__()
        self.setObjectName(role)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(spacing)


def card(*widgets: QWidget | QLayout, spacing: int = 12, margins: tuple[int, int, int, int] = (24, 22, 24, 22),
         role: str = "card") -> Card:
    frame = Card(spacing, margins, role)
    for w in widgets:
        if isinstance(w, QLayout):
            frame.body.addLayout(w)
        else:
            frame.body.addWidget(w)
    return frame


def label(text: str = "", role: str = "", wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    if role:
        lab.setObjectName(role)
    if role == "eyebrow":
        lab.setText(text.upper())
        font = lab.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        lab.setFont(font)
    if role in ("timer", "stat"):
        tabular(lab)
    lab.setWordWrap(wrap)
    return lab


def set_eyebrow(lab: QLabel, text: str) -> None:
    lab.setText(text.upper())


def tabular(widget: QWidget) -> None:
    """Fixed-width digits, so a ticking timer doesn't jiggle."""
    font = widget.font()
    font.setFeature(QFont.Tag("tnum"), 1)
    widget.setFont(font)


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


def tile(value: str, caption: str) -> Card:
    """A stat tile: a big number with a short caption under it."""
    return card(label(value, "stat", wrap=False), label(caption, "muted"), spacing=4,
                margins=(20, 18, 20, 18), role="tile")


def button(text: str, role: str = "") -> QPushButton:
    b = QPushButton(text)
    if role:
        b.setObjectName(role)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def plain(layout: QLayout) -> QWidget:
    """A transparent container for a layout."""
    layout.setContentsMargins(0, 0, 0, 0)
    w = QWidget()
    w.setLayout(layout)
    return w


def page_header(title: str, subtitle: QLabel | None = None, *right: QWidget) -> QHBoxLayout:
    """A page title (and optional muted line under it) with actions on the right."""
    text = QVBoxLayout()
    text.setSpacing(6)
    text.addWidget(label(title, "title", wrap=False))
    if subtitle is not None:
        text.addWidget(subtitle)
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addLayout(text, 1)
    for w in right:
        row.addWidget(w, 0, Qt.AlignmentFlag.AlignTop)
    return row


def page_layout(widget: QWidget, margins: tuple[int, int, int, int] = (48, 40, 48, 36),
                spacing: int = 24) -> QVBoxLayout:
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


class Segmented(QFrame):
    """Two or more mutually exclusive options shown as one pill-shaped control."""

    changed = Signal(object)

    def __init__(self, options: list[tuple[str, object]], current: object) -> None:
        super().__init__()
        self.setObjectName("segmented")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.buttons: dict[object, QPushButton] = {}
        for text, value in options:
            b = button(text)
            b.setCheckable(True)
            b.setChecked(value == current)
            self.group.addButton(b)
            layout.addWidget(b)
            self.buttons[value] = b
            b.clicked.connect(lambda _=False, v=value: self.changed.emit(v))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_current(self, value: object) -> None:
        if value in self.buttons:
            self.buttons[value].setChecked(True)


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
