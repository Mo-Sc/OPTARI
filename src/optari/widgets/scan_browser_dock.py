from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from qtpy.QtCore import QSettings, Qt
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

from optari.io.discovery import ScanInfo


@dataclass
class ScanBrowserDock:
    widget: QWidget
    folder_lineedit: QLineEdit
    browse_button: QPushButton
    scans_list: QListWidget
    hdf5_button: QPushButton
    ipasc_button: QPushButton
    export_layer_button: QPushButton

    def set_folder(self, folder: Path) -> None:
        self.folder_lineedit.setText(str(folder))

    def set_scans(self, scan_items: list[tuple[Path, ScanInfo]]) -> None:
        self.scans_list.clear()
        checked = _read_checked_scans().get(self.folder_lineedit.text(), [])
        for path, info in scan_items:
            display = (
                f"{path.name} ({info.internal_name})"
                if info.internal_name
                else path.name
            )
            item = QListWidgetItem(display)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if display in checked else Qt.Unchecked
            )
            self.scans_list.addItem(item)

    def save_checked_scans(self) -> None:
        """Save the checked scans for the current study folder."""
        items = map(self.scans_list.item, range(self.scans_list.count()))
        studies = _read_checked_scans()
        studies[self.folder_lineedit.text()] = [
            item.text() for item in items if item.checkState() == Qt.Checked
        ]
        QSettings("OPTARI", "OPTARI").setValue(
            "checked_scans", json.dumps(studies)
        )


def _read_checked_scans() -> dict[str, list[str]]:
    """Checked scans by study folder."""
    return json.loads(
        QSettings("OPTARI", "OPTARI").value("checked_scans", "{}")
    )


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
    browse_button.setToolTip("Select the study folder that contains the scans")

    row_layout.addWidget(folder_lineedit, stretch=1)
    row_layout.addWidget(browse_button)

    scans_list = QListWidget()
    scans_list.setSelectionMode(QAbstractItemView.SingleSelection)

    export_row = QWidget()
    export_row_layout = QHBoxLayout(export_row)
    export_row_layout.setContentsMargins(0, 0, 0, 0)

    hdf5_button = QPushButton("Save HDF5")
    hdf5_button.setToolTip(
        "Save the loaded scan, ROIs, and derived layers as HDF5. Choose a new file for a "
        "copy, or the loaded OPTARI HDF5 file itself to update it in place"
    )
    ipasc_button = QPushButton("Export IPASC")
    ipasc_button.setToolTip("Export the raw time series as a IPASC HDF5 file.")
    export_layer_button = QPushButton("Export View")
    export_layer_button.setToolTip(
        "Export the current viewer display as an image or video"
    )
    export_row_layout.addWidget(hdf5_button)
    export_row_layout.addWidget(ipasc_button)
    export_row_layout.addWidget(export_layer_button)

    outer.addWidget(row)
    outer.addWidget(scans_list, stretch=1)
    outer.addWidget(export_row)

    return ScanBrowserDock(
        widget=widget,
        folder_lineedit=folder_lineedit,
        browse_button=browse_button,
        scans_list=scans_list,
        hdf5_button=hdf5_button,
        ipasc_button=ipasc_button,
        export_layer_button=export_layer_button,
    )
