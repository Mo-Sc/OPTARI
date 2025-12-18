from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtGui import QDoubleValidator
from qtpy.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass
class AnnotationDock:
    widget: QWidget
    roi_min_edit: QLineEdit
    roi_max_edit: QLineEdit


def create_annotation_dock() -> AnnotationDock:
    widget = QWidget()
    outer = QVBoxLayout(widget)

    # --- ROI Settings ---
    roi_box = QGroupBox("ROI Settings")
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

    roi_form.addRow("Min ROI intensity", roi_min_edit)
    roi_form.addRow("Max ROI intensity", roi_max_edit)

    # --- Segmentation (empty placeholder for now) ---
    seg_box = QGroupBox("Segmentation")
    seg_layout = QVBoxLayout(seg_box)
    seg_layout.addWidget(QLabel(""))

    outer.addWidget(roi_box)
    outer.addWidget(seg_box, stretch=1)

    return AnnotationDock(
        widget=widget,
        roi_min_edit=roi_min_edit,
        roi_max_edit=roi_max_edit,
    )
