from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


@dataclass
class SpectrumDock:
    widget: QWidget
    refresh_button: QPushButton
    scroll_area: QScrollArea
    plots_container: QWidget
    status_label: QLabel


def create_spectrum_dock() -> SpectrumDock:
    widget = QWidget()
    layout = QVBoxLayout(widget)

    status_label = QLabel("Click 'Refresh' to compute ROI spectra.")
    refresh_button = QPushButton("Refresh")

    plots_container = QWidget()
    plots_layout = QHBoxLayout(plots_container)
    plots_layout.setContentsMargins(0, 0, 0, 0)
    plots_layout.setSpacing(8)

    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setWidget(plots_container)

    layout.addWidget(status_label)
    layout.addWidget(refresh_button)
    layout.addWidget(scroll_area, stretch=1)

    return SpectrumDock(
        widget=widget,
        refresh_button=refresh_button,
        scroll_area=scroll_area,
        plots_container=plots_container,
        status_label=status_label,
    )
