from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pyqtgraph as pg
from qtpy.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from .dock_helpers import (
    create_bottom_dock_header,
    create_bottom_single_plot_container,
)


@dataclass
class TimeAnalysisDock:
    widget: QWidget
    generate_button: QPushButton
    plot_container: QWidget
    status_label: QLabel
    # Follows the viewer's frame, dragging it moves the viewer to that frame.
    frame_line: pg.InfiniteLine

    # Created by AnalysisController on the first plot.
    plot_widget: pg.PlotWidget | None = None
    plotted_frames: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=int)
    )
    plotted_x: np.ndarray = field(default_factory=lambda: np.empty(0))


def create_time_analysis_dock() -> TimeAnalysisDock:
    widget = QWidget()
    layout = QVBoxLayout(widget)

    status_label, generate_button = create_bottom_dock_header(
        layout,
        status_text="Click 'Refresh' to compute ROI means over time.",
    )
    generate_button.setToolTip(
        "Recompute the selected feature over time for the active ROI(s), using the "
        "Feature setting in the Annotation dock"
    )
    plot_container = create_bottom_single_plot_container()
    frame_line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("y"))
    frame_line.setToolTip("Current frame, drag to move the viewer")

    layout.addWidget(plot_container, stretch=1)

    return TimeAnalysisDock(
        widget=widget,
        generate_button=generate_button,
        plot_container=plot_container,
        status_label=status_label,
        frame_line=frame_line,
    )
