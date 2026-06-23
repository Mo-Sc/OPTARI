from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QComboBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .dock_helpers import create_range_edits, create_right_dock_shell


@dataclass
class AnnotationDock:
    widget: QWidget
    roi_clipping_box: QGroupBox
    roi_clip_min_edit: QLineEdit
    roi_clip_max_edit: QLineEdit
    roi_exclusion_box: QGroupBox
    roi_exclude_min_edit: QLineEdit
    roi_exclude_max_edit: QLineEdit
    include_all_layers_checkbox: QCheckBox
    include_all_frames_checkbox: QCheckBox
    include_all_wavelengths_checkbox: QCheckBox
    roi_library_list: QListWidget
    roi_library_description_label: QLabel
    roi_placement_mode_combo: QComboBox
    save_roi_button: QPushButton
    remove_roi_button: QPushButton
    save_library_button: QPushButton

    def set_roi_ids(self, ids: list[str]) -> None:
        self.roi_library_list.clear()
        for roi_id in ids:
            self.roi_library_list.addItem(roi_id)


def create_annotation_dock(*, enable_scroll: bool = True) -> AnnotationDock:
    shell = create_right_dock_shell(enable_scroll=enable_scroll)
    widget = shell.widget
    outer = shell.content_layout

    # ROI Library section
    roi_library_box = QGroupBox("ROI Library")
    roi_library_layout = QVBoxLayout(roi_library_box)

    roi_library_list = QListWidget()
    roi_library_list.setSelectionMode(QAbstractItemView.SingleSelection)

    button_row = QWidget()
    button_layout = QHBoxLayout(button_row)
    button_layout.setContentsMargins(0, 0, 0, 0)

    save_roi_button = QPushButton("Save ROI")
    remove_roi_button = QPushButton("Remove ROI")
    save_library_button = QPushButton("Save Library")

    button_layout.addWidget(save_roi_button)
    button_layout.addWidget(remove_roi_button)
    button_layout.addWidget(save_library_button)

    roi_library_layout.addWidget(roi_library_list)
    roi_library_description_label = QLabel("")
    roi_library_description_label.setWordWrap(True)
    roi_library_layout.addWidget(roi_library_description_label)

    roi_placement_mode_combo = QComboBox()
    roi_placement_mode_combo.addItem("static", userData="static")
    roi_placement_mode_combo.addItem("auto", userData="auto")

    placement_row = QWidget()
    placement_layout = QHBoxLayout(placement_row)
    placement_layout.setContentsMargins(0, 0, 0, 0)
    placement_layout.addWidget(QLabel("Placement"))
    placement_layout.addWidget(roi_placement_mode_combo)
    roi_library_layout.addWidget(placement_row)

    roi_library_layout.addWidget(button_row)

    # ROI clipping and exclusion section                                                 
    roi_box = QGroupBox("ROI Intensity")
    roi_layout = QVBoxLayout(roi_box)

    roi_clipping_box = QGroupBox("ROI Clipping")
    roi_clipping_box.setCheckable(True)
    roi_clipping_box.setChecked(True)
    roi_clip_form = QFormLayout(roi_clipping_box)
    roi_clip_min_edit, roi_clip_max_edit = create_range_edits()
    roi_clip_form.addRow("Min. Intensity", roi_clip_min_edit)
    roi_clip_form.addRow("Max. Intensity", roi_clip_max_edit)

    roi_exclusion_box = QGroupBox("ROI Exclusion")
    roi_exclusion_box.setCheckable(True)
    roi_exclusion_box.setChecked(False)
    roi_exclude_form = QFormLayout(roi_exclusion_box)
    roi_exclude_min_edit, roi_exclude_max_edit = create_range_edits()
    roi_exclude_form.addRow("Min. Intensity", roi_exclude_min_edit)
    roi_exclude_form.addRow("Max. Intensity", roi_exclude_max_edit)

    def _on_clipping_toggled(checked: bool) -> None:
        if checked:
            roi_exclusion_box.setChecked(False)

    def _on_exclusion_toggled(checked: bool) -> None:
        if checked:
            roi_clipping_box.setChecked(False)

    roi_clipping_box.toggled.connect(_on_clipping_toggled)
    roi_exclusion_box.toggled.connect(_on_exclusion_toggled)

    roi_layout.addWidget(roi_clipping_box)
    roi_layout.addWidget(roi_exclusion_box)
    
    # ROI data saving options
    save_roi_box = QGroupBox("Save ROI Data")
    save_roi_layout = QVBoxLayout(save_roi_box)

    include_all_layers_checkbox = QCheckBox("Include all layers")
    include_all_frames_checkbox = QCheckBox("Include all frames")
    include_all_wavelengths_checkbox = QCheckBox("Include all channels")
    include_all_layers_checkbox.setChecked(False)
    include_all_frames_checkbox.setChecked(False)
    include_all_wavelengths_checkbox.setChecked(False)

    save_roi_layout.addWidget(include_all_layers_checkbox)
    save_roi_layout.addWidget(include_all_frames_checkbox)
    save_roi_layout.addWidget(include_all_wavelengths_checkbox)
    

    outer.addWidget(roi_library_box)
    outer.addWidget(roi_box)
    outer.addWidget(save_roi_box)
    outer.addStretch()

    return AnnotationDock(
        widget=widget,
        roi_clipping_box=roi_clipping_box,
        roi_clip_min_edit=roi_clip_min_edit,
        roi_clip_max_edit=roi_clip_max_edit,
        roi_exclusion_box=roi_exclusion_box,
        roi_exclude_min_edit=roi_exclude_min_edit,
        roi_exclude_max_edit=roi_exclude_max_edit,
        include_all_layers_checkbox=include_all_layers_checkbox,
        include_all_frames_checkbox=include_all_frames_checkbox,
        include_all_wavelengths_checkbox=include_all_wavelengths_checkbox,
        roi_library_list=roi_library_list,
        roi_library_description_label=roi_library_description_label,
        roi_placement_mode_combo=roi_placement_mode_combo,
        save_roi_button=save_roi_button,
        remove_roi_button=remove_roi_button,
        save_library_button=save_library_button,
    )
