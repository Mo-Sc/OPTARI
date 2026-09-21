"""Read-only layer and scan metadata dialog."""

from __future__ import annotations

from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from patari.utils.metadata import (
    clinical_metadata_rows,
    ipasc_metadata_rows,
    layer_metadata_rows,
    scan_metadata_rows,
)


class LayerMetadataDialog(QDialog):
    """Display selected layer and scan metadata in separate tabs."""

    def __init__(
        self,
        layer,
        pa_data=None,
        scan_path: Path | None = None,
        study_path: Path | None = None,
        scan_info=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Metadata")
        self.resize(640, 480)

        tabs = QTabWidget()
        tabs.addTab(self._create_table(layer_metadata_rows(layer)), "Layer")
        tabs.addTab(
            self._create_table(
                scan_metadata_rows(pa_data, scan_path, study_path, scan_info)
            ),
            "Scan",
        )
        tabs.addTab(self._create_table(ipasc_metadata_rows(pa_data)), "IPASC")
        tabs.addTab(
            self._create_table(
                clinical_metadata_rows(
                    pa_data.get_clinical_metadata() if pa_data else None
                )
            ),
            "Clinical",
        )

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    @staticmethod
    def _create_table(rows: list[tuple[str, str, str]]) -> QTableWidget:
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels(["Property", "Value"])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableWidget {"
            "background-color: #2b2b2b;"
            "alternate-background-color: #363636;"
            "color: #f0f0f0;"
            "selection-background-color: #4d647a;"
            "selection-color: #ffffff;"
            "}"
        )
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideMiddle)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setColumnWidth(0, 160)
        table.horizontalHeader().setStretchLastSection(True)
        table.cellDoubleClicked.connect(
            lambda row, _column: LayerMetadataDialog._show_details(
                table, row
            )
        )
        for row, (label, summary, details) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(label))
            value_item = QTableWidgetItem(summary)
            value_item.setData(Qt.UserRole, details)
            value_item.setToolTip("Double-click to view full value")
            table.setItem(row, 1, value_item)
        return table

    @staticmethod
    def _show_details(table: QTableWidget, row: int) -> None:
        value_item = table.item(row, 1)
        if value_item is None:
            return

        dialog = QDialog(table)
        dialog.setWindowTitle(table.item(row, 0).text())
        dialog.resize(640, 420)
        text_edit = QPlainTextEdit(str(value_item.data(Qt.UserRole)))
        text_edit.setReadOnly(True)
        text_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(text_edit)
        layout.addWidget(buttons)
        dialog.exec()
