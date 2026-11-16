"""Colours and the application stylesheet (DESIGN §10). Follows the system light or dark mode.

One calm blue accent, soft neutral surfaces and state colours for the focus pill and tray icon.
Widgets pick up roles via objectName (e.g. "primary", "card", "eyebrow") so pages don't
hard-code colours.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication

from app.paths import resource_root

ICONS = resource_root() / "app" / "ui" / "icons"


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    subtle: str       # hover and inset fills
    border: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_hover: str
    accent_text: str
    focused: str
    pending: str
    distracted: str
    paused: str
    tip_bg: str
    warn_bg: str


LIGHT = Palette(
    bg="#f6f7f9", surface="#ffffff", subtle="#f0f2f5", border="#e5e7eb", text="#151b26",
    muted="#667085", faint="#98a2b3",
    accent="#3f6fe0", accent_hover="#3462cc", accent_text="#ffffff",
    focused="#1f9d5c", pending="#d0861a", distracted="#d64545", paused="#8a94a6",
    tip_bg="#eef3fe", warn_bg="#fff4e2",
)
DARK = Palette(
    bg="#111318", surface="#1a1d24", subtle="#232731", border="#2b303b", text="#e9ecf2",
    muted="#9aa3b2", faint="#6b7383",
    accent="#7096f0", accent_hover="#86a7f4", accent_text="#0d1117",
    focused="#45c07f", pending="#e8a64a", distracted="#ef6d6d", paused="#7e8796",
    tip_bg="#1b2438", warn_bg="#33291a",
)


def current() -> Palette:
    scheme = QGuiApplication.styleHints().colorScheme()
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


def state_color(state: str, p: Palette | None = None) -> str:
    p = p or current()
    return {
        "focused": p.focused, "pending": p.pending, "distracted": p.distracted,
    }.get(state, p.paused)


def rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:.2f})"


def qcolor(color: str, alpha: float = 1.0) -> QColor:
    c = QColor(color)
    c.setAlphaF(alpha)
    return c


def _icon(name: str) -> str:
    return (ICONS / name).as_posix()


def stylesheet(p: Palette) -> str:
    return f"""
    QWidget {{ color: {p.text}; font-size: 14px; }}
    QMainWindow, QDialog, QMessageBox {{ background: {p.bg}; }}
    QLabel {{ background: transparent; }}
    QLabel#muted {{ color: {p.muted}; }}
    QLabel#faint {{ color: {p.faint}; font-size: 13px; }}
    QLabel#eyebrow {{ color: {p.muted}; font-size: 11px; font-weight: 600; }}
    QLabel#brand {{ font-size: 16px; font-weight: 600; }}
    QLabel#title {{ font-size: 28px; font-weight: 600; }}
    QLabel#lead {{ color: {p.muted}; font-size: 15px; }}
    QLabel#subtitle {{ font-size: 16px; font-weight: 600; }}
    QLabel#strong {{ font-weight: 600; }}
    QLabel#timer {{ font-size: 44px; font-weight: 600; }}
    QLabel#stat {{ font-size: 28px; font-weight: 600; }}
    QLabel#big {{ font-size: 22px; font-weight: 600; }}

    QFrame#card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 16px; }}
    QFrame#tile {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px; }}
    QFrame#divider {{ background: {p.border}; border: none; max-height: 1px; min-height: 1px; }}
    QFrame#segmented {{ background: {p.subtle}; border: none; border-radius: 10px; }}

    QLabel#preview {{ background: transparent; color: {p.muted}; }}
    QLabel#preview[empty="true"] {{
        background: {p.subtle}; border: 1px solid {p.border}; border-radius: 16px;
    }}
    QLabel#tip {{
        background: {p.tip_bg}; border-radius: 12px; padding: 12px 16px;
    }}
    QLabel#warn {{
        background: {p.warn_bg}; border-radius: 12px; padding: 12px 16px;
    }}

    QPushButton {{
        background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px;
        padding: 9px 18px; min-height: 18px; font-weight: 500;
    }}
    QPushButton:hover {{ background: {p.subtle}; }}
    QPushButton:pressed {{ background: {p.border}; }}
    QPushButton:disabled {{ color: {p.faint}; background: {p.surface}; }}
    QPushButton#primary {{
        background: {p.accent}; color: {p.accent_text}; border: none; font-weight: 600;
        padding: 11px 24px;
    }}
    QPushButton#primary:hover {{ background: {p.accent_hover}; }}
    QPushButton#primary:disabled {{ background: {p.subtle}; color: {p.faint}; }}
    QPushButton#ghost {{ background: transparent; border: none; color: {p.muted}; padding: 8px 12px; }}
    QPushButton#ghost:hover {{ background: {p.subtle}; color: {p.text}; }}
    QPushButton#link {{
        background: transparent; border: none; color: {p.accent}; padding: 4px 0; font-weight: 600;
    }}
    QPushButton#link:hover {{ color: {p.accent_hover}; }}
    QPushButton#danger {{ color: {p.distracted}; }}
    QPushButton#danger:hover {{ background: {rgba(p.distracted, 0.08)}; border-color: {rgba(p.distracted, 0.35)}; }}
    QFrame#segmented QPushButton {{
        background: transparent; border: none; border-radius: 8px; padding: 6px 14px; color: {p.muted};
    }}
    QFrame#segmented QPushButton:hover {{ color: {p.text}; }}
    QFrame#segmented QPushButton:checked {{
        background: {p.surface}; color: {p.text}; font-weight: 600; border: 1px solid {p.border};
    }}

    QCheckBox {{ spacing: 10px; background: transparent; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px; border: 1.5px solid {p.faint}; border-radius: 5px; background: {p.surface};
    }}
    QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
    QCheckBox::indicator:checked {{
        background: {p.accent}; border-color: {p.accent}; image: url("{_icon('check.svg')}");
    }}
    QCheckBox:disabled {{ color: {p.faint}; }}

    QProgressBar {{
        background: {p.subtle}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px;
        text-align: center;
    }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}

    QSpinBox, QComboBox {{
        background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px;
        padding: 6px 10px; min-height: 20px; min-width: 96px;
        selection-background-color: {rgba(p.accent, 0.25)}; selection-color: {p.text};
    }}
    QSpinBox:hover, QComboBox:hover {{ border-color: {p.faint}; }}
    QSpinBox:focus, QComboBox:focus {{ border-color: {p.accent}; }}
    QSpinBox:disabled {{ color: {p.faint}; background: {p.subtle}; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: border; width: 22px; border: none; background: transparent;
    }}
    QSpinBox::up-button {{ subcontrol-position: top right; margin-top: 3px; margin-right: 3px; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 3px; margin-right: 3px; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {p.subtle}; border-radius: 4px; }}
    QSpinBox::up-arrow {{ image: url("{_icon('chevron-up.svg')}"); width: 10px; height: 10px; }}
    QSpinBox::down-arrow {{ image: url("{_icon('chevron-down.svg')}"); width: 10px; height: 10px; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url("{_icon('chevron-down.svg')}"); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{
        background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 4px;
        selection-background-color: {rgba(p.accent, 0.15)}; selection-color: {p.text}; outline: none;
    }}

    QTabWidget::pane {{ border: none; border-top: 1px solid {p.border}; top: -1px; }}
    QTabWidget::tab-bar {{ left: 0px; }}
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{
        background: transparent; color: {p.muted}; padding: 10px 2px; margin-right: 22px;
        border: none; border-bottom: 2px solid transparent; font-weight: 500;
    }}
    QTabBar::tab:hover {{ color: {p.text}; }}
    QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.accent}; font-weight: 600; }}

    QToolTip {{
        background: {p.surface}; color: {p.text}; border: 1px solid {p.border}; border-radius: 6px;
        padding: 6px 8px;
    }}
    """


def chip_style(state: str, p: Palette | None = None) -> str:
    """The focus-state pill: a soft tint of the state colour with the colour as text."""
    color = state_color(state, p)
    return (
        f"background: {rgba(color, 0.14)}; color: {color}; border-radius: 14px; padding: 6px 14px;"
        " font-weight: 600; font-size: 13px;"
    )
