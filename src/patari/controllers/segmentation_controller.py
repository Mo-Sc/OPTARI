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
    """Segmentation generation helpers."""

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
        SegmentationController.populate_segmentation_classes(controller)
        controller.segmentation.segmentation_status_label.setText(
            f"Model: {controller.segmentation.segmentation_model_combo.currentText()}"
        )

    @staticmethod
    def populate_segmentation_classes(controller) -> None:
        if controller.segmentation is None:
            return

        classes_list = controller.segmentation.segmentation_classes_list
        classes_list.clear()
        for (
            class_id,
            class_name,
        ) in controller.active_segmentation_class_items():
            item = QListWidgetItem(f"{class_id}: {class_name}")
            item.setData(Qt.UserRole, int(class_id))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            classes_list.addItem(item)

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
    def on_generate_tissue_segmentation_clicked(controller) -> None:
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
