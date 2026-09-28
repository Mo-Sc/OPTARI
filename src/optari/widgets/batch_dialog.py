"""Batch processing window: pick a dataset and a plan, review it, then run it.

The window is a view. Resolving and checking a plan lives in ``optari.batch.plan``
and running it in ``optari.batch.runner``, so both stay testable without Qt.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from optari.batch.plan import (
    build_plan,
    describe_plan,
    plan_warnings,
    validate_plan,
)
from optari.batch.runner import BatchRunner
from optari.utils.presets import PresetStore
from optari.utils.setup import get_user_batch_presets_dir
from optari.widgets.dock_helpers import (
    add_preset_to_combo,
    create_preset_controls,
    populate_preset_combo,
    prompt_preset_name,
    remove_selected_preset,
)

logger = logging.getLogger(__name__)

SCAN_COLUMNS = ["", "Study", "Scan", "Name", "Format", "Status"]
INCLUDE_COLUMN = 0
STATUS_COLUMN = 5


class BatchDialog(QDialog):
    """Plan a batch run over a dataset, then watch it happen.

    Two phases in one window: build and check a plan, then run it with a status per
    scan. The plan stays on screen during the run so failures can be read in place.
    """

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("OPTARI Batch Processing")
        self.setMinimumSize(880, 640)

        self._preset_store = PresetStore(get_user_batch_presets_dir())
        self._plan = None
        self._runner = None
        self._row_for_key: dict[str, int] = {}
        self._running = False

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_inputs())
        layout.addWidget(self._build_editor())
        layout.addWidget(self._build_preview(), stretch=1)
        layout.addLayout(self._build_actions())

        populate_preset_combo(self.preset_combo, self._preset_store)
        self.on_preset_changed()

    # ============ construction ============
    def _build_inputs(self) -> QWidget:
        box = QGroupBox("Dataset and plan")
        form = QFormLayout(box)

        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("Folder holding Study_*/Scan_* data")
        self.root_edit.editingFinished.connect(self.refresh_plan)
        form.addRow(
            "Dataset folder", _with_browse(self.root_edit, self.on_browse_root)
        )

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Empty folder for the results")
        self.output_edit.editingFinished.connect(self.refresh_plan)
        form.addRow(
            "Output folder",
            _with_browse(self.output_edit, self.on_browse_output),
        )

        (
            self.preset_combo,
            self.save_preset_button,
            self.remove_preset_button,
            self._preset_actions,
        ) = create_preset_controls()
        self.preset_combo.setToolTip(
            "Selecting a preset loads it into the editor below"
        )
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.save_preset_button.clicked.connect(self.on_save_preset_clicked)
        self.remove_preset_button.clicked.connect(
            self.on_remove_preset_clicked
        )
        form.addRow("Batch preset", self.preset_combo)
        return box

    def _build_editor(self) -> QWidget:
        box = QGroupBox("Plan (JSON)")
        layout = QVBoxLayout(box)

        self.preset_edit = QPlainTextEdit()
        self.preset_edit.setPlaceholderText("JSON batch plan")
        self.preset_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preset_edit.setMaximumHeight(240)
        self.preset_edit.setToolTip(
            "Edit the plan here, then Apply. Save Preset writes it back to a file."
        )
        self.preset_edit.textChanged.connect(self.on_preset_edited)
        layout.addWidget(self.preset_edit)

        self.apply_button = QPushButton("Apply")
        self.apply_button.setToolTip("Re-read the edited plan above")
        self.apply_button.clicked.connect(self.refresh_plan)
        actions = QHBoxLayout()
        actions.addWidget(self.apply_button)
        actions.addWidget(self._preset_actions)
        actions.addStretch(1)
        layout.addLayout(actions)
        return box

    def _build_preview(self) -> QWidget:
        box = QGroupBox("Analysis plan")
        layout = QVBoxLayout(box)

        self.settings_view = QPlainTextEdit()
        self.settings_view.setReadOnly(True)
        self.settings_view.setMaximumHeight(150)
        layout.addWidget(self.settings_view)

        self.problems_label = QLabel()
        self.problems_label.setWordWrap(True)
        self.problems_label.setStyleSheet("color: palette(link-visited);")
        layout.addWidget(self.problems_label)

        self.scans_table = QTableWidget(0, len(SCAN_COLUMNS))
        self.scans_table.setHorizontalHeaderLabels(SCAN_COLUMNS)
        self.scans_table.verticalHeader().setVisible(False)
        self.scans_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.scans_table.setSelectionMode(QAbstractItemView.NoSelection)
        header = self.scans_table.horizontalHeader()
        header.setSectionResizeMode(
            INCLUDE_COLUMN, QHeaderView.ResizeToContents
        )
        for column in range(1, len(SCAN_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
        layout.addWidget(self.scans_table, stretch=1)
        return box

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.select_all_box = QCheckBox("Include all scans")
        self.select_all_box.setChecked(True)
        self.select_all_box.toggled.connect(self.on_select_all_toggled)
        row.addWidget(self.select_all_box)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        row.addWidget(self.progress_bar, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        row.addWidget(self.status_label, stretch=2)

        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.on_run_clicked)
        row.addWidget(self.run_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        row.addWidget(self.cancel_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.close_button)
        return row

    # ============ preset editing ============
    def on_preset_changed(self) -> None:
        """Load the selected preset into the editor."""
        preset_path = self.preset_combo.currentData()
        if preset_path is None:
            self.refresh_plan()
            return
        try:
            text = Path(preset_path).read_text()
        except OSError as exc:
            self.status_label.setText(f"Could not read preset: {exc}")
            return
        self.preset_edit.blockSignals(True)
        try:
            self.preset_edit.setPlainText(text)
        finally:
            self.preset_edit.blockSignals(False)
        self.refresh_plan()

    def on_preset_edited(self) -> None:
        """The editor is ahead of the preview until Apply is pressed."""
        self._set_problems(["Plan edited. Press Apply to check it."])

    def on_save_preset_clicked(self) -> None:
        plan_dict = self._edited_preset()
        if plan_dict is None:
            return
        name = prompt_preset_name(self, self.preset_combo, "batch_plan")
        if name is None:
            return
        try:
            preset_path = self._preset_store.save(
                name, plan_dict, overwrite=True
            )
        except (ValueError, OSError) as exc:
            self.status_label.setText(f"Could not save preset: {exc}")
            return
        if self.preset_combo.findText(preset_path.stem) < 0:
            add_preset_to_combo(self.preset_combo, preset_path)
        self.status_label.setText(f"Saved preset: {preset_path.name}")

    def on_remove_preset_clicked(self) -> None:
        try:
            removed_path, removed = remove_selected_preset(
                self.preset_combo, self._preset_store
            )
        except OSError as exc:
            self.status_label.setText(f"Could not remove preset: {exc}")
            return
        if removed:
            self.status_label.setText(f"Removed preset: {removed_path.name}")
            self.on_preset_changed()

    def _edited_preset(self) -> dict | None:
        """The plan currently in the editor, or None with the reason shown."""
        try:
            data = json.loads(self.preset_edit.toPlainText())
        except json.JSONDecodeError as exc:
            self._set_problems(
                [f"Invalid JSON: {exc.msg} (line {exc.lineno})"]
            )
            return None
        if not isinstance(data, dict):
            self._set_problems(["The batch plan must be a JSON object."])
            return None
        return data

    # ============ plan preview ============
    def on_browse_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select dataset folder"
        )
        if folder:
            self.root_edit.setText(folder)
            self.refresh_plan()

    def on_browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select output folder")
        if folder:
            self.output_edit.setText(folder)
            self.refresh_plan()

    def on_select_all_toggled(self, checked: bool) -> None:
        for row in range(self.scans_table.rowCount()):
            item = self.scans_table.item(row, INCLUDE_COLUMN)
            if item is not None:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def refresh_plan(self) -> None:
        """Rebuild the plan from the current inputs and report what is wrong with it."""
        self._plan = None
        self._row_for_key = {}
        self.scans_table.setRowCount(0)

        root = self.root_edit.text().strip()
        output = self.output_edit.text().strip()
        batch_preset = self._edited_preset()
        if batch_preset is None:
            self.settings_view.setPlainText("")
            return
        if not root or not output:
            self.settings_view.setPlainText("")
            self._set_problems(["Pick a dataset folder and an output folder."])
            return

        try:
            plan = build_plan(
                root=Path(root),
                batch_preset=batch_preset,
                output_dir=Path(output),
            )
        except ValueError as exc:
            self.settings_view.setPlainText("")
            self._set_problems([str(exc)])
            return

        self._plan = plan
        self.settings_view.setPlainText(describe_plan(plan))
        self._fill_scans_table(plan)
        self._set_problems(validate_plan(plan), warnings=plan_warnings(plan))

    def _fill_scans_table(self, plan) -> None:
        self.scans_table.setRowCount(len(plan.jobs))
        for row, job in enumerate(plan.jobs):
            include = QTableWidgetItem()
            include.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            include.setCheckState(Qt.Checked)
            self.scans_table.setItem(row, INCLUDE_COLUMN, include)
            for column, text in enumerate(
                (
                    job.study_path.name,
                    job.scan_path.name,
                    job.scan_name,
                    job.scan_info.kind,
                ),
                start=1,
            ):
                self.scans_table.setItem(row, column, QTableWidgetItem(text))
            self.scans_table.setItem(
                row, STATUS_COLUMN, QTableWidgetItem("pending")
            )
            self._row_for_key[job.key] = row

    def _set_problems(
        self, problems: list[str], warnings: list[str] = ()
    ) -> None:
        """Problems hold the run back; warnings are said out loud and let it through."""
        lines = [f"✗ {p}" for p in problems] + [f"! {w}" for w in warnings]
        self.problems_label.setText("\n".join(lines))
        self.run_button.setEnabled(not problems and self._plan is not None)

    def _included_jobs(self) -> list:
        return [
            job
            for row, job in enumerate(self._plan.jobs)
            if self.scans_table.item(row, INCLUDE_COLUMN).checkState()
            == Qt.Checked
        ]

    # ============ running ============
    def on_run_clicked(self) -> None:
        if self._plan is None:
            return
        if self.controller.task_running:
            self.status_label.setText(
                "Another task is running. Wait for it to finish."
            )
            return

        jobs = self._included_jobs()
        if not jobs:
            self.status_label.setText("No scans selected.")
            return
        self._plan.jobs = jobs
        self._fill_scans_table(self._plan)

        confirm = QMessageBox.question(
            self,
            "Run batch",
            f"Process {len(jobs)} scan(s) into\n{self._plan.output_dir}?\n\n"
            "The viewer will work through the dataset and should be left alone.",
        )
        if confirm != QMessageBox.Yes:
            return

        self._set_running(True)
        self.progress_bar.setRange(0, len(jobs))
        self.progress_bar.setValue(0)

        self._runner = BatchRunner(
            self.controller,
            self._plan,
            on_progress=self.on_job_progress,
            on_finished=self.on_run_finished,
        )
        self._runner.start()

    def on_cancel_clicked(self) -> None:
        if self._runner is not None:
            self.status_label.setText("Cancelling after the current step…")
            self._runner.cancel()

    def on_job_progress(self, job, status: str) -> None:
        row = self._row_for_key.get(job.key)
        if row is not None:
            self.scans_table.item(row, STATUS_COLUMN).setText(status)
            self.scans_table.scrollToItem(
                self.scans_table.item(row, STATUS_COLUMN)
            )
        if status == "running":
            self.status_label.setText(
                f"Processing {job.study_path.name} / {job.scan_path.name}"
            )
            return
        # The report already counts finished scans, the bar just mirrors it.
        finished = sum(
            n
            for s, n in self._runner.report.counts().items()
            if s != "running"
        )
        self.progress_bar.setValue(finished)

    def on_run_finished(self) -> None:
        """Leave the finished run on screen. Re-planning is an explicit next action.

        Rebuilding the plan here would reset every row to "pending" and replace the
        results with a complaint that the output folder is now occupied, which reads
        as if the run had not happened.
        """
        self._set_running(False)
        report = self._runner.report
        failures = report.failures
        for entry in failures:
            logger.warning(
                "batch failure: %s/%s: %s",
                entry.study,
                entry.scan,
                entry.message,
            )

        self._set_problems([])
        self.run_button.setEnabled(False)
        self.status_label.setText(
            f"Finished. {report.summary()}. Results in {self._plan.output_dir}"
        )

        detail = f"{report.summary()}\n\nResults written to:\n{self._plan.output_dir}"
        if failures:
            names = "\n".join(
                f"  {e.study}/{e.scan}: {e.message}" for e in failures[:8]
            )
            more = (
                f"\n  … and {len(failures) - 8} more"
                if len(failures) > 8
                else ""
            )
            QMessageBox.warning(
                self,
                "Batch finished with failures",
                f"{detail}\n\nFailed scans:\n{names}{more}\n\n"
                "Full detail is in batch_report.xlsx and the run log.",
            )
        else:
            QMessageBox.information(self, "Batch finished", detail)

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.progress_bar.setVisible(running)
        self.run_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.close_button.setEnabled(not running)
        for widget in (
            self.root_edit,
            self.output_edit,
            self.preset_combo,
            self.select_all_box,
        ):
            widget.setEnabled(not running)

    def closeEvent(self, event) -> None:
        """Refuse to close mid-run: the runner drives the viewer this window owns."""
        if self._running:
            event.ignore()
            self.status_label.setText("Cancel the run before closing.")
            return
        super().closeEvent(event)


def _with_browse(edit: QLineEdit, on_browse) -> QWidget:
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(edit, stretch=1)
    button = QPushButton("Browse…")
    button.clicked.connect(on_browse)
    row.addWidget(button)
    return container
