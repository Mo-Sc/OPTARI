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
    spectral_curve: pg.PlotDataItem
    frame_curve: pg.PlotDataItem
    # Lowest point of each plotted curve
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
        "Score spectral and frame-to-frame motion for every frame of the scan's ultrasound"
    )

    plot = pg.PlotWidget()
    plot.showGrid(x=True, y=True)
    plot.setLabel("bottom", "Frame")
    plot.setLabel("left", "Motion score (0 = stillest)")
    plot.setToolTip(
        "Spectral: Movement during a frame's wavelength set, which corrupts "
        "unmixing. Frame-to-frame: the image changed from the previous and next frame. "
        "Each is scaled to 0-1 within the scan, so it shows where "
        "motion happens, but are not comparable between scans."
    )
    plot.addLegend()
    spectral_curve = plot.plot(
        pen=pg.mkPen((100, 180, 255), width=2),
        symbol="o",
        symbolSize=5,
        symbolBrush=(100, 180, 255),
        name="Spectral",
    )
    frame_curve = plot.plot(
        pen=pg.mkPen((255, 160, 60), width=2),
        symbol="o",
        symbolSize=5,
        symbolBrush=(255, 160, 60),
        name="Frame-to-frame",
    )
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
        spectral_curve=spectral_curve,
        frame_curve=frame_curve,
        stillest=stillest,
        frame_line=frame_line,
    )
