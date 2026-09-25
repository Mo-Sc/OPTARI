"""Read-only layer and scan metadata dialog."""

from __future__ import annotations

from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from optari.utils.metadata import (
    ipasc_metadata_rows,
    layer_metadata_rows,
    scan_metadata_rows,
)


class LayerMetadataDialog(QDialog):
    """Display selected layer and scan metadata in separate tabs; the Clinical tab is editable."""

    def __init__(
        self,
        layer,
        pa_data=None,
        scan_path: Path | None = None,
        study_path: Path | None = None,
        scan_info=None,
        controller=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Metadata")
        self.resize(640, 480)
        self._controller = controller
        self._clinical_table: QTableWidget | None = None

        tabs = QTabWidget()
        tabs.addTab(self._create_table(layer_metadata_rows(layer)), "Layer")
        tabs.addTab(
            self._create_table(
                scan_metadata_rows(pa_data, scan_path, study_path, scan_info)
            ),
            "Scan",
        )
        tabs.addTab(self._create_table(ipasc_metadata_rows(pa_data)), "IPASC")
        tabs.addTab(self._build_clinical_tab(pa_data, controller), "Clinical")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._on_save)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _build_clinical_tab(self, pa_data, controller) -> QWidget:
        if pa_data is None:
            return self._create_table([("Status", "No scan loaded", "No scan loaded")])

        current = controller.clinical_metadata_edits if controller.clinical_metadata_edits is not None else (
            pa_data.get_clinical_metadata() or {}
        )
        rows = [(str(key), str(value), "") for key, value in current.items()]
        self._clinical_table = self._create_table(rows, editable=True)

        add_button = QPushButton("Add Row")
        remove_button = QPushButton("Remove Row")
        add_button.clicked.connect(self._add_clinical_row)
        remove_button.clicked.connect(self._remove_clinical_row)
        button_row = QHBoxLayout()
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addStretch()

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self._clinical_table)
        layout.addLayout(button_row)
        return tab

    def _add_clinical_row(self) -> None:
        row = self._clinical_table.rowCount()
        self._clinical_table.insertRow(row)
        self._clinical_table.setItem(row, 0, QTableWidgetItem(""))
        self._clinical_table.setItem(row, 1, QTableWidgetItem(""))

    def _remove_clinical_row(self) -> None:
        row = self._clinical_table.currentRow()
        if row >= 0:
            self._clinical_table.removeRow(row)

    def _on_save(self) -> None:
        if self._clinical_table is not None:
            metadata: dict[str, str] = {}
            for row in range(self._clinical_table.rowCount()):
                key_item = self._clinical_table.item(row, 0)
                key = key_item.text().strip() if key_item else ""
                if not key:
                    continue
                value_item = self._clinical_table.item(row, 1)
                metadata[key] = value_item.text() if value_item else ""
            self._controller.clinical_metadata_edits = metadata
        self.accept()

    @staticmethod
    def _create_table(rows: list[tuple[str, str, str]], editable: bool = False) -> QTableWidget:
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
        table.setColumnWidth(0, 160)
        table.horizontalHeader().setStretchLastSection(True)
        if editable:
            table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        else:
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.cellDoubleClicked.connect(
                lambda row, _column: LayerMetadataDialog._show_details(
                    table, row
                )
            )
        for row, (label, summary, details) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(label))
            value_item = QTableWidgetItem(summary)
            if not editable:
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
