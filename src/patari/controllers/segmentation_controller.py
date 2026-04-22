from __future__ import annotations

import numpy as np
from napari.layers import Image

from patari.segmentation.napari import (
    ensure_segmentation_labels_layer,
    set_segmentation_2d,
)


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
        if model_id is None:
            return

        controller.set_active_segmentation_model(str(model_id))
        controller.segmentation.segmentation_status_label.setText(
            f"Model: {controller.segmentation.segmentation_model_combo.currentText()}"
        )

    @staticmethod
    def on_generate_tissue_segmentation_clicked(controller) -> None:
        if controller.segmentation is None:
            return

        model_id = (
            controller.segmentation.segmentation_model_combo.currentData()
        )
        if model_id is not None:
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

        try:
            result = controller.get_segmenter().predict(us_2d)
        except Exception as e:
            controller.segmentation.segmentation_status_label.setText(
                f"Segmentation failed: {e}"
            )
            return

        labels = ensure_segmentation_labels_layer(controller.viewer)
        try:
            set_segmentation_2d(
                labels,
                result.seg,
                class_names=result.class_names,
                reference_layer=us_layer,
            )
        except Exception as e:
            controller.segmentation.segmentation_status_label.setText(
                f"Failed to show labels: {e}"
            )
            return
        controller.segmentation.segmentation_status_label.setText(
            "Segmentation layer added."
        )
