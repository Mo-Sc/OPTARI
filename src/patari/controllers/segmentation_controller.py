from __future__ import annotations

import logging

import numpy as np
from napari.layers import Labels
from napari.utils import progress
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QListWidgetItem

from patari.segmentation.segmenter import (
    create_segmenter,
    load_model_registry,
    SegmentationModelConfig,
)
from patari.segmentation.segmentation_presets import validate_segmentation_settings
from patari.utils.viewer import selected_frame_idx, viewer_busy
from patari.controllers.base import TaskControllerBase
from patari.roi import Ellipse, Rectangle, Polygon, ROIPlacementConfig
from patari.config import settings
from patari.utils.presets import PresetStore
from patari.utils.setup import get_user_segmentation_presets_dir
from patari.widgets.dock_helpers import (
    add_preset_to_combo,
    populate_preset_combo,
    prompt_preset_name,
    remove_selected_preset,
)


logger = logging.getLogger(__name__)


class SegmentationController(TaskControllerBase):
    """
    Segmentation-related UI actions and geometry helpers.
    Segmentation masks are generated either for a single frame or all frames, depending on the checkbox state in the UI.
    For single frame, the mask will be shown only on the selected frame.
    In any case, the mask is padded to the full shape of the US data and repeated across the channel dimension for correct napari display.
    """

    def __init__(self, parent_controller):
        super().__init__(parent_controller)
        self._segmentation_model_registry = load_model_registry()
        default_model_id = settings.segmentation.default_model
        if default_model_id not in self._segmentation_model_registry:
            logger.warning(
                f"Default segmentation model '{default_model_id}' not found in registry. "
                f"Available models: {list(self._segmentation_model_registry.keys())}. "
                f"Falling back to first available model."
            )
            default_model_id = next(iter(self._segmentation_model_registry))
        self._active_segmentation_model_id = default_model_id
        self._segmenter = None
        self._segmenter_model_id = None
        self._seg_layer: Labels | None = None
        self._pending_roi_class_id: int | None = None
        self.preset_store = PresetStore(get_user_segmentation_presets_dir())

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
        self.patari_controller.segmentation.preset_combo.currentIndexChanged.connect(
            self.on_preset_changed
        )
        self.patari_controller.segmentation.save_preset_button.clicked.connect(
            self.on_save_preset_clicked
        )
        self.patari_controller.segmentation.remove_preset_button.clicked.connect(
            self.on_remove_preset_clicked
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
        self.patari_controller.segmentation.preset_combo.currentIndexChanged.disconnect(
            self.on_preset_changed
        )
        self.patari_controller.segmentation.save_preset_button.clicked.disconnect(
            self.on_save_preset_clicked
        )
        self.patari_controller.segmentation.remove_preset_button.clicked.disconnect(
            self.on_remove_preset_clicked
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

        self.on_segmentation_model_changed()

        populate_preset_combo(dock.preset_combo, self.preset_store)

        if dock.preset_combo.count() > 0:
            self.on_preset_changed()

        self.refresh_ui()

    def teardown(self) -> None:
        """Release cached segmentation model to free memory."""
        self._segmenter = None
        self._segmenter_model_id = None
        self._seg_layer = None

    def refresh_ui(self) -> None:
        """Refresh controls that require scan or segmentation output."""
        dock = self.patari_controller.segmentation
        if dock is None:
            return

        has_us_layer = (
            self.patari_controller.pa_data is not None
            and self.patari_controller.active_us_layer is not None
        )
        dock.generate_tissue_segmentation_button.setEnabled(has_us_layer)
        dock.generate_roi_button.setEnabled(self.active_seg_mask_2d() is not None)

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
        frame_idx = selected_frame_idx(self.viewer, seg.shape[0])
        return seg[frame_idx, 0], seg_layer

    def on_segmentation_model_changed(self) -> None:
        if self.patari_controller.segmentation is None:
            return

        dock = self.patari_controller.segmentation
        model_id = dock.segmentation_model_combo.currentData()
        if model_id is None:
            return
        self.set_active_segmentation_model(str(model_id))
        self.populate_segmentation_controls()
        dock.roi_class_id_combo.clear()
        self._pending_roi_class_id = None
        dock.segmentation_status_label.setText(
            f"Model: {dock.segmentation_model_combo.currentText()}"
        )

    def populate_segmentation_controls(
        self, selected_class_ids: set[int] | None = None
    ) -> None:
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
                if (
                    class_id in selected_class_ids
                    if selected_class_ids is not None
                    else default_class == class_name
                )
                else Qt.CheckState.Unchecked
            )

            seg_dock.segmentation_classes_list.addItem(item)

    def on_preset_changed(self) -> None:
        """Load and apply the selected segmentation preset."""
        dock = self.patari_controller.segmentation
        preset_path = dock.preset_combo.currentData()
        if preset_path is None:
            return

        try:
            settings = self.preset_store.load(preset_path)
            settings = validate_segmentation_settings(settings)
            model_config = self._segmentation_model_registry.get(
                settings["model_id"]
            )
            if model_config is None:
                raise ValueError(
                    f"Unknown segmentation model: {settings['model_id']}"
                )
            settings = validate_segmentation_settings(settings, model_config.class_names)
            self._apply_preset(settings)
        except (ValueError, OSError) as exc:
            dock.segmentation_status_label.setText(
                f"Could not apply preset: {exc}"
            )

    def _apply_preset(self, settings: dict) -> None:
        dock = self.patari_controller.segmentation
        model_index = dock.segmentation_model_combo.findData(settings["model_id"])
        if model_index < 0:
            raise ValueError(f"Unknown segmentation model: {settings['model_id']}")
        shape_index = dock.roi_shape_combo.findData(settings["roi_shape"])
        if shape_index < 0:
            raise ValueError(f"Unsupported ROI shape: {settings['roi_shape']}")

        dock.segmentation_model_combo.blockSignals(True)
        try:
            dock.segmentation_model_combo.setCurrentIndex(model_index)
        finally:
            dock.segmentation_model_combo.blockSignals(False)

        self.set_active_segmentation_model(settings["model_id"])
        self.populate_segmentation_controls(set(settings["selected_class_ids"]))
        dock.roi_class_id_combo.clear()
        # Inference repopulates this combo; keep a preset's class until then.
        self._pending_roi_class_id = settings["roi_class_id"]

        dock.roi_shape_combo.setCurrentIndex(shape_index)
        dock.roi_width_edit.setText(self._format_roi_value(settings["roi_width_mm"]))
        dock.roi_height_edit.setText(self._format_roi_value(settings["roi_height_mm"]))
        dock.roi_top_margin_edit.setText(
            self._format_roi_value(settings["roi_top_margin_mm"])
        )
        dock.segmentation_status_label.setText("Preset applied.")

    @staticmethod
    def _format_roi_value(value: float | None) -> str:
        return "" if value is None else f"{value:g}"

    @staticmethod
    def _parse_roi_value(text: str, label: str) -> float | None:
        if not text.strip():
            return None
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be a number.") from exc

    def on_save_preset_clicked(self) -> None:
        dock = self.patari_controller.segmentation
        selected_class_ids = sorted(self.selected_segmentation_class_ids())
        if not selected_class_ids:
            dock.segmentation_status_label.setText("Select at least one class.")
            return

        try:
            preset_values = {
                "model_id": self.active_segmentation_model_id,
                "selected_class_ids": selected_class_ids,
                "roi_class_id": dock.roi_class_id_combo.currentData(),
                "roi_shape": dock.roi_shape_combo.currentData() or "ellipse",
                "roi_width_mm": self._parse_roi_value(
                    dock.roi_width_edit.text(), "ROI width"
                ),
                "roi_height_mm": self._parse_roi_value(
                    dock.roi_height_edit.text(), "ROI height"
                ),
                "roi_top_margin_mm": self._parse_roi_value(
                    dock.roi_top_margin_edit.text(), "ROI top margin"
                ),
            }
            preset_name = prompt_preset_name(
                dock.widget, dock.preset_combo, "segmentation_preset"
            )
            if preset_name is None:
                return
            preset_values = validate_segmentation_settings(
                preset_values,
                self._segmentation_model_registry[
                    self.active_segmentation_model_id
                ].class_names,
            )
            preset_path = self.preset_store.save(preset_name, preset_values)
        except (KeyError, ValueError, OSError) as exc:
            dock.segmentation_status_label.setText(
                f"Could not save preset: {exc}"
            )
            return

        add_preset_to_combo(dock.preset_combo, preset_path)
        dock.segmentation_status_label.setText(f"Saved preset: {preset_path.name}")

    def on_remove_preset_clicked(self) -> None:
        dock = self.patari_controller.segmentation
        preset_path = dock.preset_combo.currentData()
        if preset_path is None:
            dock.segmentation_status_label.setText("Select a preset to remove.")
            return

        try:
            removed_path, removed = remove_selected_preset(
                dock.preset_combo, self.preset_store
            )
        except (ValueError, OSError) as exc:
            dock.segmentation_status_label.setText(
                f"Could not remove preset: {exc}"
            )
            return
        if not removed:
            dock.segmentation_status_label.setText(
                f"Preset not found: {preset_path.name}"
            )
            return

        dock.segmentation_status_label.setText(
            f"Removed preset: {removed_path.name}"
        )


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
        """Generate one ROI from the selected frame of the segmentation mask."""
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

        frame_idx = selected_frame_idx(self.viewer, np.asarray(seg_layer.data).shape[0])
        class_mask = seg_2d == int(class_id)
        if not np.any(class_mask):
            seg_dock.segmentation_status_label.setText(
                "Selected class is not present in the selected frame"
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
        # auto-select the newly added shape, also activates the save button
        new_idx = len(self.patari_controller.shapes_layer.data) - 1
        self.patari_controller.shapes_layer.selected_data = {new_idx}
        seg_dock.segmentation_status_label.setText(
            f"ROI generated from class {class_id} in frame {frame_idx}"
        )

    def on_generate_tissue_segmentation_clicked(self) -> None:
        """Run segmentation on the selected frame or all frames and update labels."""
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
        segment_all_frames = seg_dock.all_frames_radio.isChecked()

        if segment_all_frames:
            frame_idx = None
            frame_ids = list(range(n_frames))
            frame_mode = "all"
        else:
            frame_idx = selected_frame_idx(self.viewer, n_frames)
            us_data = us_data[frame_idx : frame_idx + 1]
            frame_ids = [frame_idx]
            frame_mode = "current"

        segmenter = self.get_segmenter()
        seg_dock.segmentation_status_label.setText(
            f"Segmenting {len(frame_ids)} frame(s) with {self.active_segmentation_model_id}..."
        )

        try:
            with viewer_busy(self.viewer):
                with progress(total=len(frame_ids), desc="Segmenting") as progress_bar:
                    results = segmenter.predict(
                        us_data, on_frame_complete=progress_bar.update
                    )

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
                    "settings": {
                        "model_id": self.active_segmentation_model_id,
                        "selected_class_ids": sorted(selected_ids),
                        "class_names": class_names,
                        "frame_mode": frame_mode,
                        "frames": frame_ids,
                    },
                },
                units=self.image_units,
            )
            self._seg_layer = label_layer

            # Populate ROI class combo from classes present in the output mask.
            seg_dock.roi_class_id_combo.clear()
            for class_id in sorted(int(c) for c in np.unique(mask)):
                seg_dock.roi_class_id_combo.addItem(
                    f"{class_id}: {class_names.get(class_id, str(class_id))}",
                    userData=class_id,
                )
            roi_class_index = seg_dock.roi_class_id_combo.findData(
                self._pending_roi_class_id
            )
            if roi_class_index < 0:
                roi_class_index = min(1, seg_dock.roi_class_id_combo.count() - 1)
            seg_dock.roi_class_id_combo.setCurrentIndex(roi_class_index)
            self._pending_roi_class_id = None

            seg_dock.segmentation_status_label.setText(
                f"Segmentation done ({len(frame_ids)} frame(s))"
            )
            self.refresh_ui()

        except Exception as e:
            logger.exception("Segmentation failed: %s", e)
            seg_dock.segmentation_status_label.setText("Segmentation failed")