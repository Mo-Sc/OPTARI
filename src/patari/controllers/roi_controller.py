from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
)

from patari.config import MAX_ROIS, ROI_LABELS, dtype_map
from patari.io.export_pipeline import export_roi_table_to_xlsx
from patari.roi.roi_library import RoiLibrary
from patari.roi.roi_utils import compute_roi_stats
from patari.utils.misc import roi_color_for_index
from patari.controllers.base import TaskControllerBase


logger = logging.getLogger(__name__)


def _roi_library_file() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "roi_library.json"


def _roi_name_popup() -> tuple[str, str, str] | None:
    dialog = QDialog()
    dialog.setWindowTitle("Save ROI")

    form = QFormLayout(dialog)
    roi_id_edit = QLineEdit()
    description_edit = QLineEdit()
    position_edit = QLineEdit()
    position_edit.setPlaceholderText("undefined")
    form.addRow("ROI Name:", roi_id_edit)
    form.addRow("Description (optional):", description_edit)
    form.addRow("Position (optional):", position_edit)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)

    if dialog.exec() != QDialog.Accepted:
        return None

    roi_id = (roi_id_edit.text() or "").strip()
    if not roi_id:
        return None

    description = (description_edit.text() or "").strip()
    position = (position_edit.text() or "").strip() or "undefined"
    return roi_id, description, position


