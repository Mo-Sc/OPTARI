from __future__ import annotations

from dataclasses import dataclass

import pyqtgraph as pg
from qtpy.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from .dock_helpers import create_bottom_dock_header


@dataclass
class MotionDock:
    """Motion score of every frame of the loaded scan, scored on its ultrasound."""

    widget: QWidget
    refresh_button: QPushButton
    status_label: QLabel
    plot: pg.PlotWidget
    curve: pg.PlotDataItem
    stillest: pg.ScatterPlotItem
    # Follows the viewer's frame; dragging it moves the viewer to that frame.
    frame_line: pg.InfiniteLine


def create_motion_dock() -> MotionDock:
    widget = QWidget()
    layout = QVBoxLayout(widget)

    status_label, refresh_button = create_bottom_dock_header(
        layout, status_text="Click 'Refresh' to score motion per frame."
    )
    refresh_button.setToolTip(
        "Score inter-wavelength motion for every frame of the scan's ultrasound"
    )

    plot = pg.PlotWidget()
    plot.showGrid(x=True, y=True)
    plot.setLabel("bottom", "Frame")
    plot.setLabel("left", "Motion score (0 = stillest)")
    curve = plot.plot(pen=pg.mkPen(width=2), symbol="o", symbolSize=5)
    stillest = pg.ScatterPlotItem(
        size=12, brush=pg.mkBrush("g"), pen=pg.mkPen("w")
    )
    plot.addItem(stillest)
    frame_line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("y"))
    frame_line.setToolTip("Current frame, drag to move the viewer")
    frame_line.hide()
    plot.addItem(frame_line)
    layout.addWidget(plot, stretch=1)

    return MotionDock(
        widget=widget,
        refresh_button=refresh_button,
        status_label=status_label,
        plot=plot,
        curve=curve,
        stillest=stillest,
        frame_line=frame_line,
    )
