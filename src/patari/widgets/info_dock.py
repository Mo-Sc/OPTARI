from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


@dataclass
class InfoDock:
    widget: QWidget
    label: QLabel
    metadata_button: QPushButton


def create_info_dock() -> InfoDock:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)

    header = QWidget()
    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(0, 0, 0, 0)
    title = QLabel("Active Slice Info")
    title.setStyleSheet("font-weight: 600;")
    metadata_button = QPushButton("Metadata")
    metadata_button.setToolTip("View metadata for the selected layer and scan")
    metadata_button.setEnabled(False)
    header_layout.addWidget(title)
    header_layout.addStretch()
    header_layout.addWidget(metadata_button)

    label = QLabel("")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setStyleSheet("color: palette(text); line-height: 1.25em;")
    layout.addWidget(header)
    layout.addWidget(label)
    layout.addStretch()
    return InfoDock(widget=widget, label=label, metadata_button=metadata_button)
