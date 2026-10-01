from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

from patato.io.attribute_tags import HDF5Tags  # type: ignore
from qtpy.QtCore import QUrl
from qtpy.QtGui import QColor, QDesktopServices, QPixmap, QIcon
from qtpy.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from optari.config.config import read_user_config_dict, write_user_config_dict
from optari.roi.roi_features import FEATURE_REGISTRY
from optari.segmentation.segmenter import load_model_registry
from optari.widgets.dock_helpers import DOCK_LABELS
from optari.utils.setup import (
    get_default_config_file,
    get_user_config_file,
    get_user_autosave_dir,
    get_user_dir,
    get_user_logs_dir,
    get_user_models_dir,
    get_user_reconstruction_presets_dir,
)

logger = logging.getLogger(__name__)

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Keys of general.LAYER_COLOR_MAPS, paired with a readable label. Sourced from HDF5Tags so they
# stay in step with the lookup in patato_bridge.layer_colormap().
COLOR_MAP_KEYS: list[tuple[str, str]] = [
    (HDF5Tags.ULTRASOUND, "Ultrasound"),
    (HDF5Tags.RECONSTRUCTION, "Reconstruction"),
    (HDF5Tags.UNMIXED, "Unmixed"),
    (HDF5Tags.SO2, "sO₂"),
    (HDF5Tags.THB, "THb"),
]

SCALE_AXES = ("frame", "z", "x")


def _available_colormaps() -> list[str]:
    from napari.utils.colormaps import AVAILABLE_COLORMAPS

    return sorted(AVAILABLE_COLORMAPS)


