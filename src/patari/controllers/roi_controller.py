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


class RoiController:
    """ROI visualization, table management, and ROI export helpers."""

    @staticmethod
    def set_last_roi_position(controller, position: str) -> None:
        """
        Set the "roi_position" property of the most recently added shape to the given position string.
        """

        props = dict(getattr(controller.shapes_layer, "properties", {}) or {})
        positions = list(props.get("roi_position", []))
        if not positions:
            return
        positions[-1] = str(position or "undefined")
        props["roi_position"] = positions
        controller.shapes_layer.properties = props

    @staticmethod
    def apply_roi_colors(controller) -> None:
        """Assign deterministic colors to ROI edges by ROI index."""
        if controller.shapes_layer is None:
            return

        controller.shapes_layer.edge_color = [
            roi_color_for_index(i)
            for i in range(len(controller.shapes_layer.data))
        ]

    @staticmethod
    def apply_roi_labels(controller) -> None:
        """Show ROI index labels next to shapes (when enabled)."""
        if controller.shapes_layer is None:
            return

        try:
            props = dict(
                getattr(controller.shapes_layer, "properties", {}) or {}
            )
            props["roi_id"] = np.arange(
                len(controller.shapes_layer.data), dtype=int
            )
            controller.shapes_layer.properties = props
            # napari text supports formatting from properties.
            controller.shapes_layer.text = {"string": "{roi_id}", "size": 8}
        except Exception:
            logger.exception("failed to apply ROI labels")

    @staticmethod
    def on_shapes_data_changed(controller, event=None) -> None:
        if controller.shapes_layer is None:
            return

        n_shapes = len(controller.shapes_layer.data)

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

        RoiController.apply_roi_colors(controller)
        if ROI_LABELS:
            RoiController.apply_roi_labels(controller)

        RoiController.update_live_table(controller)

    @staticmethod
    def update_live_table(controller, event=None) -> None:
        if controller.roi is None or controller.shapes_layer is None:
            return

        if controller.active_layer is None:
            controller.roi.live_table.value = pd.DataFrame(
                columns=list(dtype_map.keys())
            ).astype(dtype_map)
            return

        pt = list(controller.viewer.dims.point)
        if len(pt) < 2:
            return

        frame_idx = int(round(pt[0]))
        channel_idx = int(round(pt[1]))

        try:
            df = compute_roi_stats(
                controller.shapes_layer,
                controller.active_layer,
                frame_idx,
                channel_idx,
                clamp_min=controller.roi_intensity_min,
                clamp_max=controller.roi_intensity_max,
                clamp_mode=(controller.roi_intensity_mode or "clip"),
            )
        except Exception:
            logger.exception("update_live_table failed")
            df = pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)

        controller.roi.live_table.value = df

        # Keep ROI colors in sync with current shape count/order.
        RoiController.apply_roi_colors(controller)

        # Color first table column to match each ROI color.
        num_shapes = len(controller.shapes_layer.data)
        for row_idx in range(num_shapes):
            item = controller.roi.live_table.native.item(row_idx, 0)
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

    @staticmethod
    def on_save_clicked(controller, event=None) -> None:
        if controller.roi is None or controller.shapes_layer is None:
            return

        selected = controller.shapes_layer.selected_data
        if len(selected) != 1:
            logger.info("Select one ROI to save")
            return

        roi_idx = list(selected)[0]
        df_live = RoiController.table_value_to_df(controller.roi.live_table)
        if df_live.empty or roi_idx >= len(df_live):
            logger.info("Nothing to save")
            return

        include_all_frames = False
        include_all_wavelengths = False
        if controller.annotation is not None:
            cb_frames = getattr(
                controller.annotation, "include_all_frames_checkbox", None
            )
            cb_wavs = getattr(
                controller.annotation, "include_all_wavelengths_checkbox", None
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
            if controller.active_layer is None:
                logger.info("Select an image layer to save ROI stats")
                return

            pt = list(controller.viewer.dims.point)
            if len(pt) < 2:
                return
            frame_idx = int(round(pt[0]))
            channel_idx = int(round(pt[1]))

            data = np.asarray(controller.active_layer.data)
            if data.ndim < 2:
                logger.info("Active layer has no frame/channel dimensions")
                return

            if include_all_frames:
                frames_meta = getattr(
                    controller.active_layer, "metadata", {}
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
                        controller.shapes_layer,
                        controller.active_layer,
                        int(f_idx),
                        int(c_idx),
                        clamp_min=controller.roi_intensity_min,
                        clamp_max=controller.roi_intensity_max,
                        clamp_mode=(controller.roi_intensity_mode or "clip"),
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

        df_saved = RoiController.table_value_to_df(controller.roi.saved_table)
        if df_saved.empty:
            df_saved = rows_to_add.copy()
        else:
            df_saved = pd.concat([df_saved, rows_to_add], ignore_index=True)

        controller.roi.saved_table.value = df_saved.astype(dtype_map)
        logger.info("Saved ROI %s (%s row(s))", roi_idx, len(rows_to_add))

    @staticmethod
    def on_delete_saved_clicked(controller, event=None) -> None:
        if controller.roi is None:
            return

        selection_model = controller.roi.saved_table.native.selectionModel()
        selected_rows = selection_model.selectedRows()
        selected_indices = [idx.row() for idx in selected_rows]
        if not selected_indices:
            logger.info("No row selected to delete.")
            return

        df_saved = RoiController.table_value_to_df(controller.roi.saved_table)
        if df_saved.empty:
            return

        df_saved = df_saved.drop(selected_indices).reset_index(drop=True)
        controller.roi.saved_table.value = df_saved.astype(dtype_map)
        logger.info("Deleted %s saved rows", len(selected_indices))

    @staticmethod
    def on_xlsx_export_clicked(controller, event=None) -> None:
        if controller.roi is None:
            return

        df_saved = RoiController.table_value_to_df(controller.roi.saved_table)
        if df_saved.empty:
            logger.info("Saved table empty")
            return

        filename = export_roi_table_to_xlsx(df_saved)
        if filename is None:
            return

        logger.info("Saved ROI table to %s", filename)

    @staticmethod
    def _ensure_roi_library_loaded(controller) -> RoiLibrary:
        library = getattr(controller, "_roi_library", None)
        if library is None:
            library = RoiLibrary(_roi_library_file())
            library.load()
            controller._roi_library = library
        return library

    @staticmethod
    def _refresh_roi_library_ui(controller) -> None:
        if controller.annotation is None:
            return
        library = RoiController._ensure_roi_library_loaded(controller)
        ids = library.list_ids()
        controller.annotation.set_roi_ids(ids)
        controller.annotation.roi_library_description_label.setText("")

    @staticmethod
    def on_save_roi_library_clicked(controller, event=None) -> None:
        if controller.shapes_layer is None:
            return

        selected = list(controller.shapes_layer.selected_data)
        if len(selected) == 0:
            logger.info("Save ROI clicked with no selected ROI")
            if controller.annotation is not None:
                controller.annotation.roi_library_description_label.setText(
                    "No ROI selected in viewer."
                )
            return

        roi_idx = int(selected[0])
        verts = np.asarray(controller.shapes_layer.data[roi_idx], dtype=float)
        shape_type = str(controller.shapes_layer.shape_type[roi_idx])

        metadata = _roi_name_popup()
        if metadata is None:
            return
        roi_id, description, position = metadata

        source_fov_x_mm = None
        source_fov_y_mm = None
        fov_m = controller._get_fov()
        if fov_m is not None:
            source_fov_x_mm = float(fov_m[0]) * 1000.0
            source_fov_y_mm = float(fov_m[1]) * 1000.0

        library = RoiController._ensure_roi_library_loaded(controller)
        library.add_or_update(
            roi_id=roi_id,
            description=str(description or ""),
            position=str(position or "undefined"),
            shape_type=shape_type,
            vertices=[[float(v[0]), float(v[1])] for v in verts[:, -2:]],
            source_fov_x_mm=source_fov_x_mm,
            source_fov_y_mm=source_fov_y_mm,
        )

        RoiController._refresh_roi_library_ui(controller)
        logger.info("Saved ROI '%s' into ROI Library (in-memory)", roi_id)

    @staticmethod
    def on_remove_roi_library_clicked(controller, event=None) -> None:
        if controller.annotation is None:
            return
        item = controller.annotation.roi_library_list.currentItem()
        if item is None:
            return
        roi_id = item.text()
        if not roi_id:
            return

        library = RoiController._ensure_roi_library_loaded(controller)
        removed = library.remove(roi_id)
        if removed:
            RoiController._refresh_roi_library_ui(controller)
            logger.info(
                "Removed ROI '%s' from ROI Library (in-memory)", roi_id
            )

    @staticmethod
    def on_save_roi_library_file_clicked(controller, event=None) -> None:
        library = RoiController._ensure_roi_library_loaded(controller)
        library.save()
        logger.info("Saved ROI Library to %s", _roi_library_file())

    @staticmethod
    def on_roi_library_item_clicked(controller, roi_id: str) -> None:
        if controller.shapes_layer is None:
            return
        library = RoiController._ensure_roi_library_loaded(controller)
        entry = library.get_by_id(roi_id)
        if entry is None:
            if controller.annotation is not None:
                controller.annotation.roi_library_description_label.setText("")
            return

        target_fov = controller._get_fov()
        if target_fov is not None:
            target_fov_mm = (
                float(target_fov[0]) * 1000.0,
                float(target_fov[1]) * 1000.0,
            )
        else:
            target_fov_mm = None

        source_fov_mm = (
            (entry.source_fov_x_mm, entry.source_fov_y_mm)
            if entry.source_fov_x_mm is not None
            and entry.source_fov_y_mm is not None
            else None
        )
        if (
            source_fov_mm is not None
            and target_fov_mm is not None
            and not np.allclose(
                np.asarray(source_fov_mm, dtype=float),
                np.asarray(target_fov_mm, dtype=float),
                rtol=0.0,
                atol=1e-3,
            )
        ):
            QMessageBox.warning(
                None,
                "ROI Library",
                "ROI was created for a different FOV. It will still be placed literally.",
            )

        verts = np.asarray(entry.vertices, dtype=float)
        if verts.ndim != 2 or verts.shape[1] < 2:
            logger.info("ROI '%s' has invalid vertices", roi_id)
            return

        controller.shapes_layer.add(verts[:, -2:], shape_type=entry.shape_type)
        RoiController.set_last_roi_position(controller, entry.position)
        controller._apply_roi_colors()
        controller.update_live_table()

    @staticmethod
    def on_roi_library_item_selected(controller, roi_id: str) -> None:
        if controller.annotation is None:
            return
        library = RoiController._ensure_roi_library_loaded(controller)
        entry = library.get_by_id(roi_id)
        if entry is None:
            controller.annotation.roi_library_description_label.setText("")
            return

        desc = str(entry.description or "")
        pos = str(entry.position or "undefined")

        desc = (
            f"{desc} (default position: {pos})"
            if desc
            else f"(default position: {pos})"
        )
        controller.annotation.roi_library_description_label.setText(desc)

    @staticmethod
    def initialize_roi_library(controller) -> None:
        try:
            RoiController._refresh_roi_library_ui(controller)
        except Exception:
            logger.exception("failed to initialize ROI Library")
