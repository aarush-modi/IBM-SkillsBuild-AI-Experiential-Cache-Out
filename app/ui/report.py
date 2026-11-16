"""End-of-session report page (DESIGN §10, FR-14): focus time against total time, distractions
by type with counts and minutes, posture score over the session, and the most common posture
issues with their tips. Built from stored rows by app/logic/report.py."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.logic.report import SessionReport
from app.ui import charts, theme
from app.ui.theme import qcolor
from app.ui.widgets import button, card, label, page_header, page_layout, plain, tile

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
    return tile(value, caption)


class ReportPage(QWidget):
    done = Signal()

    def __init__(self, bad_score: float) -> None:
        super().__init__()
        self.bad_score = bad_score
        self.when = label("", "lead")
        self.stats = QHBoxLayout()
        self.stats.setSpacing(12)
        self.distractions = QGridLayout()
        self.distractions.setHorizontalSpacing(16)
        self.distractions.setVerticalSpacing(14)
        self.issues = QVBoxLayout()
        self.issues.setSpacing(16)
        self.chart = charts.plot_widget(200)
        self.no_chart = label("Not enough posture data to chart.", "muted")
        done = button("Done", "primary")
        done.clicked.connect(self.done)

        left = QVBoxLayout()
        left.setSpacing(16)
        left.addWidget(card(label("Distractions", "subtitle"), plain(self.distractions), spacing=18))
        left.addWidget(card(label("Top posture issues", "subtitle"), plain(self.issues), spacing=18))
        left.addStretch()
        right = QVBoxLayout()
        right.addWidget(card(label("Posture over the session", "subtitle"), self.chart, self.no_chart,
                             spacing=14), 1)
        body = QHBoxLayout()
        body.setSpacing(16)
        body.addLayout(left, 2)
        body.addLayout(right, 3)

        layout = page_layout(self)
        layout.addLayout(page_header("Session report", self.when, done))
        layout.addLayout(self.stats)
        layout.addLayout(body, 1)

    def show_report(self, r: SessionReport) -> None:
        self.when.setText(f"{r.started_at:%A %d %B, %H:%M} · {mins(r.total_s)}"
                          + (f", including {mins(r.paused_s)} paused" if r.paused_s >= 30 else ""))
        _clear(self.stats)
        ratio = r.focus_ratio
        self.stats.addWidget(stat(f"{ratio * 100:.0f}%" if ratio is not None else "–",
                                  f"focused · {mins(r.focus_s)} of {mins(r.active_s)}"), 1)
        self.stats.addWidget(stat(str(r.distraction_count), "distractions"), 1)
        self.stats.addWidget(stat(str(r.alerts), "alerts"), 1)
        self.stats.addWidget(stat(f"{r.posture_avg:.0f}" if r.posture_avg is not None else "–",
                                  "average posture score"), 1)

        _clear(self.distractions)
        if not r.distractions:
            self.distractions.addWidget(label("None. Nicely done.", "muted"), 0, 0)
        for row, d in enumerate(r.distractions):
            self.distractions.addWidget(label(LABELS.get(d.label, d.label), wrap=False), row, 0)
            times = f"{d.count}×" if d.count != 1 else "once"
            self.distractions.addWidget(label(times, "muted", wrap=False), row, 1)
            right = label(mins(d.seconds), "strong", wrap=False)
            right.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.distractions.addWidget(right, row, 2)
        self.distractions.setColumnStretch(0, 1)

        _clear(self.issues)
        if not r.top_issues:
            self.issues.addWidget(label("No sustained posture problems.", "muted"))
        for i in r.top_issues:
            head = QHBoxLayout()
            head.addWidget(label(ISSUES.get(i.issue, i.issue), "strong", wrap=False))
            head.addStretch()
            head.addWidget(label(mins(i.seconds), "muted", wrap=False))
            block = QVBoxLayout()
            block.setSpacing(4)
            block.addLayout(head)
            block.addWidget(label(i.tip, "muted"))
            self.issues.addWidget(plain(block))

        self._chart(r)

    def _chart(self, r: SessionReport) -> None:
        p = theme.current()
        charts.style(self.chart, p)
        has_data = len(r.posture_points) >= 2
        self.chart.setVisible(has_data)
        self.no_chart.setVisible(not has_data)
        if not has_data:
            return
        xs = [x for x, _ in r.posture_points]
        ys = [y for _, y in r.posture_points]
        item = self.chart.getPlotItem()
        item.setLabel("bottom", "minutes", color=p.faint)
        item.setYRange(0, 100, padding=0.02)
        item.setXRange(0, max(xs), padding=0.02)
        self.chart.addItem(pg.InfiniteLine(pos=self.bad_score, angle=0,
                                           pen=pg.mkPen(p.pending, width=1, style=Qt.PenStyle.DashLine)))
        self.chart.plot(xs, ys, pen=pg.mkPen(p.accent, width=2), fillLevel=0,
                        brush=qcolor(p.accent, 0.10))


def _clear(layout: QHBoxLayout | QVBoxLayout | QGridLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget() if item is not None else None
        if isinstance(w, (QWidget, QLabel)):
            w.deleteLater()
