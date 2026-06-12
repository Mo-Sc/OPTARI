from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtCore import Qt
from qtpy.QtGui import QDoubleValidator
from qtpy.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


@dataclass
class SegmentationDock:
    """Widget references used by segmentation-related controller callbacks."""

    widget: QWidget
    segmentation_model_combo: QComboBox
    segmentation_classes_list: QListWidget
    select_all_classes_button: QPushButton
    clear_classes_button: QPushButton
    roi_class_id_combo: QComboBox
    roi_shape_combo: QComboBox
    roi_width_edit: QLineEdit
    roi_height_edit: QLineEdit
    roi_top_margin_edit: QLineEdit
    generate_roi_button: QPushButton
    generate_tissue_segmentation_button: QPushButton
    segment_all_frames_checkbox: QCheckBox
    segmentation_status_label: QLabel


def create_segmentation_dock() -> SegmentationDock:
    """Create the segmentation dock with model/class and ROI-from-mask controls.

    Model combo is initially empty; populate via controller.initialize_ui().
    """
    widget = QWidget()
    shell_layout = QVBoxLayout(widget)
    shell_layout.setContentsMargins(0, 0, 0, 0)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    shell_layout.addWidget(scroll)

    content_widget = QWidget()
    scroll.setWidget(content_widget)
    outer = QVBoxLayout(content_widget)

    seg_box = QGroupBox("Segmentation")
    seg_layout = QVBoxLayout(seg_box)

    segmentation_model_combo = QComboBox()

    segmentation_classes_list = QListWidget()
    segmentation_classes_list.setSelectionMode(QListWidget.NoSelection)
    segmentation_classes_list.setMinimumHeight(140)

    classes_button_row = QWidget()
    classes_button_layout = QHBoxLayout(classes_button_row)
    classes_button_layout.setContentsMargins(0, 0, 0, 0)
    select_all_classes_button = QPushButton("Select All")
    clear_classes_button = QPushButton("Clear")
    classes_button_layout.addWidget(select_all_classes_button)
    classes_button_layout.addWidget(clear_classes_button)

    roi_class_id_combo = QComboBox()
    roi_shape_combo = QComboBox()
    roi_shape_combo.addItem("Ellipse", userData="ellipse")
    roi_shape_combo.addItem("Rectangle", userData="rectangle")
    roi_shape_combo.addItem("Polygon", userData="polygon")
    roi_shape_combo.setCurrentIndex(0)
    roi_width_edit = QLineEdit()
    roi_height_edit = QLineEdit()
    roi_top_margin_edit = QLineEdit()

    for edit in (roi_width_edit, roi_height_edit, roi_top_margin_edit):
        edit.setValidator(QDoubleValidator(0.0, 9999.0, 2))
        edit.setClearButtonEnabled(True)
        edit.setPlaceholderText("mm")

    generate_roi_button = QPushButton("Generate ROI from Mask")

    generate_tissue_segmentation_button = QPushButton(
        "Generate Tissue Segmentation"
    )
    segment_all_frames_checkbox = QCheckBox("Segment all frames")
    segmentation_status_label = QLabel("Select a model and run segmentation.")

    seg_layout.addWidget(QLabel("Model"))
    seg_layout.addWidget(segmentation_model_combo)
    seg_layout.addWidget(QLabel("Classes"))
    seg_layout.addWidget(segmentation_classes_list)
    seg_layout.addWidget(classes_button_row)

    seg_layout.addWidget(generate_tissue_segmentation_button)
    seg_layout.addWidget(segment_all_frames_checkbox)
    seg_layout.addWidget(segmentation_status_label)

    outer.addWidget(seg_box)
    roi_settings_box = QGroupBox("ROI from Mask")
    roi_settings_layout = QVBoxLayout(roi_settings_box)
    roi_settings_layout.addWidget(QLabel("Class ID"))
    roi_settings_layout.addWidget(roi_class_id_combo)
    roi_settings_layout.addWidget(QLabel("Shape"))
    roi_settings_layout.addWidget(roi_shape_combo)
    roi_settings_layout.addWidget(QLabel("Width"))
    roi_settings_layout.addWidget(roi_width_edit)
    roi_settings_layout.addWidget(QLabel("Height"))
    roi_settings_layout.addWidget(roi_height_edit)
    roi_settings_layout.addWidget(QLabel("Top Margin"))
    roi_settings_layout.addWidget(roi_top_margin_edit)
    roi_settings_layout.addWidget(generate_roi_button)
    outer.addWidget(roi_settings_box)
    outer.addStretch()

    return SegmentationDock(
        widget=widget,
        segmentation_model_combo=segmentation_model_combo,
        segmentation_classes_list=segmentation_classes_list,
        select_all_classes_button=select_all_classes_button,
        clear_classes_button=clear_classes_button,
        roi_class_id_combo=roi_class_id_combo,
        roi_shape_combo=roi_shape_combo,
        roi_width_edit=roi_width_edit,
        roi_height_edit=roi_height_edit,
        roi_top_margin_edit=roi_top_margin_edit,
        generate_roi_button=generate_roi_button,
        generate_tissue_segmentation_button=generate_tissue_segmentation_button,
        segment_all_frames_checkbox=segment_all_frames_checkbox,
        segmentation_status_label=segmentation_status_label,
    )
