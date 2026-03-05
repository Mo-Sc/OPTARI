from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget


@dataclass
class UnmixingDock:
    widget: QWidget
    status_label: QLabel


def create_unmixing_dock() -> UnmixingDock:
    widget = QWidget()
    outer = QVBoxLayout(widget)

    outer.addWidget(QLabel("Unmixing"))
    status_label = QLabel("(placeholder)")
    outer.addWidget(status_label, stretch=1)

    return UnmixingDock(widget=widget, status_label=status_label)
