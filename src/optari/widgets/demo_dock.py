"""Template dock for a new feature, see "Adding a feature" in the developer guide.

To activate, uncommented in OptariController`.
"""

from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


@dataclass
class DemoDock:
    """Widget references only. The respective controller handles the logic."""

    widget: QWidget
    status_label: QLabel
    run_button: QPushButton


def create_demo_dock() -> DemoDock:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    status_label = QLabel("Load a scan to run the demo.")
    status_label.setWordWrap(True)
    run_button = QPushButton("Run Demo")
    run_button.setToolTip(
        "Walk over the scan's frames in the background, change nothing"
    )
    layout.addWidget(status_label)
    layout.addWidget(run_button)
    layout.addStretch()
    return DemoDock(widget=widget, status_label=status_label, run_button=run_button)
