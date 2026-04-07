from __future__ import annotations

from dataclasses import dataclass

from patari.config import ROI_PLACEMENT_PRESETS
from qtpy.QtCore import Qt
from qtpy.QtGui import QDoubleValidator
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
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
    include_all_frames_checkbox: QCheckBox
    include_all_wavelengths_checkbox: QCheckBox

    # Segmentation
    segmentation_model_combo: QComboBox
    generate_tissue_segmentation_button: QPushButton
    segmentation_status_label: QLabel

    # ROI placement
    roi_preset_buttons: list[QPushButton]
    roi_class_combo: QComboBox
    roi_type_combo: QComboBox
    roi_width_edit: QLineEdit
    roi_height_edit: QLineEdit
    roi_depth_edit: QLineEdit
    place_roi_button: QPushButton
    roi_status_label: QLabel


def create_annotation_dock() -> AnnotationDock:
    # Outer shell — what napari receives as the dock widget
    widget = QWidget()
    shell_layout = QVBoxLayout(widget)
    shell_layout.setContentsMargins(0, 0, 0, 0)

    # Scroll area fills the shell
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    shell_layout.addWidget(scroll)

    # Content widget lives inside the scroll area
    content_widget = QWidget()
    scroll.setWidget(content_widget)
    outer = QVBoxLayout(content_widget)

    # ------------------------------------------------------------------ #
    # ROI Settings section                                                 #
    # ------------------------------------------------------------------ #
    roi_box = QGroupBox("ROI Settings")
    roi_layout = QVBoxLayout(roi_box)

    def _make_range_edits() -> tuple[QLineEdit, QLineEdit]:
        min_edit = QLineEdit()
        max_edit = QLineEdit()
        validator = QDoubleValidator()
        min_edit.setValidator(validator)
        max_edit.setValidator(validator)
        min_edit.setPlaceholderText("(unset)")
        max_edit.setPlaceholderText("(unset)")
        min_edit.setClearButtonEnabled(True)
        max_edit.setClearButtonEnabled(True)
        return min_edit, max_edit

    roi_clipping_box = QGroupBox("ROI Clipping")
    roi_clipping_box.setCheckable(True)
    roi_clipping_box.setChecked(True)
    roi_clip_form = QFormLayout(roi_clipping_box)
    roi_clip_min_edit, roi_clip_max_edit = _make_range_edits()
    roi_clip_form.addRow("Min. Intensity", roi_clip_min_edit)
    roi_clip_form.addRow("Max. Intensity", roi_clip_max_edit)

    roi_exclusion_box = QGroupBox("ROI Exclusion")
    roi_exclusion_box.setCheckable(True)
    roi_exclusion_box.setChecked(False)
    roi_exclude_form = QFormLayout(roi_exclusion_box)
    roi_exclude_min_edit, roi_exclude_max_edit = _make_range_edits()
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

    include_all_frames_checkbox = QCheckBox("Include all frames")
    include_all_wavelengths_checkbox = QCheckBox("Include all wavelengths")
    include_all_frames_checkbox.setChecked(False)
    include_all_wavelengths_checkbox.setChecked(False)

    roi_layout.addWidget(roi_clipping_box)
    roi_layout.addWidget(roi_exclusion_box)
    roi_layout.addWidget(include_all_frames_checkbox)
    roi_layout.addWidget(include_all_wavelengths_checkbox)

    # ------------------------------------------------------------------ #
    # Segmentation section                                                 #
    # ------------------------------------------------------------------ #
    seg_box = QGroupBox("Segmentation")
    seg_form = QFormLayout(seg_box)

    segmentation_model_combo = QComboBox()
    segmentation_model_combo.addItem("DummySeg")

    generate_tissue_segmentation_button = QPushButton(
        "Generate Tissue Segmentation"
    )
    segmentation_status_label = QLabel("Click to add the Segmentation layer.")

    seg_form.addRow("Model", segmentation_model_combo)
    seg_form.addRow(generate_tissue_segmentation_button)
    seg_form.addRow(segmentation_status_label)

    # ------------------------------------------------------------------ #
    # Auto-ROI placement section                                           #
    # ------------------------------------------------------------------ #
    roi_place_box = QGroupBox("Auto-ROI")
    roi_place_form = QFormLayout(roi_place_box)

    preset_row = QWidget()
    preset_layout = QHBoxLayout(preset_row)
    preset_layout.setContentsMargins(0, 0, 0, 0)
    roi_preset_buttons: list[QPushButton] = []
    for preset_index, preset in enumerate(ROI_PLACEMENT_PRESETS[:3]):
        btn = QPushButton(str(preset.get("name", f"Preset {preset_index+1}")))
        btn.setProperty("roi_preset_index", int(preset_index))
        roi_preset_buttons.append(btn)
        preset_layout.addWidget(btn)

    roi_class_combo = QComboBox()
    roi_class_combo.setEnabled(False)
    roi_class_combo.setToolTip("Generate a tissue segmentation first.")

    roi_type_combo = QComboBox()
    roi_type_combo.addItem("Ellipse", userData="ellipse")

    roi_width_edit = QLineEdit()
    roi_height_edit = QLineEdit()
    roi_depth_edit = QLineEdit()

    mm_validator = QDoubleValidator()
    mm_validator.setBottom(0.0)
    roi_width_edit.setValidator(mm_validator)
    roi_height_edit.setValidator(mm_validator)
    roi_depth_edit.setValidator(mm_validator)

    roi_width_edit.setPlaceholderText("mm")
    roi_height_edit.setPlaceholderText("mm")
    roi_depth_edit.setPlaceholderText("mm")

    roi_width_edit.setClearButtonEnabled(True)
    roi_height_edit.setClearButtonEnabled(True)
    roi_depth_edit.setClearButtonEnabled(True)

    place_roi_button = QPushButton("Place ROI")
    roi_status_label = QLabel("Generate segmentation, then click 'Place ROI'.")

    roi_place_form.addRow("Presets", preset_row)
    roi_place_form.addRow("Tissue Class", roi_class_combo)
    roi_place_form.addRow("ROI Type", roi_type_combo)
    roi_place_form.addRow("ROI Width", roi_width_edit)
    roi_place_form.addRow("ROI Height", roi_height_edit)
    roi_place_form.addRow("ROI Depth", roi_depth_edit)
    roi_place_form.addRow(place_roi_button)
    roi_place_form.addRow(roi_status_label)

    outer.addWidget(roi_box)
    outer.addWidget(seg_box)
    outer.addWidget(roi_place_box)
    outer.addStretch()

    return AnnotationDock(
        widget=widget,
        roi_clipping_box=roi_clipping_box,
        roi_clip_min_edit=roi_clip_min_edit,
        roi_clip_max_edit=roi_clip_max_edit,
        roi_exclusion_box=roi_exclusion_box,
        roi_exclude_min_edit=roi_exclude_min_edit,
        roi_exclude_max_edit=roi_exclude_max_edit,
        include_all_frames_checkbox=include_all_frames_checkbox,
        include_all_wavelengths_checkbox=include_all_wavelengths_checkbox,
        segmentation_model_combo=segmentation_model_combo,
        generate_tissue_segmentation_button=generate_tissue_segmentation_button,
        segmentation_status_label=segmentation_status_label,
        roi_preset_buttons=roi_preset_buttons,
        roi_class_combo=roi_class_combo,
        roi_type_combo=roi_type_combo,
        roi_width_edit=roi_width_edit,
        roi_height_edit=roi_height_edit,
        roi_depth_edit=roi_depth_edit,
        place_roi_button=place_roi_button,
        roi_status_label=roi_status_label,
    )
