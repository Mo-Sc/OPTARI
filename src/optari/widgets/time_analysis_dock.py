from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pyqtgraph as pg
from qtpy.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from .dock_helpers import create_bottom_dock_header


@dataclass
class TimeAnalysisDock:
    """The Temporal dock: one feature of each ROI plotted over the frames."""

    widget: QWidget
    refresh_button: QPushButton
    status_label: QLabel
    # One plot for the dock's lifetime, redrawn on every refresh.
    plot_widget: pg.PlotWidget
    # Follows the viewer's frame, dragging it moves the viewer to that frame.
    frame_line: pg.InfiniteLine

    plotted_frames: np.ndarray = field(
        default_factory=lambda: np.empty(0, dtype=int)
    )
    plotted_x: np.ndarray = field(default_factory=lambda: np.empty(0))

    def clear(self) -> None:
        """Remove every curve and the status text, and forget what was plotted."""
        self.plot_widget.clear()
        self.plotted_frames = np.empty(0, dtype=int)
        self.plotted_x = np.empty(0)
        self.frame_line.setVisible(False)
        self.status_label.setText("")


def create_time_analysis_dock() -> TimeAnalysisDock:
    widget = QWidget()
    layout = QVBoxLayout(widget)

    status_label, refresh_button = create_bottom_dock_header(
        layout,
        status_text="Click 'Refresh' to plot the selected feature over time.",
    )
    refresh_button.setToolTip(
        "Recompute the selected feature over time for the active ROI(s), using the "
        "Feature setting in the Annotation dock"
    )
    plot_widget = pg.PlotWidget()
    plot_widget.showGrid(x=True, y=True)
    frame_line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("y"))
    frame_line.setToolTip("Current frame, drag to move the viewer")

    layout.addWidget(plot_widget, stretch=1)

    return TimeAnalysisDock(
        widget=widget,
        refresh_button=refresh_button,
        status_label=status_label,
        plot_widget=plot_widget,
        frame_line=frame_line,
    )
