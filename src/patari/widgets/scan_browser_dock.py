from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from patari.controllers.scan_controller import ScanInfo


@dataclass
class ScanBrowserDock:
    widget: QWidget
    folder_lineedit: QLineEdit
    browse_button: QPushButton
    scans_list: QListWidget
    hdf5_button: QPushButton

    def set_folder(self, folder: Path) -> None:
        self.folder_lineedit.setText(str(folder))

    def set_scans(self, scan_items: list[tuple[Path, ScanInfo]]) -> None:
        self.scans_list.clear()
        for path, info in scan_items:
            display = f"{path.name} ({info.internal_name})" if info.internal_name else path.name
            item = QListWidgetItem(display)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.scans_list.addItem(item)


def create_scan_browser_dock() -> ScanBrowserDock:
    widget = QWidget()
    # widget.setMinimumHeight(400)
    outer = QVBoxLayout(widget)

    outer.addWidget(QLabel("Scan Browser"))

    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)

    folder_lineedit = QLineEdit()
    folder_lineedit.setReadOnly(True)
    browse_button = QPushButton("Open Study")

    row_layout.addWidget(folder_lineedit, stretch=1)
    row_layout.addWidget(browse_button)

    scans_list = QListWidget()
    scans_list.setSelectionMode(QAbstractItemView.SingleSelection)

    hdf5_button = QPushButton("Export HDF5")

    outer.addWidget(row)
    outer.addWidget(scans_list, stretch=1)
    outer.addWidget(hdf5_button)

    return ScanBrowserDock(
        widget=widget,
        folder_lineedit=folder_lineedit,
        browse_button=browse_button,
        scans_list=scans_list,
        hdf5_button=hdf5_button,
    )
