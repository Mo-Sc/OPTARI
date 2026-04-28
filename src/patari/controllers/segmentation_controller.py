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


logger = logging.getLogger(__name__)


class SegmentationController:
    """Segmentation-related UI actions and geometry helpers.

    This controller keeps segmentation event handlers and ROI-from-mask
    geometry logic together.
    """

    def __init__(self, parent_controller):
        self.controller = parent_controller
        self._segmentation_model_registry = load_onnx_model_registry()
        self._active_segmentation_model_id = next(
            iter(self._segmentation_model_registry)
        )
        self._segmenter = None
        self._segmenter_model_id = None

    def segmentation_model_options(self) -> list[tuple[str, str]]:
        """Return ``(model_id, display_name)`` pairs for the model combo."""
        return [
            (spec.model_id, spec.model_id)
            for spec in self._segmentation_model_registry.values()
        ]

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
        items = list(
            self._active_segmentation_model_config().class_names.items()
        )
        return sorted(
            (int(class_id), str(class_name)) for class_id, class_name in items
        )

    def selected_segmentation_class_ids(self) -> set[int]:
        if self.controller.segmentation is None:
            return set()

        class_ids: set[int] = set()
        classes_list = self.controller.segmentation.segmentation_classes_list
        for i in range(classes_list.count()):
            item = classes_list.item(i)
            if item is None:
                continue
            if item.checkState() == Qt.CheckState.Checked:
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
        if self.controller.segmentation is None:
            return

        model_id = (
            self.controller.segmentation.segmentation_model_combo.currentData()
        )
        self.set_active_segmentation_model(str(model_id))
        self.populate_segmentation_controls()
        self.controller.segmentation.segmentation_status_label.setText(
            f"Model: {self.controller.segmentation.segmentation_model_combo.currentText()}"
        )

    def populate_segmentation_controls(self) -> None:
        if self.controller.segmentation is None:
            return

        classes_list = self.controller.segmentation.segmentation_classes_list
        class_combo = self.controller.segmentation.roi_class_id_combo
        classes_list.clear()
        class_combo.clear()
        for (
            class_id,
            class_name,
        ) in self.active_segmentation_class_items():
            item = QListWidgetItem(f"{class_id}: {class_name}")
            item.setData(Qt.ItemDataRole.UserRole, int(class_id))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            classes_list.addItem(item)
            class_combo.addItem(
                f"{class_id}: {class_name}", userData=int(class_id)
            )

        if class_combo.count() > 0:
            for i in range(class_combo.count()):
                if int(class_combo.itemData(i)) != 0:
                    class_combo.setCurrentIndex(i)
                    break

    def set_all_segmentation_classes_checked(self, checked: bool) -> None:
        if self.controller.segmentation is None:
            return

        classes_list = self.controller.segmentation.segmentation_classes_list
        check_state = (
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )
        for i in range(classes_list.count()):
            item = classes_list.item(i)
            if item is not None:
                item.setCheckState(check_state)

    def on_segmentation_select_all_classes_clicked(self) -> None:
        self.set_all_segmentation_classes_checked(checked=True)

    def on_segmentation_clear_classes_clicked(self) -> None:
        self.set_all_segmentation_classes_checked(checked=False)

    def on_generate_roi_from_mask_clicked(self) -> None:
        """Generate one rectangular ROI from the selected segmentation class."""
        if self.controller.segmentation is None:
            return

        if "Segmentation" not in self.controller.viewer.layers:
            self.controller.segmentation.segmentation_status_label.setText(
                "No segmentation mask found"
            )
            return

        seg_layer = self.controller.viewer.layers["Segmentation"]
        seg = np.asarray(seg_layer.data)
        class_names = dict(getattr(seg_layer, "metadata", {}) or {}).get(
            "class_names", {}
        )
        class_id = (
            self.controller.segmentation.roi_class_id_combo.currentData()
        )
        if class_id is None:
            self.controller.segmentation.segmentation_status_label.setText(
                "Select a class id"
            )
            return

        class_mask = seg == int(class_id)
        if not np.any(class_mask):
            self.controller.segmentation.segmentation_status_label.setText(
                "Selected class is not present in the mask"
            )
            return

        scale = tuple(getattr(seg_layer, "scale", (1.0, 1.0)))
        translate = tuple(getattr(seg_layer, "translate", (0.0, 0.0)))
        # Segmentation layer scale/translate carry the mm calibration.
        sy = float(scale[-2])
        sx = float(scale[-1])
        ty = float(translate[-2])
        tx = float(translate[-1])

        top_margin_text = (
            self.controller.segmentation.roi_top_margin_edit.text()
        )
        width_text = self.controller.segmentation.roi_width_edit.text()
        height_text = self.controller.segmentation.roi_height_edit.text()

        top_margin_mm = (
            float(top_margin_text) if top_margin_text.strip() else None
        )
        width_mm = float(width_text) if width_text.strip() else None
        height_mm = float(height_text) if height_text.strip() else None

        roi_box, error_text = self._compute_roi_box_from_mask(
            class_mask,
            sx=sx,
            sy=sy,
            top_margin_mm=top_margin_mm,
            width_mm=width_mm,
            height_mm=height_mm,
        )
        if roi_box is None:
            self.controller.segmentation.segmentation_status_label.setText(
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

        self.controller.shapes_layer.add(verts, shape_type="polygon")
        # from patari.controllers.roi_controller import RoiController
        # RoiController.set_last_roi_position(
        #     self.controller,
        #     str(class_names.get(int(class_id), int(class_id))),
        # )
        # Colors and live table are refreshed by shapes_layer.data event.
        self.controller.segmentation.segmentation_status_label.setText(
            f"ROI generated from class {class_names.get(int(class_id), int(class_id))}"
        )

    def on_generate_tissue_segmentation_clicked(self) -> None:
        """Run segmentation on the currently visible US slice and update labels."""
        if self.controller.segmentation is None:
            return

        us_layer = self.resolve_us_layer(self.controller)
        if us_layer is None:
            self.controller.segmentation.segmentation_status_label.setText(
                "No US layer found"
            )
            return

        data_slice = self.us_slice_2d(self.controller, us_layer)
        if data_slice is None:
            self.controller.segmentation.segmentation_status_label.setText(
                "Invalid US volume dimension"
            )
            return

        selected_ids = self.selected_segmentation_class_ids()
        if not selected_ids:
            self.controller.segmentation.segmentation_status_label.setText(
                "No classes selected"
            )
            return

        try:
            segmenter = self.get_segmenter()
        except ValueError as err:
            logger.exception("Failed to load Segmentation model")
            self.controller.segmentation.segmentation_status_label.setText(
                f"Error: {err}"
            )
            return

        try:
            self.controller.segmentation.segmentation_status_label.setText(
                f"Generating mask with {self.active_segmentation_model_id}..."
            )
            self.controller.viewer.window.qt_viewer.setCursor(
                Qt.CursorShape.WaitCursor
            )
            self.controller.viewer.window.qt_viewer.repaint()

            mask = segmenter.predict(data_slice, selected_ids)

            label_layer = ensure_segmentation_labels_layer(
                self.controller.viewer,
                target_mask_shape=data_slice.shape,
                class_names=self._active_segmentation_model_config().class_names,
            )
            set_segmentation_2d(self.controller, us_layer, label_layer, mask)

            self.controller.segmentation.segmentation_status_label.setText(
                "Segmentation finished successfully"
            )
        except Exception as e:
            logger.exception("Segmentation inference failed")
            self.controller.segmentation.segmentation_status_label.setText(
                f"Error updating segmentation mask: {e}"
            )
        finally:
            self.controller.viewer.window.qt_viewer.unsetCursor()
            return

        model_id = (
            controller.segmentation.segmentation_model_combo.currentData()
        )
        controller.set_active_segmentation_model(str(model_id))

        us_layer = SegmentationController.resolve_us_layer(controller)
        if us_layer is None:
            controller.segmentation.segmentation_status_label.setText(
                "No US layer found"
            )
            return

        us_2d = SegmentationController.us_slice_2d(controller, us_layer)
        if us_2d is None:
            controller.segmentation.segmentation_status_label.setText(
                "US layer has unsupported shape"
            )
            return

        controller.segmentation.segmentation_status_label.setText(
            "Running segmentation…"
        )

        result = controller.get_segmenter().predict(us_2d)

        selected_class_ids = controller.selected_segmentation_class_ids()
        if selected_class_ids:
            selected_ids = np.asarray(
                sorted(selected_class_ids), dtype=np.int32
            )
            # Keep only checked classes; everything else becomes background.
            keep_mask = np.isin(result.seg, selected_ids)
            seg_filtered = np.where(keep_mask, result.seg, 0).astype(
                np.int32, copy=False
            )
        else:
            seg_filtered = np.zeros_like(result.seg, dtype=np.int32)

        class_names = {
            int(class_id): str(name)
            for class_id, name in result.class_names.items()
            if int(class_id) == 0 or int(class_id) in selected_class_ids
        }
        if 0 not in class_names:
            class_names[0] = "background"

        labels = ensure_segmentation_labels_layer(controller.viewer)
        set_segmentation_2d(
            labels,
            seg_filtered,
            class_names=class_names,
            reference_layer=us_layer,
        )

        logger.info(
            "segmentation generated model=%s selected_classes=%s shape=%s",
            controller.active_segmentation_model_id,
            sorted(selected_class_ids),
            tuple(seg_filtered.shape),
        )
        controller.segmentation.segmentation_status_label.setText(
            f"Segmentation layer added ({len(selected_class_ids)} classes)."
        )
