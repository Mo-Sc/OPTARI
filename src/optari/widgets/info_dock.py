from __future__ import annotations

from dataclasses import dataclass
from html import escape

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


@dataclass
class InfoDock:
    widget: QWidget
    label: QLabel
    metadata_button: QPushButton

    def set_message(self, text: str) -> None:
        self.label.setText(text)
        line_height = 4 * self.label.fontMetrics().lineSpacing()
        wrapped_height = self.label.heightForWidth(self.label.width())
        self.label.setMinimumHeight(max(line_height, wrapped_height))

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        html_rows = "".join(
            f"<tr bgcolor='{('#2b2b2b' if index % 2 == 0 else '#363636')}'>"
            "<td><b>"
            f"{escape(label)}"
            "</b></td><td>"
            f"{escape(value)}"
            "</td></tr>"
            for index, (label, value) in enumerate(rows)
        )
        self.label.setText(
            "<table cellpadding='4' cellspacing='0' width='100%'>"
            f"{html_rows}"
            "</table>"
        )
        self.label.setMinimumHeight(0)


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
    label.setStyleSheet("color: white; line-height: 1.25em;")
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QScrollArea.NoFrame)
    scroll_area.setWidget(label)
    layout.addWidget(header)
    layout.addWidget(scroll_area)
    return InfoDock(widget=widget, label=label, metadata_button=metadata_button)
