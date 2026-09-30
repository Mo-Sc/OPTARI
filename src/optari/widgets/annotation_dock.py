from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
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

from optari.roi.roi_features import numeric_feature_ids
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
    save_scope_selected_radio: QRadioButton
    save_scope_track_radio: QRadioButton
    time_analysis_feature_combo: QComboBox
    time_analysis_selected_radio: QRadioButton
    time_analysis_track_radio: QRadioButton
    time_analysis_track_id_combo: QComboBox
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
    roi_presets_list.setToolTip(
        "Click to preview a preset; double-click to place it immediately"
    )

    button_row = QWidget()
    button_layout = QHBoxLayout(button_row)
    button_layout.setContentsMargins(0, 0, 0, 0)

    save_roi_preset_button = QPushButton("Save Preset")
    save_roi_preset_button.setToolTip(
        "Save the currently selected ROI shape in the viewer as a reusable preset"
    )
    remove_roi_preset_button = QPushButton("Remove Preset")
    place_roi_button = QPushButton("Apply Preset")
    place_roi_button.setToolTip(
        "Place the selected preset using the placement mode and scope below"
    )

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
    roi_placement_mode_combo.setToolTip(
        "Static: uses the preset's saved coordinates. Auto: places it inside the matching "
        "segmentation class, falling back to static if not found. With Scope All Frames, "
        "Auto anchors on each frame's own segmentation, skipping frames the class "
        "isn't present on"
    )

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
    roi_clipping_box.setToolTip(
        "Clamp out-of-range pixel values before computing ROI statistics "
        "(mutually exclusive with ROI Exclusion)"
    )
    roi_clip_form = QFormLayout(roi_clipping_box)
    roi_clip_min_edit, roi_clip_max_edit = create_range_edits()
    roi_clip_form.addRow("Min. Intensity", roi_clip_min_edit)
    roi_clip_form.addRow("Max. Intensity", roi_clip_max_edit)

    roi_exclusion_box = QGroupBox("ROI Exclusion")
    roi_exclusion_box.setCheckable(True)
    roi_exclusion_box.setChecked(False)
    roi_exclusion_box.setToolTip(
        "Drop out-of-range pixels entirely before computing ROI statistics "
        "(mutually exclusive with ROI Clipping)"
    )
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
    include_all_layers_checkbox.setToolTip(
        "Save this ROI's data for every layer in the scan; also enables Include all channels"
    )
    include_all_frames_checkbox.setToolTip(
        "Save this ROI's data for every frame in the scan"
    )
    include_all_channels_checkbox.setToolTip(
        "Save this ROI's data for every channel (wavelength/chromophore); "
        "auto-enabled by Include all layers"
    )

    # When include all layers, always include all channels
    include_all_layers_checkbox.toggled.connect(
        lambda checked: (
            include_all_channels_checkbox.setChecked(True) if checked else None
        )
    )

    save_scope_selected_radio = QRadioButton("Selected ROI")
    save_scope_track_radio = QRadioButton("Track ID")
    save_scope_selected_radio.setChecked(True)
    save_scope_selected_radio.setToolTip(
        "Measure every frame in the sequence using exactly the ROI you selected."
    )
    save_scope_track_radio.setToolTip(
        "Measure each frame using that frame's own ROI, if this ROI belongs to"
        " a tracked group. A frame the track has no record on is skipped."
    )
    save_scope_group = QButtonGroup(save_roi_box)
    save_scope_group.setExclusive(True)
    save_scope_group.addButton(save_scope_selected_radio)
    save_scope_group.addButton(save_scope_track_radio)

    save_scope_row = QWidget()
    save_scope_row_layout = QHBoxLayout(save_scope_row)
    save_scope_row_layout.setContentsMargins(20, 0, 0, 0)
    save_scope_row_layout.addWidget(save_scope_selected_radio)
    save_scope_row_layout.addWidget(save_scope_track_radio)
    save_scope_row.setEnabled(include_all_frames_checkbox.isChecked())
    include_all_frames_checkbox.toggled.connect(save_scope_row.setEnabled)

    save_roi_layout.addWidget(include_all_layers_checkbox)
    save_roi_layout.addWidget(include_all_channels_checkbox)
    save_roi_layout.addWidget(include_all_frames_checkbox)
    save_roi_layout.addWidget(save_scope_row)

    # Time analysis feature selection (default is mean)
    time_analysis_box = QGroupBox("Temporal Analysis")
    time_analysis_layout = QFormLayout(time_analysis_box)
    time_analysis_feature_combo = QComboBox()
    for feature_id in numeric_feature_ids():
        time_analysis_feature_combo.addItem(feature_id, userData=feature_id)
    time_analysis_feature_combo.setCurrentIndex(
        time_analysis_feature_combo.findData("mean")
    )
    time_analysis_layout.addRow("Feature", time_analysis_feature_combo)

    # Scope: "Selected ROI" measures each visible shape's own record on every frame
    # "Track ID" follows one tracked ROI's own record per frame instead, leaving a gap where it has no record on a frame.
    time_analysis_selected_radio = QRadioButton("Selected ROI")
    time_analysis_track_radio = QRadioButton("Track ID")
    time_analysis_selected_radio.setChecked(True)
    time_analysis_selected_radio.setToolTip(
        "Every ROI currently shown on the viewed frame is reused for every frame in the sequence."
    )
    time_analysis_track_radio.setToolTip(
        "Follow one tracked ROI across frames, measuring each frame on"
        " that frame's own ROI. Frames for which the track has no record on are left"
        " as a gap."
    )
    time_analysis_scope_group = QButtonGroup(time_analysis_box)
    time_analysis_scope_group.setExclusive(True)
    time_analysis_scope_group.addButton(time_analysis_selected_radio)
    time_analysis_scope_group.addButton(time_analysis_track_radio)

    scope_row = QWidget()
    scope_row_layout = QHBoxLayout(scope_row)
    scope_row_layout.setContentsMargins(0, 0, 0, 0)
    scope_row_layout.addWidget(time_analysis_selected_radio)
    scope_row_layout.addWidget(time_analysis_track_radio)
    time_analysis_layout.addRow("Scope", scope_row)

    time_analysis_track_id_combo = QComboBox()
    time_analysis_track_id_combo.setEnabled(False)
    time_analysis_track_id_combo.setToolTip(
        "Which tracked ROI to plot. Refreshed each time you generate the plot."
    )
    time_analysis_track_radio.toggled.connect(
        time_analysis_track_id_combo.setEnabled
    )
    time_analysis_layout.addRow("Track", time_analysis_track_id_combo)

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
        save_scope_selected_radio=save_scope_selected_radio,
        save_scope_track_radio=save_scope_track_radio,
        time_analysis_feature_combo=time_analysis_feature_combo,
        time_analysis_selected_radio=time_analysis_selected_radio,
        time_analysis_track_radio=time_analysis_track_radio,
        time_analysis_track_id_combo=time_analysis_track_id_combo,
        roi_presets_list=roi_presets_list,
        roi_presets_description_label=roi_presets_description_label,
        roi_placement_mode_combo=roi_placement_mode_combo,
        current_frames_radio=current_frames_radio,
        all_frames_radio=all_frames_radio,
        save_roi_preset_button=save_roi_preset_button,
        remove_roi_preset_button=remove_roi_preset_button,
        place_roi_button=place_roi_button,
    )
