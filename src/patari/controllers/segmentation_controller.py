from __future__ import annotations

import numpy as np
from napari.layers import Image, Labels

from patari.config import ROI_PLACEMENT_PRESETS
from patari.roi.roi_shapes import EllipseConfig, ShapeFactory
from patari.segmentation.napari import (
    ensure_segmentation_labels_layer,
    set_segmentation_2d,
)
from patari.utils.misc import parse_float_input


class SegmentationController:
    """Segmentation generation and auto-ROI placement helpers."""

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

        # Use current frame index when US has a frame axis.
        try:
            pt = list(controller.viewer.dims.point)
            frame_idx = int(round(pt[0])) if len(pt) >= 1 else 0
        except Exception:
            frame_idx = 0

        frame_idx = int(np.clip(frame_idx, 0, max(0, data.shape[0] - 1)))

        if data.ndim == 3:
            return data[frame_idx]
        if data.ndim >= 4:
            # e.g. (frame, channel, y, x)
            return data[frame_idx, 0]

        return None

    @staticmethod
    def set_roi_class_choices(controller, class_names: dict[int, str]) -> None:
        if controller.annotation is None:
            return

        combo = controller.annotation.roi_class_combo
        combo.blockSignals(True)
        try:
            combo.clear()
            for class_id, name in sorted(
                class_names.items(), key=lambda kv: int(kv[0])
            ):
                combo.addItem(str(name), userData=int(class_id))
            combo.setEnabled(combo.count() > 0)
        finally:
            combo.blockSignals(False)

    @staticmethod
    def select_roi_class_by_name(controller, class_name: str) -> None:
        if controller.annotation is None:
            return

        combo = controller.annotation.roi_class_combo
        target = (class_name or "").strip()
        if not target:
            return

        for i in range(combo.count()):
            txt = (combo.itemText(i) or "").strip()
            if txt == target:
                combo.setCurrentIndex(i)
                return

    @staticmethod
    def on_roi_preset_clicked(controller, button) -> None:
        if controller.annotation is None:
            return

        try:
            preset_index = int(button.property("roi_preset_index"))
        except Exception:
            return

        if not (0 <= preset_index < len(ROI_PLACEMENT_PRESETS)):
            return

        preset = ROI_PLACEMENT_PRESETS[preset_index]
        roi_type = str(preset.get("roi_type", "ellipse"))

        # ROI type dropdown (currently only ellipse).
        for i in range(controller.annotation.roi_type_combo.count()):
            if controller.annotation.roi_type_combo.itemData(i) == roi_type:
                controller.annotation.roi_type_combo.setCurrentIndex(i)
                break

        # Numeric fields
        controller.annotation.roi_width_edit.setText(
            str(preset.get("width_mm", ""))
        )
        controller.annotation.roi_height_edit.setText(
            str(preset.get("height_mm", ""))
        )
        controller.annotation.roi_depth_edit.setText(
            str(preset.get("depth_mm", ""))
        )

        seg_class = str(preset.get("segmentation_class", "")).strip()
        if not seg_class:
            return

        if (
            controller.annotation.roi_class_combo.isEnabled()
            and controller.annotation.roi_class_combo.count() > 0
        ):
            SegmentationController.select_roi_class_by_name(
                controller, seg_class
            )

    @staticmethod
    def on_generate_tissue_segmentation_clicked(controller) -> None:
        if controller.annotation is None:
            return

        us_layer = SegmentationController.resolve_us_layer(controller)
        if us_layer is None:
            controller.annotation.segmentation_status_label.setText(
                "No US layer found"
            )
            return

        us_2d = SegmentationController.us_slice_2d(controller, us_layer)
        if us_2d is None:
            controller.annotation.segmentation_status_label.setText(
                "US layer has unsupported shape"
            )
            return

        controller.annotation.segmentation_status_label.setText(
            "Running segmentation…"
        )

        try:
            result = controller._segmenter.predict(us_2d)
        except Exception as e:
            controller.annotation.segmentation_status_label.setText(
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
            controller.annotation.segmentation_status_label.setText(
                f"Failed to show labels: {e}"
            )
            return

        SegmentationController.set_roi_class_choices(
            controller, result.class_names
        )
        controller.annotation.roi_status_label.setText(
            "Segmentation generated. Choose class and place ROI."
        )
        controller.annotation.segmentation_status_label.setText(
            "Segmentation layer added."
        )

    @staticmethod
    def on_place_roi_clicked(controller) -> None:
        if controller.annotation is None:
            return
        if controller.shapes_layer is None:
            controller.annotation.roi_status_label.setText("No ROIs layer")
            return

        # Must have segmentation layer first.
        seg_layer = (
            controller.viewer.layers["Segmentation"]
            if "Segmentation" in controller.viewer.layers
            else None
        )

        if seg_layer is None or not isinstance(seg_layer, Labels):
            controller.annotation.roi_status_label.setText(
                "Generate tissue segmentation first"
            )
            return

        seg = np.asarray(seg_layer.data)

        if seg.ndim != 2:
            controller.annotation.roi_status_label.setText(
                "Segmentation layer must be 2D"
            )
            return

        class_id = controller.annotation.roi_class_combo.currentData()
        if class_id is None:
            controller.annotation.roi_status_label.setText("Select a class")
            return

        roi_type = (
            controller.annotation.roi_type_combo.currentData() or "ellipse"
        )

        width_mm = parse_float_input(
            controller.annotation.roi_width_edit.text()
        )
        height_mm = parse_float_input(
            controller.annotation.roi_height_edit.text()
        )
        depth_mm = parse_float_input(
            controller.annotation.roi_depth_edit.text()
        )

        if width_mm is None or height_mm is None:
            controller.annotation.roi_status_label.setText(
                "Enter ROI width and height (mm)"
            )
            return
        if depth_mm is None:
            depth_mm = 0.0

        # Placement is done in world coordinates (mm), so we need US scale/translate
        # to convert from segmentation pixels to napari-world ROI vertices.
        us_layer = SegmentationController.resolve_us_layer(controller)
        if us_layer is None:
            controller.annotation.roi_status_label.setText("No US layer found")
            return

        ref_scale = getattr(us_layer, "scale", (1.0, 1.0))
        sy, sx = float(ref_scale[-2]), float(ref_scale[-1])

        ref_translate = getattr(us_layer, "translate", (0.0, 0.0))
        ty, tx = float(ref_translate[-2]), float(ref_translate[-1])

        class_mask = seg == int(class_id)
        config = EllipseConfig(
            width_mm=float(width_mm),
            height_mm=float(height_mm),
            depth_mm=float(depth_mm),
        )

        try:
            placer = ShapeFactory.create_shape(str(roi_type), config)
            verts_world = placer.to_napari_verts_world(
                class_mask=class_mask,
                sy=sy,
                sx=sx,
                ty=ty,
                tx=tx,
            )
        except Exception as e:
            controller.annotation.roi_status_label.setText(
                f"ROI placement failed: {e}"
            )
            return

        try:
            controller.shapes_layer.add(
                verts_world, shape_type=str(roi_type)
            )
        except Exception as e:
            controller.annotation.roi_status_label.setText(
                f"Failed to add ROI to viewer: {e}"
            )
            return

        controller._apply_roi_colors()
        controller.update_live_table()
        controller.annotation.roi_status_label.setText("ROI placed.")
