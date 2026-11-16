"""Stats history dashboard (DESIGN §10, FR-15): focus minutes per day, distractions per hour of
work and average posture score, for the last 7 or 30 days. Data from app/logic/stats.py."""

from __future__ import annotations

import math

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from app.logic.stats import DayStats, PeriodStats
from app.ui import theme
from app.ui.report import mins, stat
from app.ui.widgets import card, label

PERIODS = (7, 30)


def _chart() -> pg.PlotWidget:
    w = pg.PlotWidget()
    w.setMinimumHeight(150)
    w.setMouseEnabled(x=False, y=False)
    w.hideButtons()
    w.setMenuEnabled(False)
    return w


def _ticks(days: list[DayStats]) -> list[tuple[int, str]]:
    if len(days) <= 7:
        return [(i, f"{d.day:%a %d}") for i, d in enumerate(days)]
    step = 5
    return [(i, f"{d.day:%d %b}") for i, d in enumerate(days) if (len(days) - 1 - i) % step == 0]


class DashboardPage(QWidget):
    back = Signal()
    period_changed = Signal(int)   # days

    def __init__(self) -> None:
        super().__init__()
        self.days = PERIODS[0]
        self.stats_row = QHBoxLayout()
        self.focus_chart = _chart()
        self.dist_chart = _chart()
        self.posture_chart = _chart()
        self.empty = label("No sessions in this period yet. Start one from Home.", "muted")

        group = QButtonGroup(self)
        switch = QHBoxLayout()
        self.period_buttons: dict[int, QPushButton] = {}
        for n in PERIODS:
            b = QPushButton(f"Last {n} days")
            b.setCheckable(True)
            group.addButton(b)
            switch.addWidget(b)
            self.period_buttons[n] = b
            b.clicked.connect(lambda _=False, n=n: self.period_changed.emit(n))
        self.period_buttons[self.days].setChecked(True)
        switch.addStretch()
        back = QPushButton("Back")
        back.clicked.connect(self.back)
        switch.addWidget(back)

        charts = QHBoxLayout()
        charts.addWidget(card(label("Focus minutes per day", "subtitle"), self.focus_chart), 1)
        charts.addWidget(card(label("Distractions per hour of work", "subtitle"), self.dist_chart), 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(14)
        layout.addWidget(label("Your progress", "title"))
        layout.addLayout(switch)
        layout.addLayout(self.stats_row)
        layout.addWidget(self.empty)
        layout.addLayout(charts, 1)
        layout.addWidget(card(label("Average posture score", "subtitle"), self.posture_chart), 1)

    def show_stats(self, st: PeriodStats) -> None:
        self.days = len(st.days)
        if self.days in self.period_buttons:
            self.period_buttons[self.days].setChecked(True)
        t = st.total
        while self.stats_row.count():
            item = self.stats_row.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        per_day = t.focus_s / self.days if self.days else 0
        rate = t.distractions_per_hour
        self.stats_row.addWidget(stat(mins(t.focus_s), f"focused · {mins(per_day)} a day on average"))
        self.stats_row.addWidget(stat(str(t.sessions), "sessions"))
        self.stats_row.addWidget(stat(f"{rate:.1f}" if rate is not None else "–", "distractions per hour"))
        self.stats_row.addWidget(stat(f"{t.posture_avg:.0f}" if t.posture_avg is not None else "–",
                                      "average posture score"))
        self.empty.setVisible(t.sessions == 0)
        self._draw(st.days)

    def _draw(self, days: list[DayStats]) -> None:
        p = theme.current()
        xs = list(range(len(days)))
        ticks = [_ticks(days)]
        for chart in (self.focus_chart, self.dist_chart, self.posture_chart):
            chart.clear()
            chart.setBackground(p.surface)
            item = chart.getPlotItem()
            for axis in ("left", "bottom"):
                ax = item.getAxis(axis)
                ax.setPen(pg.mkPen(p.border))
                ax.setTextPen(pg.mkPen(p.muted))
            item.getAxis("bottom").setTicks(ticks)
            item.setXRange(-0.6, len(days) - 0.4, padding=0)
        width = 0.6
        focus = [d.focus_s / 60 for d in days]
        self.focus_chart.addItem(pg.BarGraphItem(x=xs, height=focus, width=width, brush=p.accent, pen=None))
        self.focus_chart.getPlotItem().setYRange(0, max([*focus, 30]) * 1.1, padding=0)

        rate = [d.distractions_per_hour or 0.0 for d in days]
        self.dist_chart.addItem(pg.BarGraphItem(x=xs, height=rate, width=width, brush=p.pending, pen=None))
        self.dist_chart.getPlotItem().setYRange(0, max([*rate, 2]) * 1.1, padding=0)

        posture = [d.posture_avg if d.posture_avg is not None else math.nan for d in days]
        self.posture_chart.getPlotItem().setYRange(0, 100, padding=0.02)
        if any(not math.isnan(v) for v in posture):
            self.posture_chart.plot(xs, posture, pen=pg.mkPen(p.focused, width=2), connect="finite",
                                    symbol="o", symbolSize=6, symbolBrush=p.focused, symbolPen=None)
