from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget


@dataclass
class ReconstructionDock:
    widget: QWidget
    status_label: QLabel


def create_reconstruction_dock() -> ReconstructionDock:
    widget = QWidget()
    outer = QVBoxLayout(widget)

    outer.addWidget(QLabel("Reconstruction"))
    status_label = QLabel("(placeholder)")
    outer.addWidget(status_label, stretch=1)

    return ReconstructionDock(widget=widget, status_label=status_label)
