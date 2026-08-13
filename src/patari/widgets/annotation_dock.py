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
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from patari.roi.roi_features import numeric_feature_ids
from .dock_helpers import (
    create_frame_scope_controls,
    create_range_edits,
    create_right_dock_shell,
)


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
    include_all_channels_checkbox: QCheckBox
    time_analysis_feature_combo: QComboBox
    roi_presets_list: QListWidget
    roi_presets_description_label: QLabel
    roi_placement_mode_combo: QComboBox
    current_frames_radio: QRadioButton
    all_frames_radio: QRadioButton
    save_roi_preset_button: QPushButton
    remove_roi_preset_button: QPushButton
    place_roi_button: QPushButton

    def set_roi_preset_names(self, names: list[str]) -> None:
        self.roi_presets_list.clear()
        for name in names:
            self.roi_presets_list.addItem(name)


def create_annotation_dock(*, enable_scroll: bool = True) -> AnnotationDock:
    shell = create_right_dock_shell(enable_scroll=enable_scroll)
    widget = shell.widget
    outer = shell.content_layout

    # ROI presets section
    roi_presets_box = QGroupBox("ROI Presets")
    roi_presets_layout = QVBoxLayout(roi_presets_box)

    roi_presets_list = QListWidget()
    roi_presets_list.setSelectionMode(QAbstractItemView.SingleSelection)

    button_row = QWidget()
    button_layout = QHBoxLayout(button_row)
    button_layout.setContentsMargins(0, 0, 0, 0)

    save_roi_preset_button = QPushButton("Save Preset")
    remove_roi_preset_button = QPushButton("Remove Preset")
    place_roi_button = QPushButton("Apply Preset")

    button_layout.addWidget(save_roi_preset_button)
    button_layout.addWidget(remove_roi_preset_button)
    button_layout.addWidget(place_roi_button)

    roi_presets_layout.addWidget(roi_presets_list)
    roi_presets_description_label = QLabel("")
    roi_presets_description_label.setWordWrap(True)
    roi_presets_layout.addWidget(roi_presets_description_label)

    roi_placement_mode_combo = QComboBox()
    roi_placement_mode_combo.addItem("static", userData="static")
    roi_placement_mode_combo.addItem("auto", userData="auto")

    placement_row = QWidget()
    placement_layout = QHBoxLayout(placement_row)
    placement_layout.setContentsMargins(0, 0, 0, 0)
    placement_layout.addWidget(QLabel("Placement mode"))
    placement_layout.addWidget(roi_placement_mode_combo)
    roi_presets_layout.addWidget(placement_row)

    scope_row, current_frames_radio, all_frames_radio = (
        create_frame_scope_controls()
    )
    roi_presets_layout.addWidget(scope_row)

    roi_presets_layout.addWidget(button_row)

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
    include_all_channels_checkbox = QCheckBox("Include all channels")
    include_all_layers_checkbox.setChecked(False)
    include_all_frames_checkbox.setChecked(False)
    include_all_channels_checkbox.setChecked(False)

    # When include all layers, always include all channels
    include_all_layers_checkbox.toggled.connect(
        lambda checked: include_all_channels_checkbox.setChecked(True)
        if checked
        else None
    )

    save_roi_layout.addWidget(include_all_layers_checkbox)
    save_roi_layout.addWidget(include_all_frames_checkbox)
    save_roi_layout.addWidget(include_all_channels_checkbox)

    # Time analysis feature selection (default is mean)
    time_analysis_box = QGroupBox("Time Analysis")
    time_analysis_layout = QFormLayout(time_analysis_box)
    time_analysis_feature_combo = QComboBox()
    for feature_id in numeric_feature_ids():
        time_analysis_feature_combo.addItem(feature_id, userData=feature_id)
    time_analysis_feature_combo.setCurrentIndex(time_analysis_feature_combo.findData("mean"))
    time_analysis_layout.addRow("Feature", time_analysis_feature_combo)
    

    outer.addWidget(roi_presets_box)
    outer.addWidget(roi_box)
    outer.addWidget(save_roi_box)
    outer.addWidget(time_analysis_box)
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
        include_all_channels_checkbox=include_all_channels_checkbox,
        time_analysis_feature_combo=time_analysis_feature_combo,
        roi_presets_list=roi_presets_list,
        roi_presets_description_label=roi_presets_description_label,
        roi_placement_mode_combo=roi_placement_mode_combo,
        current_frames_radio=current_frames_radio,
        all_frames_radio=all_frames_radio,
        save_roi_preset_button=save_roi_preset_button,
        remove_roi_preset_button=remove_roi_preset_button,
        place_roi_button=place_roi_button,
    )
