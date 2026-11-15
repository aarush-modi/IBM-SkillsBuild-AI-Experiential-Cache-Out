"""Tray or menu-bar icon (DESIGN §10): state colour, Start or End session, Pause, Open, Quit."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app.ui import theme


def dot_icon(color: str, size: int = 64) -> QIcon:
    """A filled circle: the app and tray icon, coloured by focus state."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    m = size // 8
    p.drawEllipse(m, m, size - 2 * m, size - 2 * m)
    p.end()
    return QIcon(pix)


class Tray(QObject):
    open_requested = Signal()
    session_toggled = Signal()
    pause_toggled = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        self.icon = QSystemTrayIcon()
        menu = QMenu()
        self.open_action = QAction("Open FocusBand")
        self.session_action = QAction("Start session")
        self.pause_action = QAction("Pause")
        self.quit_action = QAction("Quit FocusBand")
        for a in (self.open_action, self.session_action, self.pause_action):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self.quit_action)
        self._menu = menu
        self.open_action.triggered.connect(self.open_requested)
        self.session_action.triggered.connect(self.session_toggled)
        self.pause_action.triggered.connect(self.pause_toggled)
        self.quit_action.triggered.connect(self.quit_requested)
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)
        self.set_state("idle", in_session=False, paused=False, can_start=False)
        if self.available:
            self.icon.show()

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_requested.emit()

    def set_state(self, state: str, in_session: bool, paused: bool, can_start: bool) -> None:
        color = theme.state_color(state) if in_session else theme.current().muted
        self.icon.setIcon(dot_icon(color))
        self.icon.setToolTip(f"FocusBand: {state if in_session else 'no session'}")
        self.session_action.setText("End session" if in_session else "Start session")
        self.session_action.setEnabled(in_session or can_start)
        self.pause_action.setText("Resume" if paused else "Pause")
        self.pause_action.setEnabled(in_session)

    def message(self, title: str, text: str) -> None:
        if self.available:
            self.icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 4000)
