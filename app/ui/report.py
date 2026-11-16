"""End-of-session report page (DESIGN §10, FR-14): focus time against total time, distractions
by type with counts and minutes, posture score over the session, and the most common posture
issues with their tips. Built from stored rows by app/logic/report.py."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.logic.report import SessionReport
from app.ui import theme
from app.ui.widgets import card, label

TOP_ISSUES = 3  # DESIGN §10: "the 3 most common posture issues"

LABELS = {
    "phone": "Phone", "desk_object": "Desk object", "looking_away": "Looking away",
    "window": "Looking out the window", "away": "Away from desk",
}
ISSUES = {
    "slouching": "Slouching", "leaning_in": "Leaning in", "neck_down": "Neck bent down",
    "head_tilt": "Head tilt", "uneven_shoulders": "Uneven shoulders",
}


def mins(seconds: float) -> str:
    m = int(round(seconds / 60))
    if m >= 60:
        return f"{m // 60} h" + (f" {m % 60} min" if m % 60 else "")
    return f"{m} min" if m else "under 1 min"


def stat(value: str, caption: str) -> QWidget:
    return card(label(value, "big", wrap=False), label(caption, "muted"), spacing=2)


class ReportPage(QWidget):
    done = Signal()

    def __init__(self, bad_score: float) -> None:
        super().__init__()
        self.bad_score = bad_score
        self.heading = label("Session report", "title")
        self.when = label("", "muted")
        self.stats = QHBoxLayout()
        self.distractions = QGridLayout()
        self.issues = QVBoxLayout()
        self.chart = pg.PlotWidget()
        self.chart.setMinimumHeight(180)
        self.chart.setMouseEnabled(x=False, y=False)
        self.chart.hideButtons()
        self.chart.setMenuEnabled(False)
        self.no_chart = label("Not enough posture data to chart.", "muted")
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(self.done)

        dist_box = QWidget()
        dist_box.setObjectName("plain")
        dist_box.setLayout(self.distractions)
        issues_box = QWidget()
        issues_box.setObjectName("plain")
        issues_box.setLayout(self.issues)
        left = QVBoxLayout()
        left.addWidget(card(label("Distractions", "subtitle"), dist_box))
        left.addStretch()
        right = QVBoxLayout()
        right.addWidget(card(label("Posture over the session", "subtitle"), self.chart, self.no_chart))
        right.addWidget(card(label("Top posture issues", "subtitle"), issues_box))
        right.addStretch()
        body = QHBoxLayout()
        body.addLayout(left, 2)
        body.addLayout(right, 3)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(done)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(14)
        layout.addWidget(self.heading)
        layout.addWidget(self.when)
        layout.addLayout(self.stats)
        layout.addLayout(body, 1)
        layout.addLayout(buttons)

    def show_report(self, r: SessionReport) -> None:
        self.when.setText(f"{r.started_at:%A %d %B, %H:%M} · {mins(r.total_s)}"
                          + (f", including {mins(r.paused_s)} paused" if r.paused_s >= 30 else ""))
        _clear(self.stats)
        ratio = r.focus_ratio
        self.stats.addWidget(stat(f"{ratio * 100:.0f}%" if ratio is not None else "–",
                                  f"focused: {mins(r.focus_s)} of {mins(r.active_s)}"))
        self.stats.addWidget(stat(str(r.distraction_count), "distractions"))
        self.stats.addWidget(stat(str(r.alerts), "alerts"))
        self.stats.addWidget(stat(f"{r.posture_avg:.0f}" if r.posture_avg is not None else "–",
                                  "average posture score"))

        _clear(self.distractions)
        if not r.distractions:
            self.distractions.addWidget(label("None. Nicely done.", "muted"), 0, 0)
        for row, d in enumerate(r.distractions):
            self.distractions.addWidget(label(LABELS.get(d.label, d.label), wrap=False), row, 0)
            times = f"{d.count}×" if d.count != 1 else "once"
            self.distractions.addWidget(label(times, "muted", wrap=False), row, 1)
            right = label(mins(d.seconds), wrap=False)
            right.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.distractions.addWidget(right, row, 2)
        self.distractions.setColumnStretch(0, 1)

        _clear(self.issues)
        if not r.top_issues:
            self.issues.addWidget(label("No sustained posture problems.", "muted"))
        for i in r.top_issues:
            self.issues.addWidget(label(f"{ISSUES.get(i.issue, i.issue)} · {mins(i.seconds)}", wrap=False))
            self.issues.addWidget(label(i.tip, "muted"))

        self._chart(r)

    def _chart(self, r: SessionReport) -> None:
        p = theme.current()
        self.chart.clear()
        self.chart.setBackground(p.surface)
        has_data = len(r.posture_points) >= 2
        self.chart.setVisible(has_data)
        self.no_chart.setVisible(not has_data)
        if not has_data:
            return
        xs = [x for x, _ in r.posture_points]
        ys = [y for _, y in r.posture_points]
        item = self.chart.getPlotItem()
        for axis in ("left", "bottom"):
            ax = item.getAxis(axis)
            ax.setPen(pg.mkPen(p.border))
            ax.setTextPen(pg.mkPen(p.muted))
        item.setLabel("bottom", "minutes")
        item.setYRange(0, 100, padding=0.02)
        item.setXRange(0, max(xs), padding=0.02)
        self.chart.addItem(pg.InfiniteLine(pos=self.bad_score, angle=0,
                                           pen=pg.mkPen(p.pending, width=1, style=Qt.PenStyle.DashLine)))
        self.chart.plot(xs, ys, pen=pg.mkPen(p.accent, width=2))


def _clear(layout: QHBoxLayout | QVBoxLayout | QGridLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget() if item is not None else None
        if isinstance(w, (QWidget, QLabel)):
            w.deleteLater()
