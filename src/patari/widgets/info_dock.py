from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget


@dataclass
class InfoDock:
    widget: QWidget
    label: QLabel


def create_info_dock() -> InfoDock:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.addWidget(QLabel("<b>Slice Info:</b>"))
    label = QLabel("")
    layout.addWidget(label)
    layout.addStretch()
    return InfoDock(widget=widget, label=label)
