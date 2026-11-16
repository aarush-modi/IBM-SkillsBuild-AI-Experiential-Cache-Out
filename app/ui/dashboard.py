"""Stats history dashboard (DESIGN §10, FR-15): focus minutes per day, distractions per hour of
work and average posture score, for the last 7 or 30 days. Data from app/logic/stats.py."""

from __future__ import annotations

import math

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget

from app.logic.stats import DayStats, PeriodStats
from app.ui import charts, theme
from app.ui.report import mins, stat
from app.ui.theme import qcolor
from app.ui.widgets import Segmented, button, card, label, page_header, page_layout

PERIODS = (7, 30)


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
        self.stats_row.setSpacing(12)
        self.focus_chart = charts.plot_widget(150)
        self.dist_chart = charts.plot_widget(150)
        self.posture_chart = charts.plot_widget(150)
        self.empty = label("No sessions in this period yet. Start one from Home.", "muted")

        self.period = Segmented([(f"Last {n} days", n) for n in PERIODS], self.days)
        self.period_buttons = self.period.buttons
        self.period.changed.connect(lambda n: self.period_changed.emit(int(n)))
        back = button("←  Home", "ghost")
        back.clicked.connect(self.back)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(16)
        charts_row.addWidget(card(label("Focus minutes per day", "subtitle"), self.focus_chart, spacing=14), 1)
        charts_row.addWidget(card(label("Distractions per hour of work", "subtitle"), self.dist_chart,
                                  spacing=14), 1)
        layout = page_layout(self)
        layout.addLayout(page_header("Your progress", None, self.period, back))
        layout.addLayout(self.stats_row)
        layout.addWidget(self.empty)
        layout.addLayout(charts_row, 1)
        layout.addWidget(card(label("Average posture score", "subtitle"), self.posture_chart, spacing=14), 1)

    def show_stats(self, st: PeriodStats) -> None:
        self.days = len(st.days)
        self.period.set_current(self.days)
        t = st.total
        while self.stats_row.count():
            item = self.stats_row.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        per_day = t.focus_s / self.days if self.days else 0
        rate = t.distractions_per_hour
        self.stats_row.addWidget(stat(mins(t.focus_s), f"focused · {mins(per_day)} a day"), 1)
        self.stats_row.addWidget(stat(str(t.sessions), "sessions"), 1)
        self.stats_row.addWidget(stat(f"{rate:.1f}" if rate is not None else "–", "distractions per hour"), 1)
        self.stats_row.addWidget(stat(f"{t.posture_avg:.0f}" if t.posture_avg is not None else "–",
                                      "average posture score"), 1)
        self.empty.setVisible(t.sessions == 0)
        self._draw(st.days)

    def _draw(self, days: list[DayStats]) -> None:
        p = theme.current()
        xs = list(range(len(days)))
        ticks = [_ticks(days)]
        for chart in (self.focus_chart, self.dist_chart, self.posture_chart):
            charts.style(chart, p)
            item = chart.getPlotItem()
            item.getAxis("bottom").setTicks(ticks)
            item.setXRange(-0.6, len(days) - 0.4, padding=0)
        width = 0.55
        focus = [d.focus_s / 60 for d in days]
        self.focus_chart.addItem(pg.BarGraphItem(x=xs, height=focus, width=width, brush=p.accent, pen=None))
        self.focus_chart.getPlotItem().setYRange(0, max([*focus, 30]) * 1.1, padding=0)

        rate = [d.distractions_per_hour or 0.0 for d in days]
        self.dist_chart.addItem(pg.BarGraphItem(x=xs, height=rate, width=width, brush=qcolor(p.pending, 0.85), pen=None))
        self.dist_chart.getPlotItem().setYRange(0, max([*rate, 2]) * 1.1, padding=0)

        posture = [d.posture_avg if d.posture_avg is not None else math.nan for d in days]
        self.posture_chart.getPlotItem().setYRange(0, 100, padding=0.02)
        if any(not math.isnan(v) for v in posture):
            self.posture_chart.plot(xs, posture, pen=pg.mkPen(p.focused, width=2), connect="finite",
                                    symbol="o", symbolSize=7, symbolBrush=p.surface,
                                    symbolPen=pg.mkPen(p.focused, width=2))
