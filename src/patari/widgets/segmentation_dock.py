from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


@dataclass
class SegmentationDock:
    widget: QWidget
    segmentation_model_combo: QComboBox
    generate_tissue_segmentation_button: QPushButton
    segmentation_status_label: QLabel


def create_segmentation_dock(
    model_options: list[tuple[str, str]],
    default_model_id: str,
) -> SegmentationDock:
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
    seg_form = QFormLayout(seg_box)

    segmentation_model_combo = QComboBox()
    for model_id, display_name in model_options:
        segmentation_model_combo.addItem(display_name, userData=model_id)

    for i in range(segmentation_model_combo.count()):
        if segmentation_model_combo.itemData(i) == default_model_id:
            segmentation_model_combo.setCurrentIndex(i)
            break

    generate_tissue_segmentation_button = QPushButton(
        "Generate Tissue Segmentation"
    )
    segmentation_status_label = QLabel("Select a model and run segmentation.")

    seg_form.addRow("Model", segmentation_model_combo)
    seg_form.addRow(generate_tissue_segmentation_button)
    seg_form.addRow(segmentation_status_label)

    outer.addWidget(seg_box)
    outer.addStretch()

    return SegmentationDock(
        widget=widget,
        segmentation_model_combo=segmentation_model_combo,
        generate_tissue_segmentation_button=generate_tissue_segmentation_button,
        segmentation_status_label=segmentation_status_label,
    )
