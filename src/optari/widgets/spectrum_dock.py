from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtWidgets import QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .dock_helpers import (
    create_bottom_dock_header,
    create_bottom_plot_strip,
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

    status_label, refresh_button = create_bottom_dock_header(
        layout,
        status_text="Click 'Refresh' to compute ROI spectra.",
    )
    refresh_button.setToolTip(
        "Recompute per-ROI mean-intensity spectra across channels for the current frame"
    )
    scroll_area, plots_container = create_bottom_plot_strip()

    layout.addWidget(scroll_area, stretch=1)

    return SpectrumDock(
        widget=widget,
        refresh_button=refresh_button,
        scroll_area=scroll_area,
        plots_container=plots_container,
        status_label=status_label,
    )