def _color_icon(color: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def _open_path(path: Path) -> None:
    """Open *path* in the OS file browser, or its parent when it is a file."""
    target = path if path.is_dir() else path.parent
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


class SettingsDialog(QDialog):
    """Editor for the application settings in ``~/.optari/config/config.json``.

    Only changes config.json. Presets are changed in the respective docks.
    Requires restart to take effect.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("OPTARI Settings")
        self.setMinimumSize(560, 520)

        self._data = read_user_config_dict()

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general_tab(), "General")
        self.tabs.addTab(self._build_viewer_tab(), "Viewer")
        self.tabs.addTab(self._build_docks_tab(), "Docks")
        self.tabs.addTab(self._build_roi_tab(), "ROI Table")
        self.tabs.addTab(self._build_models_tab(), "Models")
        self.tabs.addTab(self._build_paths_tab(), "Paths")

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save
            | QDialogButtonBox.Close
            | QDialogButtonBox.RestoreDefaults
        )
        buttons.button(QDialogButtonBox.Save).clicked.connect(
            self.on_save_clicked
        )
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.close)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(
            self.on_restore_defaults_clicked
        )

        outer = QVBoxLayout(self)
        outer.addWidget(self.tabs)
        outer.addWidget(self.status_label)
        outer.addWidget(buttons)

        self._load_into_widgets(self._data)

    # ============ tab construction ============
    def _build_general_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self.operator_edit = QLineEdit()
        self.operator_edit.setToolTip(
            "Who is running the analysis. Will be recorded in the exported HDF5 and XLSX files."
        )
        form.addRow("Operator", self.operator_edit)

        self.analysis_id_edit = QLineEdit()
        self.analysis_id_edit.setToolTip(
            "Name of the analysis, e.g. a study or cohort name. Will be recorded in the exported HDF5 and XLSX files."
        )
        form.addRow("Analysis ID", self.analysis_id_edit)

        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(LOG_LEVELS)
        form.addRow("Log level", self.log_level_combo)

        self.gui_log_level_combo = QComboBox()
        self.gui_log_level_combo.addItems(LOG_LEVELS)
        self.gui_log_level_combo.setToolTip(
            "Minimum level shown as a napari notification popup."
        )
        form.addRow("Notification level", self.gui_log_level_combo)

        self.histogram_bins_spin = QSpinBox()
        self.histogram_bins_spin.setRange(2, 1000)
        form.addRow("Histogram bins", self.histogram_bins_spin)

        return widget

    def _build_viewer_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self.default_pa_layer_edit = QLineEdit()
        self.default_pa_layer_edit.setToolTip(
            "Layer selected automatically after a scan loads, matched by name."
        )
        form.addRow("Default PA layer", self.default_pa_layer_edit)

        self.frame_mode_combo = QComboBox()
        self.frame_mode_combo.addItem("Motion-based", userData="motion")
        self.frame_mode_combo.addItem("Fixed index", userData="index")
        self.frame_index_spin = QSpinBox()
        self.frame_index_spin.setRange(0, 100000)
        self.frame_mode_combo.currentIndexChanged.connect(
            lambda: self.frame_index_spin.setEnabled(
                self.frame_mode_combo.currentData() == "index"
            )
        )
        frame_row = QWidget()
        frame_layout = QHBoxLayout(frame_row)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(self.frame_mode_combo)
        frame_layout.addWidget(self.frame_index_spin)
        form.addRow("Default frame", frame_row)

        self.channel_index_spin = QSpinBox()
        self.channel_index_spin.setRange(0, 1000)
        form.addRow("Default channel", self.channel_index_spin)

        self.playback_fps_spin = QSpinBox()
        self.playback_fps_spin.setRange(1, 240)
        form.addRow("Playback FPS", self.playback_fps_spin)

        self.pa_scale_spins = self._add_scale_row(
            form, "PA fallback scale (mm)"
        )
        self.us_scale_spins = self._add_scale_row(
            form, "US fallback scale (mm)"
        )

        self.show_track_id_check = QCheckBox("Show track ID on ROI shapes")
        self.show_track_id_check.setToolTip(
            'Label shapes as "roi_id/track_id" instead of just "roi_id".'
        )
        form.addRow(self.show_track_id_check)

        self.roi_label_size_spin = QSpinBox()
        self.roi_label_size_spin.setRange(1, 72)
        form.addRow("ROI label text size", self.roi_label_size_spin)

        colormap_group = QGroupBox("Layer colormaps")
        colormap_form = QFormLayout(colormap_group)
        self.colormap_combos: dict[str, QComboBox] = {}
        colormap_names = _available_colormaps()
        for key, label in COLOR_MAP_KEYS:
            combo = QComboBox()
            combo.setEditable(
                True
            )  # matplotlib names beyond napari's built-ins still resolve
            combo.addItems(colormap_names)
            self.colormap_combos[key] = combo
            colormap_form.addRow(label, combo)
        form.addRow(colormap_group)

        return widget

    def _add_scale_row(
        self, form: QFormLayout, label: str
    ) -> list[QDoubleSpinBox]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        spins = []
        for axis in SCALE_AXES:
            spin = QDoubleSpinBox()
            spin.setDecimals(4)
            spin.setRange(0.0001, 1000.0)
            spin.setPrefix(f"{axis}: ")
            layout.addWidget(spin)
            spins.append(spin)
        form.addRow(label, row)
        return spins

    def _build_docks_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(
            QLabel(
                "Panels shown when OPTARI starts. Any panel can still be shown or hidden at "
                "any time from OPTARI ▸ Docks."
            )
        )

        group = QGroupBox("Default visible docks")
        grid = QGridLayout(group)
        self.dock_checkboxes: dict[str, QCheckBox] = {}
        for position, label in enumerate(DOCK_LABELS):
            checkbox = QCheckBox(label)
            self.dock_checkboxes[label] = checkbox
            grid.addWidget(checkbox, position // 3, position % 3)
        layout.addWidget(group)
        layout.addStretch()

        return widget

    def _build_roi_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        features_group = QGroupBox("Columns shown in the ROI table")
        grid = QGridLayout(features_group)
        self.feature_checkboxes: dict[str, QCheckBox] = {}
        for position, feature_id in enumerate(FEATURE_REGISTRY):
            checkbox = QCheckBox(feature_id)
            self.feature_checkboxes[feature_id] = checkbox
            grid.addWidget(checkbox, position // 3, position % 3)
        layout.addWidget(features_group)

        colors_group = QGroupBox("ROI colors (cycled by ROI index)")
        colors_layout = QVBoxLayout(colors_group)
        self.roi_colors_list = QListWidget()
        self.roi_colors_list.itemDoubleClicked.connect(
            lambda _item: self.on_edit_color_clicked()
        )
        colors_layout.addWidget(self.roi_colors_list)

        color_buttons = QWidget()
        color_buttons_layout = QHBoxLayout(color_buttons)
        color_buttons_layout.setContentsMargins(0, 0, 0, 0)
        add_button = QPushButton("Add")
        edit_button = QPushButton("Edit")
        remove_button = QPushButton("Remove")
        add_button.clicked.connect(self.on_add_color_clicked)
        edit_button.clicked.connect(self.on_edit_color_clicked)
        remove_button.clicked.connect(self.on_remove_color_clicked)
        for button in (add_button, edit_button, remove_button):
            color_buttons_layout.addWidget(button)
        colors_layout.addWidget(color_buttons)
        layout.addWidget(colors_group)

        return widget

    def _build_models_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        self.default_model_combo = QComboBox()
        form.addRow("Default segmentation model", self.default_model_combo)
        layout.addLayout(form)

        self.models_table = QTableWidget(0, 4)
        self.models_table.setHorizontalHeaderLabels(
            ["Model", "Classes", "Input", "Weights"]
        )
        self.models_table.verticalHeader().setVisible(False)
        self.models_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        layout.addWidget(self.models_table)

        layout.addWidget(
            QLabel(
                "The model registry itself is edited in "
                "~/.optari/config/segmentation_models.json."
            )
        )
        return widget

    def _build_paths_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        for label, path in (
            ("User directory", get_user_dir()),
            ("Config file", get_user_config_file()),
            ("Presets", get_user_reconstruction_presets_dir().parent),
            ("Models", get_user_models_dir()),
            ("Logs", get_user_logs_dir()),
            ("ROI table backups", get_user_autosave_dir()),
        ):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(path))
            edit.setReadOnly(True)
            open_button = QPushButton("Open")
            open_button.clicked.connect(
                lambda _checked=False, p=path: _open_path(p)
            )
            row_layout.addWidget(edit)
            row_layout.addWidget(open_button)
            form.addRow(label, row)
        return widget

    # ============ load / collect ============
    def _load_into_widgets(self, data: dict) -> None:
        general = data["general"]
        self.operator_edit.setText(str(general["OPERATOR"]))
        self.analysis_id_edit.setText(str(general["ANALYSIS_ID"]))
        self.log_level_combo.setCurrentText(str(general["LOG_LEVEL"]).upper())
        self.gui_log_level_combo.setCurrentText(
            str(general["GUI_LOG_LEVEL"]).upper()
        )
        self.histogram_bins_spin.setValue(
            int(data["analysis"]["histogram_bins"])
        )

        self.default_pa_layer_edit.setText(str(general["DEFAULT_PA_LAYER"]))

        frame_index = general["DEFAULT_FRAME_INDEX"]
        is_motion = frame_index == "motion"
        self.frame_mode_combo.setCurrentIndex(0 if is_motion else 1)
        self.frame_index_spin.setValue(0 if is_motion else int(frame_index))
        self.frame_index_spin.setEnabled(not is_motion)

        self.channel_index_spin.setValue(int(general["DEFAULT_CHANNEL_INDEX"]))
        self.playback_fps_spin.setValue(int(general["DEFAULT_PLAYBACK_FPS"]))

        for spins, key in (
            (self.pa_scale_spins, "PA_FALLBACK_SCALE"),
            (self.us_scale_spins, "US_FALLBACK_SCALE"),
        ):
            for spin, value in zip(spins, general[key]):
                spin.setValue(float(value))

        self.show_track_id_check.setChecked(
            bool(data["annotation"].get("show_track_id", True))
        )
        self.roi_label_size_spin.setValue(
            int(data["annotation"].get("roi_label_size", 8))
        )

        colormaps = general.get("LAYER_COLOR_MAPS", {})
        for key, combo in self.colormap_combos.items():
            combo.setCurrentText(str(colormaps.get(key, "")))

        visible_docks = general.get("DEFAULT_VISIBLE_DOCKS", {})
        for label, checkbox in self.dock_checkboxes.items():
            checkbox.setChecked(int(visible_docks.get(label, 1)) == 1)

        roi_features = data["annotation"].get("roi_features", {})
        for feature_id, checkbox in self.feature_checkboxes.items():
            checkbox.setChecked(int(roi_features.get(feature_id, 0)) == 1)

        self.roi_colors_list.clear()
        for color in data["annotation"].get("roi_colors", []):
            self._append_color_item(str(color))

        self._refresh_models_tab(str(data["segmentation"]["default_model"]))

    def _collect_from_widgets(self, data: dict) -> dict:
        general = data["general"]
        general["OPERATOR"] = self.operator_edit.text().strip()
        general["ANALYSIS_ID"] = self.analysis_id_edit.text().strip()
        general["LOG_LEVEL"] = self.log_level_combo.currentText()
        general["GUI_LOG_LEVEL"] = self.gui_log_level_combo.currentText()
        general["DEFAULT_PA_LAYER"] = self.default_pa_layer_edit.text().strip()
        general["DEFAULT_FRAME_INDEX"] = (
            "motion"
            if self.frame_mode_combo.currentData() == "motion"
            else self.frame_index_spin.value()
        )
        general["DEFAULT_CHANNEL_INDEX"] = self.channel_index_spin.value()
        general["DEFAULT_PLAYBACK_FPS"] = self.playback_fps_spin.value()
        general["PA_FALLBACK_SCALE"] = [
            spin.value() for spin in self.pa_scale_spins
        ]
        general["US_FALLBACK_SCALE"] = [
            spin.value() for spin in self.us_scale_spins
        ]
        general.setdefault("LAYER_COLOR_MAPS", {})
        for key, combo in self.colormap_combos.items():
            general["LAYER_COLOR_MAPS"][key] = combo.currentText().strip()

        general.setdefault("DEFAULT_VISIBLE_DOCKS", {})
        for label, checkbox in self.dock_checkboxes.items():
            general["DEFAULT_VISIBLE_DOCKS"][label] = int(checkbox.isChecked())

        data["analysis"]["histogram_bins"] = self.histogram_bins_spin.value()

        data["annotation"][
            "show_track_id"
        ] = self.show_track_id_check.isChecked()
        data["annotation"]["roi_label_size"] = self.roi_label_size_spin.value()
        data["annotation"].setdefault("roi_features", {})
        for feature_id, checkbox in self.feature_checkboxes.items():
            data["annotation"]["roi_features"][feature_id] = int(
                checkbox.isChecked()
            )
        data["annotation"]["roi_colors"] = [
            self.roi_colors_list.item(row).text()
            for row in range(self.roi_colors_list.count())
        ]

        data["segmentation"][
            "default_model"
        ] = self.default_model_combo.currentText()
        return data

    # ============ models tab ============
    def _refresh_models_tab(self, default_model: str | None = None) -> None:
        if default_model is None:
            default_model = self.default_model_combo.currentText()

        try:
            registry = load_model_registry()
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.exception("Could not read the segmentation model registry.")
            self.status_label.setText(
                f"Could not read the model registry: {exc}"
            )
            return

        self.default_model_combo.blockSignals(True)
        self.default_model_combo.clear()
        self.default_model_combo.addItems(sorted(registry))
        self.default_model_combo.setCurrentText(default_model)
        self.default_model_combo.blockSignals(False)

        self.models_table.setRowCount(len(registry))
        for row, model_id in enumerate(sorted(registry)):
            model_config = registry[model_id]
            weights_path = get_user_models_dir() / model_config.filename
            installed = weights_path.is_file()

            self.models_table.setItem(row, 0, QTableWidgetItem(model_id))
            self.models_table.setItem(
                row,
                1,
                QTableWidgetItem(", ".join(model_config.class_names.values())),
            )
            self.models_table.setItem(
                row,
                2,
                QTableWidgetItem(
                    f"{model_config.input_height}×{model_config.input_width}"
                ),
            )
            self.models_table.setItem(
                row,
                3,
                QTableWidgetItem("Installed" if installed else "Missing"),
            )

        self.models_table.resizeColumnsToContents()
        self.models_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )

    # ============ roi colors ============
    def _append_color_item(self, color: str) -> None:
        item = QListWidgetItem(_color_icon(color), color)
        self.roi_colors_list.addItem(item)

    def on_add_color_clicked(self) -> None:
        color = QColorDialog.getColor(QColor("#FF0000"), self, "Add ROI color")
        if color.isValid():
            self._append_color_item(color.name().upper())

    def on_edit_color_clicked(self) -> None:
        item = self.roi_colors_list.currentItem()
        if item is None:
            return
        color = QColorDialog.getColor(
            QColor(item.text()), self, "Edit ROI color"
        )
        if color.isValid():
            item.setText(color.name().upper())
            item.setIcon(_color_icon(color.name()))

    def on_remove_color_clicked(self) -> None:
        row = self.roi_colors_list.currentRow()
        if row < 0:
            return
        if self.roi_colors_list.count() == 1:
            self.status_label.setText("At least one ROI color is required.")
            return
        self.roi_colors_list.takeItem(row)

    # ============ save / restore ============
    def _write_config(
        self, data: dict, success_message: str, failure_prefix: str
    ) -> bool:
        """Validate and write *data*, reporting the outcome in the status label."""
        try:
            write_user_config_dict(data)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self.status_label.setText(f"{failure_prefix}: {exc}")
            return False
        self._data = data
        self.status_label.setText(success_message)
        return True

    def on_save_clicked(self) -> None:
        data = self._collect_from_widgets(copy.deepcopy(self._data))
        self._write_config(
            data, "Settings saved. Restart OPTARI to apply.", "Not saved"
        )

    def on_restore_defaults_clicked(self) -> None:
        confirmed = QMessageBox.question(
            self,
            "Restore defaults",
            "Replace your settings with the OPTARI defaults? Presets and downloaded "
            "models are not affected.",
        )
        if confirmed != QMessageBox.Yes:
            return

        data = json.loads(
            get_default_config_file().read_text(encoding="utf-8")
        )
        if self._write_config(
            data, "Defaults restored. Restart OPTARI to apply.", "Not restored"
        ):
            self._load_into_widgets(self._data)
