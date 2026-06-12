from __future__ import annotations

import logging

import numpy as np
from napari.layers import Image
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QListWidgetItem

from patari.segmentation.segmenter import (
    create_segmenter,
    load_model_registry,
    SegmentationModelConfig,
)
from patari.utils.viewer import current_frame_idx
from napari.layers import Labels
from patari.controllers.base import TaskControllerBase
from patari.roi import Ellipse, Rectangle, Polygon, ROIPlacementConfig


logger = logging.getLogger(__name__)


class SegmentationController(TaskControllerBase):
    """
    Segmentation-related UI actions and geometry helpers.
    Segmentation masks are generated either for a single frame or all frames, depending on the checkbox state in the UI.
    For single frame, the mask will be shown only on the current frame.
    In any case, the mask is padded to the full shape of the US data and repeated across the channel dimension for correct napari display.
    """

    def __init__(self, parent_controller):
        super().__init__(parent_controller)
        self._segmentation_model_registry = load_model_registry()
        self._active_segmentation_model_id = next(
            iter(self._segmentation_model_registry)
        )
        self._segmenter = None
        self._segmenter_model_id = None
        self._seg_layer: Labels | None = None

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
        self._segmenter = None
        self._segmenter_model_id = None
        self._seg_layer = None

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
        """get the segmenter for the active model selection."""
        if (
            self._segmenter is None
            or self._segmenter_model_id != self._active_segmentation_model_id
        ):
            self._segmenter = create_segmenter(
                self._active_segmentation_model_config()
            )
            self._segmenter_model_id = self._active_segmentation_model_id
        return self._segmenter


    def active_seg_mask_2d(self) -> tuple[np.ndarray, "Labels"] | None:
        """Return (H, W) segmentation mask for the current viewer frame, or None."""
        if (
            self._seg_layer is None
            or self._seg_layer not in self.viewer.layers
        ):
            self._seg_layer = None
            return None
        seg_layer = self._seg_layer
        seg = np.asarray(seg_layer.data)
        frame_idx = current_frame_idx(self.viewer, seg.shape[0])
        return seg[frame_idx, 0], seg_layer

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
        default_class = self._active_segmentation_model_config().default_class
        seg_dock.segmentation_classes_list.clear()

        for class_id, class_name in self.active_segmentation_class_items():
            # Add to classes list
            item = QListWidgetItem(f"{class_id}: {class_name}")
            item.setData(Qt.ItemDataRole.UserRole, class_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if default_class == class_name
                else Qt.CheckState.Unchecked
            )

            seg_dock.segmentation_classes_list.addItem(item)


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
        """Generate one ROI from the current frame of the segmentation mask."""
        seg_dock = self.patari_controller.segmentation
        if seg_dock is None:
            return

        result = self.active_seg_mask_2d()
        if result is None:
            seg_dock.segmentation_status_label.setText("No segmentation mask found")
            return
        seg_2d, seg_layer = result

        class_id = seg_dock.roi_class_id_combo.currentData()
        if class_id is None:
            seg_dock.segmentation_status_label.setText("Select a class id")
            return

        sy, sx = float(seg_layer.scale[-2]), float(seg_layer.scale[-1])
        ty, tx = float(seg_layer.translate[-2]), float(seg_layer.translate[-1])

        def parse_roi_param(text: str) -> float | None:
            return float(text) if text.strip() else None

        shape_type = str(seg_dock.roi_shape_combo.currentData() or "ellipse")
        top_margin_mm = parse_roi_param(seg_dock.roi_top_margin_edit.text())
        width_mm = parse_roi_param(seg_dock.roi_width_edit.text())
        height_mm = parse_roi_param(seg_dock.roi_height_edit.text())

        if (width_mm is None or height_mm is None) and shape_type in ("rectangle", "ellipse"):
            seg_dock.segmentation_status_label.setText("Width and height are required")
            return

        config = ROIPlacementConfig(
            width_mm=width_mm,
            height_mm=height_mm,
            depth_mm=top_margin_mm or 0.0,
        )
        if shape_type == "ellipse":
            shape = Ellipse(config)
        elif shape_type == "rectangle":
            shape = Rectangle(config)
        elif shape_type == "polygon":
            shape = Polygon(config)
        else:
            raise ValueError(f"Unknown ROI shape type: {shape_type}")

        frame_idx = current_frame_idx(self.viewer, np.asarray(seg_layer.data).shape[0])
        class_mask = seg_2d == int(class_id)
        if not np.any(class_mask):
            seg_dock.segmentation_status_label.setText(
                "Selected class is not present in the current frame"
            )
            return

        try:
            verts = shape.to_napari_verts_world(
                class_mask=class_mask, sy=sy, sx=sx, ty=ty, tx=tx
            )
        except Exception as exc:
            seg_dock.segmentation_status_label.setText(str(exc))
            return

        self.patari_controller.shapes_layer.add(
            verts, shape_type=shape.shape_type
        )
        seg_dock.segmentation_status_label.setText(
            f"ROI generated from class {class_id} in frame {frame_idx}"
        )

    def on_generate_tissue_segmentation_clicked(self) -> None:
        """Run segmentation on the current frame or all frames and update labels."""
        seg_dock = self.patari_controller.segmentation
        if seg_dock is None:
            return

        us_layer = self.patari_controller.active_us_layer
        if us_layer is None:
            seg_dock.segmentation_status_label.setText("No US layer found")
            return

        selected_ids = self.selected_segmentation_class_ids()
        if not selected_ids:
            seg_dock.segmentation_status_label.setText("No classes selected")
            return

        us_raw = np.asarray(us_layer.data)
        us_data = us_raw[:, 0]
        n_frames, n_channels = us_raw.shape[:2]
        segment_all_frames = seg_dock.segment_all_frames_checkbox.isChecked()

        if segment_all_frames:
            frame_idx = None
            frame_ids = list(range(n_frames))
            frame_mode = "all"
        else:
            frame_idx = current_frame_idx(self.viewer, n_frames)
            us_data = us_data[frame_idx : frame_idx + 1]
            frame_ids = [frame_idx]
            frame_mode = "current"

        segmenter = self.get_segmenter()
        seg_dock.segmentation_status_label.setText(
            f"Segmenting {len(frame_ids)} frame(s) with {self.active_segmentation_model_id}..."
        )

        try:
            results = segmenter.predict(us_data)
            class_names = results[0].class_names

            filtered = [
                np.where(np.isin(r.seg, list(selected_ids)), r.seg, 0).astype(np.int32)
                for r in results
            ]
            mask_3d = np.stack(filtered)
            # Repeat across channel dimension for correct napari display;
            # segmenter output is (nframes, H, W) but napari expects (nframes, n_channels, H, W)
            mask = np.repeat(mask_3d[:, np.newaxis], n_channels, axis=1)
            if frame_idx is not None:
                full_mask = np.zeros(us_raw.shape, dtype=np.int32)
                full_mask[frame_idx] = mask[0]
                mask = full_mask

            if self._seg_layer is not None and self._seg_layer in self.viewer.layers:
                self.viewer.layers.remove(self._seg_layer)
            self._seg_layer = None
            label_layer = self.viewer.add_labels(
                mask,
                name="Segmentation",
                scale=tuple(us_layer.scale),
                translate=tuple(us_layer.translate),
                opacity=0.5,
                metadata={
                    "type": "segmentation",
                    "frame_mode": frame_mode,
                    "frames": frame_ids,
                    "class_names": class_names,
                    "source_model_id": self.active_segmentation_model_id,
                },
            )
            self._seg_layer = label_layer

            # Populate ROI class combo from classes present in the output mask.
            seg_dock.roi_class_id_combo.clear()
            for class_id in sorted(int(c) for c in np.unique(mask)):
                seg_dock.roi_class_id_combo.addItem(
                    f"{class_id}: {class_names.get(class_id, str(class_id))}",
                    userData=class_id,
                )
            # Default to first non-background class if present
            seg_dock.roi_class_id_combo.setCurrentIndex(
                min(1, seg_dock.roi_class_id_combo.count() - 1)
            )

            seg_dock.segmentation_status_label.setText(
                f"Segmentation done ({len(frame_ids)} frame(s))"
            )

        except Exception as e:
            logger.exception("Segmentation failed: %s", e)
            seg_dock.segmentation_status_label.setText("Segmentation failed")