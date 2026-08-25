from __future__ import annotations

from dataclasses import dataclass

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

    # Optional pyqtgraph PlotWidget; kept as object to avoid hard dependency
    plot_widget: object | None = None


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

    layout.addWidget(plot_container, stretch=1)

    return TimeAnalysisDock(
        widget=widget,
        generate_button=generate_button,
        plot_container=plot_container,
        status_label=status_label,
        plot_widget=None,
    )
