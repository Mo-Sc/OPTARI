from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


@dataclass
class TimeAnalysisDock:
    widget: QWidget
    generate_button: QPushButton
    plot_container: QWidget
    status_label: QLabel

    # Optional pyqtgraph PlotWidget; kept as object to avoid hard dependency
    plot_widget: object | None = None
    # Movable vertical line for frame scrubbing
    # scrub_line: object | None = None


def create_time_analysis_dock() -> TimeAnalysisDock:
    widget = QWidget()
    layout = QVBoxLayout(widget)

    status_label = QLabel("Click 'Refresh' to compute ROI means over time.")
    generate_button = QPushButton("Refresh")

    plot_container = QWidget()
    plot_layout = QVBoxLayout(plot_container)
    plot_layout.setContentsMargins(0, 0, 0, 0)

    layout.addWidget(status_label)
    layout.addWidget(generate_button)
    layout.addWidget(plot_container, stretch=1)

    return TimeAnalysisDock(
        widget=widget,
        generate_button=generate_button,
        plot_container=plot_container,
        status_label=status_label,
        plot_widget=None,
    )
