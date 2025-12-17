from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qtpy.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass
class ScanBrowserDock:
    widget: QWidget
    folder_lineedit: QLineEdit
    browse_button: QPushButton
    scans_list: QListWidget

    def set_folder(self, folder: Path) -> None:
        self.folder_lineedit.setText(str(folder))

    def set_scans(self, scan_paths: list[Path]) -> None:
        self.scans_list.clear()
        for p in scan_paths:
            self.scans_list.addItem(p.name)


def create_scan_browser_dock() -> ScanBrowserDock:
    widget = QWidget()
    outer = QVBoxLayout(widget)

    outer.addWidget(QLabel("Scans"))

    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)

    folder_lineedit = QLineEdit()
    folder_lineedit.setReadOnly(True)
    browse_button = QPushButton("Browse folder…")

    row_layout.addWidget(folder_lineedit, stretch=1)
    row_layout.addWidget(browse_button)

    scans_list = QListWidget()
    scans_list.setSelectionMode(QAbstractItemView.SingleSelection)

    outer.addWidget(row)
    outer.addWidget(scans_list, stretch=1)

    return ScanBrowserDock(
        widget=widget,
        folder_lineedit=folder_lineedit,
        browse_button=browse_button,
        scans_list=scans_list,
    )
