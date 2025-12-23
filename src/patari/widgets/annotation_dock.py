from __future__ import annotations

from dataclasses import dataclass

from patari.config import ROI_PLACEMENT_PRESETS
from qtpy.QtGui import QDoubleValidator
from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass
class AnnotationDock:
    widget: QWidget
    roi_min_edit: QLineEdit
    roi_max_edit: QLineEdit

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
    widget = QWidget()
    outer = QVBoxLayout(widget)

    # --- ROI Settings ---
    roi_box = QGroupBox("ROI Thresholds")
    roi_form = QFormLayout(roi_box)

    roi_min_edit = QLineEdit()
    roi_max_edit = QLineEdit()
    validator = QDoubleValidator()
    roi_min_edit.setValidator(validator)
    roi_max_edit.setValidator(validator)
    roi_min_edit.setPlaceholderText("(unset)")
    roi_max_edit.setPlaceholderText("(unset)")
    roi_min_edit.setClearButtonEnabled(True)
    roi_max_edit.setClearButtonEnabled(True)

    roi_form.addRow("Min. Intensity", roi_min_edit)
    roi_form.addRow("Max. intensity", roi_max_edit)

    # --- Segmentation ---
    seg_box = QGroupBox("Segmentation")
    seg_form = QFormLayout(seg_box)

    segmentation_model_combo = QComboBox()
    # Dummy model list for now
    segmentation_model_combo.addItem("DummySeg")

    generate_tissue_segmentation_button = QPushButton(
        "Generate Tissue Segmentation"
    )
    segmentation_status_label = QLabel("Click to add the Segmentation layer.")

    seg_form.addRow("Model", segmentation_model_combo)
    seg_form.addRow(generate_tissue_segmentation_button)
    seg_form.addRow(segmentation_status_label)

    # --- ROI placement ---
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
    outer.addWidget(seg_box, stretch=1)
    outer.addWidget(roi_place_box, stretch=1)

    return AnnotationDock(
        widget=widget,
        roi_min_edit=roi_min_edit,
        roi_max_edit=roi_max_edit,
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
