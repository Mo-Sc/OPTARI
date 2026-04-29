from __future__ import annotations

import logging

import numpy as np
from napari.layers import Image
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QListWidgetItem

from patari.segmentation.segmenter import (
    create_segmenter,
    load_onnx_model_registry,
    SegmentationModelConfig,
)
from patari.segmentation.napari import (
    ensure_segmentation_labels_layer,
    set_segmentation_2d,
)
from patari.controllers.base import TaskControllerBase


logger = logging.getLogger(__name__)


class SegmentationController(TaskControllerBase):
    """Segmentation-related UI actions and geometry helpers."""

    def __init__(self, parent_controller):
        super().__init__(parent_controller)
        self._segmentation_model_registry = load_onnx_model_registry()
        self._active_segmentation_model_id = next(
            iter(self._segmentation_model_registry)
        )
        self._segmenter = None
        self._segmenter_model_id = None

    def bind_events(self) -> None:
        """Connect segmentation dock signals."""
        self.patari_controller.segmentation.segmentation_model_combo.currentIndexChanged.connect(
            self.on_segmentation_model_changed
        )
        self.patari_controller.segmentation.select_all_classes_button.clicked.connect(
            self.on_segmentation_select_all_classes_clicked
        )
        self.patari_controller.segmentation.clear_classes_button.clicked.connect(
            self.on_segmentation_clear_classes_clicked
        )
        self.patari_controller.segmentation.generate_roi_button.clicked.connect(
            self.on_generate_roi_from_mask_clicked
        )
        self.patari_controller.segmentation.generate_tissue_segmentation_button.clicked.connect(
            self.on_generate_tissue_segmentation_clicked
        )

    def unbind_events(self) -> None:
        """Disconnect segmentation dock signals."""
        try:
            self.patari_controller.segmentation.segmentation_model_combo.currentIndexChanged.disconnect(
                self.on_segmentation_model_changed
            )
            self.patari_controller.segmentation.select_all_classes_button.clicked.disconnect(
                self.on_segmentation_select_all_classes_clicked
            )
            self.patari_controller.segmentation.clear_classes_button.clicked.disconnect(
                self.on_segmentation_clear_classes_clicked
            )
            self.patari_controller.segmentation.generate_roi_button.clicked.disconnect(
                self.on_generate_roi_from_mask_clicked
            )
            self.patari_controller.segmentation.generate_tissue_segmentation_button.clicked.disconnect(
                self.on_generate_tissue_segmentation_clicked
            )
        except Exception as e:
            logger.exception(
                "Error unbinding segmentation dock signals: %s", e
            )

    def initialize_ui(self) -> None:
        """Initialize model combo and populate default classes once."""

        dock = self.patari_controller.segmentation

        if dock.segmentation_model_combo.count() == 0:
            # Populate available models once on first dock init.
            for model_id in self.segmentation_model_options():
                dock.segmentation_model_combo.addItem(
                    model_id, userData=model_id
                )

            # Set to active model (default is first in registry).
            for i in range(dock.segmentation_model_combo.count()):
                if (
                    dock.segmentation_model_combo.itemData(i)
                    == self.active_segmentation_model_id
                ):
                    dock.segmentation_model_combo.setCurrentIndex(i)
                    break

        # Populate classes for the current model.
        self.on_segmentation_model_changed()

    def teardown(self) -> None:
        """Release cached segmentation model to free memory."""
        if self._segmenter is not None:
            logger.info(
                "Releasing segmentation model %s", self._segmenter_model_id
            )
            self._segmenter = None
            self._segmenter_model_id = None

    def segmentation_model_options(self) -> list[str]:
        """Return model IDs for the model combo."""
        return list(self._segmentation_model_registry.keys())

    @property
    def active_segmentation_model_id(self) -> str:
        return self._active_segmentation_model_id

    def set_active_segmentation_model(self, model_id: str) -> None:
        if model_id not in self._segmentation_model_registry:
            raise ValueError(f"Unknown segmentation model: {model_id}")
        self._active_segmentation_model_id = model_id

    def _active_segmentation_model_config(self) -> SegmentationModelConfig:
        """Return config for the currently selected segmentation model."""
        return self._segmentation_model_registry[
            self._active_segmentation_model_id
        ]

    def active_segmentation_class_items(self) -> list[tuple[int, str]]:
        """Return sorted ``(class_id, class_name)`` entries for the active model."""
        return sorted(
            self._active_segmentation_model_config().class_names.items()
        )

    def selected_segmentation_class_ids(self) -> set[int]:
        seg_dock = self.patari_controller.segmentation
        if seg_dock is None:
            return set()

        class_ids: set[int] = set()
        for i in range(seg_dock.segmentation_classes_list.count()):
            item = seg_dock.segmentation_classes_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                class_ids.add(int(item.data(Qt.ItemDataRole.UserRole)))
        return class_ids

    def get_segmenter(self):
        """Lazily create/cache the segmenter for the active model selection."""
        if (
            self._segmenter is None
            or self._segmenter_model_id != self._active_segmentation_model_id
        ):
            self._segmenter = create_segmenter(
                self._active_segmentation_model_config()
            )
            self._segmenter_model_id = self._active_segmentation_model_id
        return self._segmenter

    @staticmethod
    def _compute_roi_box_from_mask(
        class_mask: np.ndarray,
        *,
        sx: float,
        sy: float,
        top_margin_mm: float | None,
        width_mm: float | None,
        height_mm: float | None,
    ) -> tuple[tuple[int, int, int, int] | None, str | None]:
        """Return a cropped ROI box ``(top, bottom, left, right)`` in px.

        ROI placement semantics:
        - anchor the top edge to the selected class at image center,
        - apply top margin in mm (downwards),
        - crop width symmetrically to final width in mm,
        - crop height from the bottom only to final height in mm.
        """
        ys, xs = np.where(class_mask)
        bottom = int(ys.max())
        left = int(xs.min())
        right = int(xs.max())

        center_col = int(class_mask.shape[1] // 2)
        center_rows = np.where(class_mask[:, center_col])[0]
        if center_rows.size == 0:
            return None, "Selected class is not present at image center"
        top = int(center_rows[0])

        if top_margin_mm is not None:
            top += int(round(top_margin_mm / sy))

        if width_mm is not None:
            current_width_mm = float(right - left) * sx
            trim_x = int(
                round(max(0.0, current_width_mm - width_mm) / (2.0 * sx))
            )
            left += trim_x
            right -= trim_x

        if height_mm is not None:
            current_height_mm = float(bottom - top) * sy
            trim_bottom = int(
                round(max(0.0, current_height_mm - height_mm) / sy)
            )
            bottom -= trim_bottom

        if right <= left or bottom <= top:
            return None, "ROI settings collapse the class region"

        return (top, bottom, left, right), None

    @staticmethod
    def resolve_us_layer(controller) -> Image | None:
        """Find US image layer for segmentation (segmentation always runs on US)."""
        for layer in controller.viewer.layers:
            if isinstance(layer, Image) and layer.metadata.get("type") == "us":
                return layer
        return None

    @staticmethod
    def us_slice_2d(controller, us_layer: Image) -> np.ndarray | None:
        data = np.asarray(us_layer.data)
        if data.ndim == 2:
            return data

        pt = list(controller.viewer.dims.point)
        frame_idx = int(round(pt[0])) if len(pt) >= 1 else 0

        frame_idx = int(np.clip(frame_idx, 0, max(0, data.shape[0] - 1)))

        if data.ndim == 3:
            return data[frame_idx]
        if data.ndim >= 4:
            # e.g. (frame, channel, y, x)
            return data[frame_idx, 0]

        return None

    def on_segmentation_model_changed(self) -> None:
        if self.patari_controller.segmentation is None:
            return

        model_id = (
            self.patari_controller.segmentation.segmentation_model_combo.currentData()
        )
        self.set_active_segmentation_model(str(model_id))
        self.populate_segmentation_controls()
        self.patari_controller.segmentation.segmentation_status_label.setText(
            f"Model: {self.patari_controller.segmentation.segmentation_model_combo.currentText()}"
        )

    def populate_segmentation_controls(self) -> None:
        seg_dock = self.patari_controller.segmentation
        if seg_dock is None:
            return

        seg_dock.segmentation_classes_list.clear()
        seg_dock.roi_class_id_combo.clear()

        for class_id, class_name in self.active_segmentation_class_items():
            # Add to classes list
            item = QListWidgetItem(f"{class_id}: {class_name}")
            item.setData(Qt.ItemDataRole.UserRole, class_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            seg_dock.segmentation_classes_list.addItem(item)

            # Add to class combo
            seg_dock.roi_class_id_combo.addItem(
                f"{class_id}: {class_name}", userData=class_id
            )

        # Set default to first non-background class (skip class 0)
        for i in range(seg_dock.roi_class_id_combo.count()):
            if seg_dock.roi_class_id_combo.itemData(i) != 0:
                seg_dock.roi_class_id_combo.setCurrentIndex(i)
                break

    def set_all_segmentation_classes_checked(self, checked: bool) -> None:
        seg_dock = self.patari_controller.segmentation
        if seg_dock is None:
            return

        check_state = (
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )
        for i in range(seg_dock.segmentation_classes_list.count()):
            item = seg_dock.segmentation_classes_list.item(i)
            if item is not None:
                item.setCheckState(check_state)

    def on_segmentation_select_all_classes_clicked(self) -> None:
        self.set_all_segmentation_classes_checked(checked=True)

    def on_segmentation_clear_classes_clicked(self) -> None:
        self.set_all_segmentation_classes_checked(checked=False)

    def on_generate_roi_from_mask_clicked(self) -> None:
        """Generate one rectangular ROI from the selected segmentation class."""
        seg_dock = self.patari_controller.segmentation
        if seg_dock is None:
            return

        if "Segmentation" not in self.viewer.layers:
            seg_dock.segmentation_status_label.setText(
                "No segmentation mask found"
            )
            return

        seg_layer = self.viewer.layers["Segmentation"]
        class_id = seg_dock.roi_class_id_combo.currentData()
        if class_id is None:
            seg_dock.segmentation_status_label.setText("Select a class id")
            return

        seg = np.asarray(seg_layer.data)
        class_mask = seg == int(class_id)
        if not np.any(class_mask):
            seg_dock.segmentation_status_label.setText(
                "Selected class is not present in the mask"
            )
            return

        # Extract scale and translate directly as floats from layer attributes
        scale = getattr(seg_layer, "scale", (1.0, 1.0))
        translate = getattr(seg_layer, "translate", (0.0, 0.0))
        sy, sx = float(scale[-2]), float(scale[-1])
        ty, tx = float(translate[-2]), float(translate[-1])

        # Parse ROI parameters from UI, allowing empty fields
        def parse_roi_param(text: str) -> float | None:
            return float(text) if text.strip() else None

        top_margin_mm = parse_roi_param(seg_dock.roi_top_margin_edit.text())
        width_mm = parse_roi_param(seg_dock.roi_width_edit.text())
        height_mm = parse_roi_param(seg_dock.roi_height_edit.text())

        roi_box, error_text = self._compute_roi_box_from_mask(
            class_mask,
            sx=sx,
            sy=sy,
            top_margin_mm=top_margin_mm,
            width_mm=width_mm,
            height_mm=height_mm,
        )
        if roi_box is None:
            seg_dock.segmentation_status_label.setText(
                str(error_text or "Failed to compute ROI")
            )
            return

        top, bottom, left, right = roi_box

        # Convert the cropped class box into world coordinates and add it as a polygon.
        verts = np.asarray(
            [
                [ty + top * sy, tx + left * sx],
                [ty + top * sy, tx + right * sx],
                [ty + bottom * sy, tx + right * sx],
                [ty + bottom * sy, tx + left * sx],
            ],
            dtype=float,
        )

        self.patari_controller.shapes_layer.add(verts, shape_type="polygon")
        # Colors and live table are refreshed by shapes_layer.data event.
        seg_dock.segmentation_status_label.setText(
            f"ROI generated from class {class_id}"
        )

    def on_generate_tissue_segmentation_clicked(self) -> None:
        """Run segmentation on the currently visible US slice and update labels."""
        seg_dock = self.patari_controller.segmentation
        if seg_dock is None:
            return

        us_layer = self.resolve_us_layer(self.patari_controller)
        if us_layer is None:
            seg_dock.segmentation_status_label.setText("No US layer found")
            return

        data_slice = self.us_slice_2d(self.patari_controller, us_layer)
        if data_slice is None:
            seg_dock.segmentation_status_label.setText(
                "Invalid US volume dimension"
            )
            return

        selected_ids = self.selected_segmentation_class_ids()
        if not selected_ids:
            seg_dock.segmentation_status_label.setText("No classes selected")
            return

        try:
            segmenter = self.get_segmenter()
        except ValueError as err:
            logger.exception("Failed to load Segmentation model")
            seg_dock.segmentation_status_label.setText(f"Error: {err}")
            return

        try:
            seg_dock.segmentation_status_label.setText(
                f"Generating mask with {self.active_segmentation_model_id}..."
            )
            self.viewer.window.qt_viewer.setCursor(Qt.CursorShape.WaitCursor)
            self.viewer.window.qt_viewer.repaint()

            seg_result = segmenter.predict(data_slice)
            mask = np.asarray(seg_result.seg)
            mask = np.where(np.isin(mask, list(selected_ids)), mask, 0)

            label_layer = ensure_segmentation_labels_layer(
                self.viewer,
                name="Segmentation",
            )
            set_segmentation_2d(
                label_layer,
                mask,
                class_names=seg_result.class_names,
                reference_layer=us_layer,
            )

            seg_dock.segmentation_status_label.setText(
                "Segmentation finished successfully"
            )
        except Exception as e:
            logger.exception("Segmentation inference failed")
            seg_dock.segmentation_status_label.setText(
                f"Error updating segmentation mask: {e}"
            )
        finally:
            self.viewer.window.qt_viewer.unsetCursor()