class RoiController(TaskControllerBase):
    """ROI visualization, table management, and ROI export helpers."""

    def __init__(self, parent_controller):
        super().__init__(parent_controller)

    def bind_events(self) -> None:
        """Connect ROI and annotation dock signals."""
        # ROI table buttons
        self.patari_controller.roi.save_button.clicked.connect(
            self.on_save_clicked
        )
        self.patari_controller.roi.delete_button.clicked.connect(
            self.on_delete_saved_clicked
        )
        self.patari_controller.roi.xlsx_button.clicked.connect(
            self.on_xlsx_export_clicked
        )

        # Annotation dock: ROI intensity settings
        ann = self.patari_controller.annotation
        for edit in (
            ann.roi_clip_min_edit,
            ann.roi_clip_max_edit,
            ann.roi_exclude_min_edit,
            ann.roi_exclude_max_edit,
        ):
            edit.editingFinished.connect(
                self.patari_controller._on_roi_intensity_settings_changed
            )
            edit.textChanged.connect(
                lambda t, _e=edit: (
                    self.patari_controller._on_roi_intensity_settings_changed()
                    if (t or "").strip() == ""
                    else None
                )
            )

        ann.roi_clipping_box.toggled.connect(
            lambda checked: self.patari_controller._on_roi_intensity_settings_changed()
        )
        ann.roi_exclusion_box.toggled.connect(
            lambda checked: self.patari_controller._on_roi_intensity_settings_changed()
        )

        # ROI library
        ann.roi_library_list.itemClicked.connect(
            lambda item: self.on_roi_library_item_selected(item.text())
        )
        ann.roi_library_list.itemDoubleClicked.connect(
            lambda item: self.on_roi_library_item_clicked(item.text())
        )
        ann.save_roi_button.clicked.connect(self.on_save_roi_library_clicked)
        ann.remove_roi_button.clicked.connect(
            self.on_remove_roi_library_clicked
        )
        ann.save_library_button.clicked.connect(
            self.on_save_roi_library_file_clicked
        )

    def unbind_events(self) -> None:
        """Disconnect ROI and annotation dock signals."""
        try:
            self.patari_controller.roi.save_button.clicked.disconnect(
                self.on_save_clicked
            )
            self.patari_controller.roi.delete_button.clicked.disconnect(
                self.on_delete_saved_clicked
            )
            self.patari_controller.roi.xlsx_button.clicked.disconnect(
                self.on_xlsx_export_clicked
            )

            ann = self.patari_controller.annotation
            for edit in (
                ann.roi_clip_min_edit,
                ann.roi_clip_max_edit,
                ann.roi_exclude_min_edit,
                ann.roi_exclude_max_edit,
            ):
                edit.editingFinished.disconnect(
                    self.patari_controller._on_roi_intensity_settings_changed
                )

            ann.roi_library_list.itemClicked.disconnect(
                lambda item: self.on_roi_library_item_selected(item.text())
            )
            ann.roi_library_list.itemDoubleClicked.disconnect(
                lambda item: self.on_roi_library_item_clicked(item.text())
            )
            ann.save_roi_button.clicked.disconnect(
                self.on_save_roi_library_clicked
            )
            ann.remove_roi_button.clicked.disconnect(
                self.on_remove_roi_library_clicked
            )
            ann.save_library_button.clicked.disconnect(
                self.on_save_roi_library_file_clicked
            )
        except Exception as e:
            logger.exception(
                "Error unbinding ROI and annotation dock signals: %s", e
            )

    # @staticmethod
    # def set_last_roi_position(controller, position: str) -> None:
    #     """Tag the most recently added ROI with a semantic position string."""
    # Disabled for now: roi_position metadata is currently not exported anyways by
    # export/stats
    # props = dict(getattr(controller.shapes_layer, "properties", {}) or {})
    # positions = list(props.get("roi_position", []))
    # if not positions:
    #     return
    # positions[-1] = str(position or "undefined")
    # props["roi_position"] = positions
    # controller.shapes_layer.properties = props
    # return

    def apply_roi_colors(self) -> None:
        """Assign deterministic colors to ROI edges by ROI index."""
        if self.patari_controller.shapes_layer is None:
            return

        self.patari_controller.shapes_layer.edge_color = [
            roi_color_for_index(i)
            for i in range(len(self.patari_controller.shapes_layer.data))
        ]

    def apply_roi_labels(self) -> None:
        """Show ROI index labels next to shapes (when enabled)."""
        if self.patari_controller.shapes_layer is None:
            return

        try:
            props = dict(
                getattr(self.patari_controller.shapes_layer, "properties", {})
                or {}
            )
            props["roi_id"] = np.arange(
                len(self.patari_controller.shapes_layer.data), dtype=int
            )
            self.patari_controller.shapes_layer.properties = props
            # napari text supports formatting from properties.
            self.patari_controller.shapes_layer.text = {
                "string": "{roi_id}",
                "size": 8,
            }
        except Exception:
            logger.exception("failed to apply ROI labels")

    def on_shapes_data_changed(self, event=None) -> None:
        if self.patari_controller.shapes_layer is None:
            return

        n_shapes = len(self.patari_controller.shapes_layer.data)

        # ROI limit. For now just warning, TODO: enforce
        if n_shapes > MAX_ROIS:
            logger.warning(
                "ROI soft limit reached (%s ROIs); Too many ROIs may cause performance issues. Current number of ROIs: %s",
                MAX_ROIS,
                n_shapes,
            )

        # TODO: roi_position attribute
        # for roi specific metadata, we have to add/update properties on the shapes layer, that would be done here
        # props = dict(getattr(controller.shapes_layer, "properties", {}) or {})
        # positions = list(props.get("roi_position", []))
        # print(positions)

        self.apply_roi_colors()
        if ROI_LABELS:
            self.apply_roi_labels()

        self.update_live_table()

    def update_live_table(self, event=None) -> None:
        if (
            self.patari_controller.roi is None
            or self.patari_controller.shapes_layer is None
        ):
            return

        if self.patari_controller.active_recon_layer is None:
            self.patari_controller.roi.live_table.value = pd.DataFrame(
                columns=list(dtype_map.keys())
            ).astype(dtype_map)
            return

        pt = list(self.viewer.dims.point)
        if len(pt) < 2:
            return

        frame_idx = int(round(pt[0]))
        channel_idx = int(round(pt[1]))

        try:
            df = compute_roi_stats(
                self.patari_controller.shapes_layer,
                self.patari_controller.active_recon_layer,
                frame_idx,
                channel_idx,
                clamp_min=self.patari_controller.roi_intensity_min,
                clamp_max=self.patari_controller.roi_intensity_max,
                clamp_mode=(
                    self.patari_controller.roi_intensity_mode or "clip"
                ),
            )
        except Exception:
            logger.exception("update_live_table failed")
            df = pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)

        self.patari_controller.roi.live_table.value = df

        # Keep ROI colors in sync with current shape count/order.
        self.apply_roi_colors()

        # Color first table column to match each ROI color.
        num_shapes = len(self.patari_controller.shapes_layer.data)
        for row_idx in range(num_shapes):
            item = self.patari_controller.roi.live_table.native.item(
                row_idx, 0
            )
            if item is not None:
                item.setBackground(QColor(roi_color_for_index(row_idx)))

    @staticmethod
    def table_value_to_df(table: object) -> pd.DataFrame:
        # magicgui Table.value is sometimes a DataFrame and sometimes dict-like
        val = getattr(table, "value", table)
        if isinstance(val, pd.DataFrame):
            return val
        if isinstance(val, dict) and "data" in val and "columns" in val:
            return pd.DataFrame(val["data"], columns=val["columns"])
        return pd.DataFrame()

    def on_save_clicked(self, event=None) -> None:
        if (
            self.patari_controller.roi is None
            or self.patari_controller.shapes_layer is None
        ):
            return

        selected = self.patari_controller.shapes_layer.selected_data
        if len(selected) != 1:
            logger.info("Select one ROI to save")
            return

        roi_idx = list(selected)[0]
        df_live = self.table_value_to_df(self.patari_controller.roi.live_table)
        if df_live.empty or roi_idx >= len(df_live):
            logger.info("Nothing to save")
            return

        include_all_frames = False
        include_all_wavelengths = False
        if self.patari_controller.annotation is not None:
            cb_frames = getattr(
                self.patari_controller.annotation,
                "include_all_frames_checkbox",
                None,
            )
            cb_wavs = getattr(
                self.patari_controller.annotation,
                "include_all_wavelengths_checkbox",
                None,
            )
            include_all_frames = (
                bool(cb_frames.isChecked()) if cb_frames is not None else False
            )
            include_all_wavelengths = (
                bool(cb_wavs.isChecked()) if cb_wavs is not None else False
            )

        if not include_all_frames and not include_all_wavelengths:
            rows_to_add = df_live.iloc[[roi_idx]].astype(dtype_map)
        else:
            if self.patari_controller.active_recon_layer is None:
                logger.info("Select an image layer to save ROI stats")
                return

            pt = list(self.viewer.dims.point)
            if len(pt) < 2:
                return
            frame_idx = int(round(pt[0]))
            channel_idx = int(round(pt[1]))

            data = np.asarray(self.patari_controller.active_recon_layer.data)
            if data.ndim < 2:
                logger.info("Active layer has no frame/channel dimensions")
                return

            if include_all_frames:
                frames_meta = getattr(
                    self.patari_controller.active_recon_layer, "metadata", {}
                ).get("frames")
                frame_indices = [int(f) for f in frames_meta]
            else:
                frame_indices = [frame_idx]

            if include_all_wavelengths:
                channel_indices = list(range(data.shape[1]))
            else:
                channel_indices = [channel_idx]

            # Potentially expensive path: compute one row per (frame, channel)
            # for the selected ROI only, preserving the current ROI filtering rules.
            collected: list[pd.DataFrame] = []
            for f_idx in frame_indices:
                for c_idx in channel_indices:
                    df_slice = compute_roi_stats(
                        self.patari_controller.shapes_layer,
                        self.patari_controller.active_recon_layer,
                        int(f_idx),
                        int(c_idx),
                        clamp_min=self.patari_controller.roi_intensity_min,
                        clamp_max=self.patari_controller.roi_intensity_max,
                        clamp_mode=(
                            self.patari_controller.roi_intensity_mode or "clip"
                        ),
                    )

                    roi_index_numeric = pd.to_numeric(
                        df_slice["roi_index"], errors="coerce"
                    )
                    df_row = df_slice[roi_index_numeric == int(roi_idx)]
                    collected.append(df_row.iloc[[0]].astype(dtype_map))

            if not collected:
                logger.info("Nothing to save")
                return

            rows_to_add = pd.concat(collected, ignore_index=True).astype(
                dtype_map
            )

        df_saved = self.table_value_to_df(
            self.patari_controller.roi.saved_table
        )
        if df_saved.empty:
            df_saved = rows_to_add.copy()
        else:
            df_saved = pd.concat([df_saved, rows_to_add], ignore_index=True)

        self.patari_controller.roi.saved_table.value = df_saved.astype(
            dtype_map
        )
        logger.info("Saved ROI %s (%s row(s))", roi_idx, len(rows_to_add))

    def on_delete_saved_clicked(self, event=None) -> None:
        if self.patari_controller.roi is None:
            return

        selection_model = (
            self.patari_controller.roi.saved_table.native.selectionModel()
        )
        selected_rows = selection_model.selectedRows()
        selected_indices = [idx.row() for idx in selected_rows]
        if not selected_indices:
            logger.info("No row selected to delete.")
            return

        df_saved = self.table_value_to_df(
            self.patari_controller.roi.saved_table
        )
        if df_saved.empty:
            return

        df_saved = df_saved.drop(selected_indices).reset_index(drop=True)
        self.patari_controller.roi.saved_table.value = df_saved.astype(
            dtype_map
        )
        logger.info("Deleted %s saved rows", len(selected_indices))

    def on_xlsx_export_clicked(self, event=None) -> None:
        if self.patari_controller.roi is None:
            return

        df_saved = self.table_value_to_df(
            self.patari_controller.roi.saved_table
        )
        if df_saved.empty:
            logger.info("Saved table empty")
            return

        filename = export_roi_table_to_xlsx(df_saved)
        if filename is None:
            return

        logger.info("Saved ROI table to %s", filename)

    def _ensure_roi_library_loaded(self) -> RoiLibrary:
        library = getattr(self.patari_controller, "_roi_library", None)
        if library is None:
            library = RoiLibrary(_roi_library_file())
            library.load()
            self.patari_controller._roi_library = library
        return library

    def _refresh_roi_library_ui(self) -> None:
        if self.patari_controller.annotation is None:
            return
        library = self._ensure_roi_library_loaded()
        ids = library.list_ids()
        self.patari_controller.annotation.set_roi_ids(ids)
        self.patari_controller.annotation.roi_library_description_label.setText(
            ""
        )

    def on_save_roi_library_clicked(self, event=None) -> None:
        if self.patari_controller.shapes_layer is None:
            return

        selected = list(self.patari_controller.shapes_layer.selected_data)
        if len(selected) == 0:
            logger.info("Save ROI clicked with no selected ROI")
            if self.patari_controller.annotation is not None:
                self.patari_controller.annotation.roi_library_description_label.setText(
                    "No ROI selected in viewer."
                )
            return

        roi_idx = int(selected[0])
        verts = np.asarray(
            self.patari_controller.shapes_layer.data[roi_idx], dtype=float
        )
        shape_type = str(
            self.patari_controller.shapes_layer.shape_type[roi_idx]
        )

        metadata = _roi_name_popup()
        if metadata is None:
            return
        roi_id, description, position = metadata

        source_fov_x_mm = None
        source_fov_y_mm = None
        fov_m = self.patari_controller._get_fov()
        if fov_m is not None:
            source_fov_x_mm = float(fov_m[0]) * 1000.0
            source_fov_y_mm = float(fov_m[1]) * 1000.0

        library = self._ensure_roi_library_loaded()
        library.add_or_update(
            roi_id=roi_id,
            description=str(description or ""),
            position=str(position or "undefined"),
            shape_type=shape_type,
            vertices=[[float(v[0]), float(v[1])] for v in verts[:, -2:]],
            source_fov_x_mm=source_fov_x_mm,
            source_fov_y_mm=source_fov_y_mm,
        )

        self._refresh_roi_library_ui()
        logger.info("Saved ROI '%s' into ROI Library (in-memory)", roi_id)

    def on_remove_roi_library_clicked(self, event=None) -> None:
        if self.patari_controller.annotation is None:
            return
        item = self.patari_controller.annotation.roi_library_list.currentItem()
        if item is None:
            return
        roi_id = item.text()
        if not roi_id:
            return

        library = self._ensure_roi_library_loaded()
        removed = library.remove(roi_id)
        if removed:
            self._refresh_roi_library_ui()
            logger.info(
                "Removed ROI '%s' from ROI Library (in-memory)", roi_id
            )

    def on_save_roi_library_file_clicked(self, event=None) -> None:
        library = self._ensure_roi_library_loaded()
        library.save()
        logger.info("Saved ROI Library to %s", _roi_library_file())

    def _roi_library_placement_mode(self) -> str:
        if self.patari_controller.annotation is None:
            return "static"

        return str(
            self.patari_controller.annotation.roi_placement_mode_combo.currentData()
        )

    @staticmethod
    def _place_library_entry_static(controller, entry) -> None:
        """Place a saved ROI entry at its stored coordinates."""
        verts = np.asarray(entry.vertices, dtype=float)[:, -2:]
        controller.shapes_layer.add(verts, shape_type=entry.shape_type)
        # Keep roi_position metadata aligned with the newly added shape index.
        # RoiController.set_last_roi_position(controller, entry.position)
        # Colors and live table are refreshed by shapes_layer.data event.

    @staticmethod
    def _place_library_entry_auto(controller, entry) -> None:
        """Place a saved ROI by aligning it to the selected segmentation class."""
        result = controller.segmentation_ctrl.active_seg_mask_2d()
        if result is None:
            QMessageBox.critical(
                None, "Auto ROI",
                "No segmentation mask found. Generate segmentation first.",
            )
            return

        seg, seg_layer = result
        class_names = (seg_layer.metadata or {}).get("class_names", {})
        class_name_to_id = {
            str(name): int(class_id) for class_id, name in class_names.items()
        }

        target_class_name = str(entry.position or "").strip()
        if target_class_name not in class_name_to_id:
            QMessageBox.critical(
                None, "Auto ROI",
                f"ROI position '{target_class_name}' not found in segmentation classes.",
            )
            return

        class_id = class_name_to_id[target_class_name]
        class_mask = seg == int(class_id)
        if not np.any(class_mask):
            QMessageBox.critical(
                None, "Auto ROI",
                f"Class '{target_class_name}' is not present in the current frame.",
            )
            return

        verts = np.asarray(entry.vertices, dtype=float)[:, -2:]
        y_min = float(np.min(verts[:, 0]))
        x_min = float(np.min(verts[:, 1]))
        x_max = float(np.max(verts[:, 1]))
        source_center_x = 0.5 * (x_min + x_max)

        # seg is (H, W) — shape[1] is now reliably image width
        center_col = int(seg.shape[1] // 2)
        center_rows = np.where(class_mask[:, center_col])[0]
        if center_rows.size == 0:
            QMessageBox.critical(
                None, "Auto ROI",
                f"Class '{target_class_name}' is not present at image center.",
            )
            return
        top_row = int(center_rows[0])

        sy = float(seg_layer.scale[-2])
        sx = float(seg_layer.scale[-1])
        ty = float(seg_layer.translate[-2])
        tx = float(seg_layer.translate[-1])

        dy = ty + float(top_row) * sy - y_min
        dx = tx + float(center_col) * sx - source_center_x
        verts_shifted = verts + np.asarray([dy, dx], dtype=float)

        controller.shapes_layer.add(verts_shifted, shape_type=entry.shape_type)

    def on_roi_library_item_clicked(self, roi_id: str) -> None:
        if self.patari_controller.shapes_layer is None:
            return
        library = self._ensure_roi_library_loaded()
        entry = library.get_by_id(roi_id)
        if entry is None:
            if self.patari_controller.annotation is not None:
                self.patari_controller.annotation.roi_library_description_label.setText(
                    ""
                )
            return

        mode = self._roi_library_placement_mode()
        if mode == "auto":
            self._place_library_entry_auto(self.patari_controller, entry)
            return

        self._place_library_entry_static(self.patari_controller, entry)

    def on_roi_library_item_selected(self, roi_id: str) -> None:
        if self.patari_controller.annotation is None:
            return
        library = self._ensure_roi_library_loaded()
        entry = library.get_by_id(roi_id)
        if entry is None:
            self.patari_controller.annotation.roi_library_description_label.setText(
                ""
            )
            return

        desc = str(entry.description or "")
        pos = str(entry.position or "undefined")

        desc = (
            f"{desc} (default position: {pos})"
            if desc
            else f"(default position: {pos})"
        )
        self.patari_controller.annotation.roi_library_description_label.setText(
            desc
        )

    def initialize_roi_library(self) -> None:
        try:
            self._refresh_roi_library_ui()
        except Exception:
            logger.exception("failed to initialize ROI Library")
