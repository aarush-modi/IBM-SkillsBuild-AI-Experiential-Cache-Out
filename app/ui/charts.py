"""Shared pyqtgraph styling for the report and dashboard charts: no frame, faint grid, muted labels."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QFont

from app.ui.theme import Palette, qcolor


def plot_widget(min_height: int = 160) -> pg.PlotWidget:
    w = pg.PlotWidget()
    w.setMinimumHeight(min_height)
    w.setMouseEnabled(x=False, y=False)
    w.hideButtons()
    w.setMenuEnabled(False)
    w.setFrameShape(pg.QtWidgets.QFrame.Shape.NoFrame)
    return w


def style(chart: pg.PlotWidget, p: Palette) -> None:
    """Clear the chart and apply the theme. Call before adding items."""
    chart.clear()
    chart.setBackground(p.surface)
    item = chart.getPlotItem()
    font = QFont()
    font.setPixelSize(11)
    for name in ("left", "bottom"):
        ax = item.getAxis(name)
        ax.setPen(pg.mkPen(qcolor(p.border)))
        ax.setTextPen(pg.mkPen(p.faint))
        ax.setTickFont(font)
        ax.setStyle(tickLength=0, tickTextOffset=8)
    item.getAxis("left").setWidth(34)
    item.showGrid(x=False, y=True, alpha=0.7)  # grid lines take the axis pen, so they stay faint
    for name in ("left", "bottom"):
        item.getAxis(name).setZValue(-1)        # draw the grid behind bars and lines
    item.setContentsMargins(0, 4, 4, 0)
