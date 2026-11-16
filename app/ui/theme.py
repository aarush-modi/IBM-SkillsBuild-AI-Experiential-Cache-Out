"""Colours and the application stylesheet (DESIGN §10). Follows the system light or dark mode.

One accent colour; state colours for the focus chip and tray icon. Widgets pick up roles via
objectName (e.g. "primary", "card", "chip") so pages don't hard-code colours.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    focused: str
    pending: str
    distracted: str
    paused: str
    tip_bg: str
    warn_bg: str


LIGHT = Palette(
    bg="#f5f6f8", surface="#ffffff", border="#e2e5ea", text="#1d2330", muted="#6b7280",
    accent="#3b6fd8", accent_text="#ffffff",
    focused="#2e9e5b", pending="#d9902b", distracted="#d64545", paused="#8a919e",
    tip_bg="#eef3ff", warn_bg="#fff4e0",
)
DARK = Palette(
    bg="#15181e", surface="#1e222a", border="#2e333d", text="#e8eaef", muted="#9aa1ad",
    accent="#6b95ec", accent_text="#0e1116",
    focused="#4cc282", pending="#e6a845", distracted="#ef6b6b", paused="#7d8592",
    tip_bg="#1f2a40", warn_bg="#3a2e1a",
)


def current() -> Palette:
    scheme = QGuiApplication.styleHints().colorScheme()
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


def state_color(state: str, p: Palette | None = None) -> str:
    p = p or current()
    return {
        "focused": p.focused, "pending": p.pending, "distracted": p.distracted,
    }.get(state, p.paused)


def stylesheet(p: Palette) -> str:
    return f"""
    QWidget {{ background: {p.bg}; color: {p.text}; font-size: 14px; }}
    QDialog, QMessageBox {{ background: {p.bg}; }}
    QLabel {{ background: transparent; }}
    QLabel#muted {{ color: {p.muted}; }}
    QLabel#title {{ font-size: 26px; font-weight: 600; }}
    QLabel#subtitle {{ font-size: 17px; font-weight: 600; }}
    QLabel#timer {{ font-size: 40px; font-weight: 600; }}
    QLabel#big {{ font-size: 22px; font-weight: 600; }}
    QFrame#card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
    QFrame#card QLabel, QFrame#card QCheckBox, QWidget#plain {{ background: transparent; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border: 1px solid {p.muted}; border-radius: 4px; background: {p.surface};
    }}
    QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}
    QLabel#preview {{ background: #000000; border-radius: 12px; color: {p.muted}; }}
    QLabel#tip {{ background: {p.tip_bg}; border-radius: 8px; padding: 10px 12px; }}
    QLabel#warn {{ background: {p.warn_bg}; border-radius: 8px; padding: 10px 12px; }}
    QPushButton {{
        background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px;
        padding: 8px 16px; min-height: 20px;
    }}
    QPushButton:hover {{ border-color: {p.accent}; }}
    QPushButton:disabled {{ color: {p.muted}; }}
    QPushButton#primary {{
        background: {p.accent}; color: {p.accent_text}; border: none; font-weight: 600;
        padding: 10px 22px;
    }}
    QPushButton#primary:disabled {{ background: {p.border}; color: {p.muted}; }}
    QPushButton#danger {{ color: {p.distracted}; }}
    QProgressBar {{
        background: {p.border}; border: none; border-radius: 4px; height: 8px; text-align: center;
    }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}
    QSpinBox, QComboBox {{
        background: {p.surface}; border: 1px solid {p.border}; border-radius: 6px; padding: 4px 8px;
    }}
    QGroupBox {{
        border: 1px solid {p.border}; border-radius: 10px; margin-top: 14px; padding: 12px 10px 8px;
        font-weight: 600;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
    """


def chip_style(state: str, p: Palette | None = None) -> str:
    color = state_color(state, p)
    return (
        f"background: {color}; color: #ffffff; border-radius: 12px; padding: 4px 12px;"
        " font-weight: 600; font-size: 13px;"
    )
