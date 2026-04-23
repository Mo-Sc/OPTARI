from __future__ import annotations

import logging

import numpy as np
from napari.layers import Image
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QListWidgetItem

from patari.segmentation.napari import (
    ensure_segmentation_labels_layer,
    set_segmentation_2d,
)


logger = logging.getLogger(__name__)


class SegmentationController:
    """Segmentation-related UI actions and geometry helpers.

    This controller keeps segmentation event handlers and ROI-from-mask
    geometry logic together, while shared app state remains on
    ``PatariController``.
    """

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

    @staticmethod
    def on_segmentation_model_changed(controller) -> None:
        if controller.segmentation is None:
            return

        model_id = (
            controller.segmentation.segmentation_model_combo.currentData()
        )
        controller.set_active_segmentation_model(str(model_id))
        SegmentationController.populate_segmentation_controls(controller)
        controller.segmentation.segmentation_status_label.setText(
            f"Model: {controller.segmentation.segmentation_model_combo.currentText()}"
        )

    @staticmethod
    def populate_segmentation_controls(controller) -> None:
        if controller.segmentation is None:
            return

        classes_list = controller.segmentation.segmentation_classes_list
        class_combo = controller.segmentation.roi_class_id_combo
        classes_list.clear()
        class_combo.clear()
        for (
            class_id,
            class_name,
        ) in controller.active_segmentation_class_items():
            item = QListWidgetItem(f"{class_id}: {class_name}")
            item.setData(Qt.UserRole, int(class_id))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            classes_list.addItem(item)
            class_combo.addItem(
                f"{class_id}: {class_name}", userData=int(class_id)
            )

        if class_combo.count() > 0:
            for i in range(class_combo.count()):
                if int(class_combo.itemData(i)) != 0:
                    class_combo.setCurrentIndex(i)
                    break

    @staticmethod
    def set_all_segmentation_classes_checked(
        controller, checked: bool
    ) -> None:
        if controller.segmentation is None:
            return

        classes_list = controller.segmentation.segmentation_classes_list
        check_state = Qt.Checked if checked else Qt.Unchecked
        for i in range(classes_list.count()):
            item = classes_list.item(i)
            if item is not None:
                item.setCheckState(check_state)

    @staticmethod
    def on_segmentation_select_all_classes_clicked(controller) -> None:
        SegmentationController.set_all_segmentation_classes_checked(
            controller, checked=True
        )

    @staticmethod
    def on_segmentation_clear_classes_clicked(controller) -> None:
        SegmentationController.set_all_segmentation_classes_checked(
            controller, checked=False
        )

    @staticmethod
    def on_generate_roi_from_mask_clicked(controller) -> None:
        """Generate one rectangular ROI from the selected segmentation class."""
        if controller.segmentation is None:
            return

        if "Segmentation" not in controller.viewer.layers:
            controller.segmentation.segmentation_status_label.setText(
                "No segmentation mask found"
            )
            return

        seg_layer = controller.viewer.layers["Segmentation"]
        seg = np.asarray(seg_layer.data)
        class_names = dict(getattr(seg_layer, "metadata", {}) or {}).get(
            "class_names", {}
        )
        class_id = controller.segmentation.roi_class_id_combo.currentData()
        if class_id is None:
            controller.segmentation.segmentation_status_label.setText(
                "Select a class id"
            )
            return

        class_mask = seg == int(class_id)
        if not np.any(class_mask):
            controller.segmentation.segmentation_status_label.setText(
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

        top_margin_text = controller.segmentation.roi_top_margin_edit.text()
        width_text = controller.segmentation.roi_width_edit.text()
        height_text = controller.segmentation.roi_height_edit.text()

        top_margin_mm = (
            float(top_margin_text) if top_margin_text.strip() else None
        )
        width_mm = float(width_text) if width_text.strip() else None
        height_mm = float(height_text) if height_text.strip() else None

        roi_box, error_text = (
            SegmentationController._compute_roi_box_from_mask(
                class_mask,
                sx=sx,
                sy=sy,
                top_margin_mm=top_margin_mm,
                width_mm=width_mm,
                height_mm=height_mm,
            )
        )
        if roi_box is None:
            controller.segmentation.segmentation_status_label.setText(
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

        controller.shapes_layer.add(verts, shape_type="polygon")
        # from patari.controllers.roi_controller import RoiController
        # RoiController.set_last_roi_position(
        #     controller,
        #     str(class_names.get(int(class_id), int(class_id))),
        # )
        # Colors and live table are refreshed by shapes_layer.data event.
        controller.segmentation.segmentation_status_label.setText(
            f"ROI generated from class {class_names.get(int(class_id), int(class_id))}"
        )

    @staticmethod
    def on_generate_tissue_segmentation_clicked(controller) -> None:
        """Run segmentation on the currently visible US slice and update labels."""
        if controller.segmentation is None:
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
