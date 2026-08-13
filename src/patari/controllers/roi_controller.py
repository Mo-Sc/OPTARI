from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from qtpy.QtCore import QSignalBlocker
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
)

from patari.controllers.base import TaskControllerBase
from patari.io.export_pipeline import export_roi_table_to_xlsx
from patari.roi.roi_presets import RoiPresetStore
from patari.roi.roi_records import ROIRecord
from patari.roi.roi_utils import (
    compute_roi_stats,
    live_table_columns,
    saved_export_columns,
    saved_table_columns,
)
from patari.utils.misc import roi_color_for_index
from patari.utils.setup import get_user_roi_presets_dir
from patari.utils.viewer import selected_frame_idx

from napari.layers import Image

logger = logging.getLogger(__name__)
ROI_EDGE_WIDTH = 0.1


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
        self._saved_full_df = pd.DataFrame(columns=saved_export_columns())
        self._syncing = False
        self._roi_records: dict[int, ROIRecord] = {}
        self._projection_ids: list[int] = []
        self._next_roi_id = 0
        self._next_roi_group_id = 0
        self._projecting = False
        self._roi_preset_store = RoiPresetStore(get_user_roi_presets_dir())

    @property
    def roi_records(self) -> list[ROIRecord]:
        return list(self._roi_records.values())

    def _n_frames(self) -> int:
        return int(np.asarray(self.patari_controller.active_us_layer.data).shape[0])

    # def _current_frame(self) -> int:
    #     return selected_frame_idx(self.viewer, self._n_frames())

    def _new_record(self, verts, kind: str) -> ROIRecord:
        record = ROIRecord(
            roi_id=self._next_roi_id,
            roi_group_id=self._next_roi_group_id,
            frame_id=selected_frame_idx(self.viewer, self._n_frames()),
            verts=verts,
            kind=kind,
        )
        self._next_roi_id += 1
        self._next_roi_group_id += 1
        return record

    def set_roi_records(self, records: list[ROIRecord]) -> None:
        self._roi_records = {record.roi_id: record for record in records}
        self._next_roi_id = max((record.roi_id for record in records), default=-1) + 1
        self._next_roi_group_id = max(
            (record.roi_group_id for record in records), default=-1
        ) + 1
        self.project_current_frame()

    def clear_roi_records(self) -> None:
        self._roi_records.clear()
        self._projection_ids = []

    def current_records(self) -> list[ROIRecord]:
        """Records for the ROIs currently displayed, in display order."""
        return [self._roi_records[roi_id] for roi_id in self._projection_ids]

    def expand_current_projection_to_all_frames(self) -> None:
        self.sync_records_from_shapes()
        if not self._projection_ids:
            return
        source = self._roi_records[self._projection_ids[-1]]
        for frame_id in range(self._n_frames()):
            if frame_id == source.frame_id:
                continue
            record = ROIRecord(
                roi_id=self._next_roi_id,
                roi_group_id=source.roi_group_id,
                frame_id=frame_id,
                verts=source.verts,
                kind=source.kind,
                source=source.source,
                position=source.position,
            )
            self._roi_records[record.roi_id] = record
            self._next_roi_id += 1
        self.project_current_frame()

    def project_current_frame(self) -> None:
        shapes = self.patari_controller.shapes_layer
        if shapes is None or self._projecting:
            return
        frame_id = selected_frame_idx(self.viewer, self._n_frames())
        visible = sorted(
            (r for r in self._roi_records.values() if r.frame_id == frame_id),
            key=lambda r: r.roi_id,
        )
        self._projecting = True
        try:
            # pass (verts, kind) pairs so napari never rebuilds shapes against a stale shape_type
            shapes.data = [(r.verts, r.kind) for r in visible]
            if visible:
                shapes.edge_width = [ROI_EDGE_WIDTH] * len(visible)
            self._projection_ids = [r.roi_id for r in visible]
            shapes.selected_data = set()
        finally:
            self._projecting = False
        self._refresh_shape_display()

    def _match_ids_after_removal(self, data, kinds: list[str]) -> list[int | None]:
        """Match surviving shapes to their prior ids; removal preserves relative order."""
        old_records = self.current_records()
        matched: list[int | None] = []
        j = 0
        for verts, kind in zip(data, kinds):
            verts = np.asarray(verts, dtype=float)
            while j < len(old_records) and not (
                old_records[j].kind == kind
                and np.array_equal(old_records[j].verts, verts)
            ):
                j += 1
            matched.append(old_records[j].roi_id if j < len(old_records) else None)
            j += 1
        return matched

    def sync_records_from_shapes(self) -> None:
        """Keep frame-owned ROI records in sync with the projected Shapes layer.

        Same/grown shape count: ids are kept positionally (napari always
        appends new shapes at the end; in-place edits keep their position).
        Shrunk shape count: removal preserves the relative order of survivors,
        so ids are recovered by matching remaining geometry to the old records.
        """
        shapes = self.patari_controller.shapes_layer
        if shapes is None or self._projecting:
            return

        data = list(shapes.data)
        kinds = [str(k) for k in shapes.shape_type]
        old_ids = self._projection_ids

        if len(data) < len(old_ids):
            new_ids = self._match_ids_after_removal(data, kinds)
        else:
            new_ids = old_ids + [None] * (len(data) - len(old_ids))

        for i, (verts, kind) in enumerate(zip(data, kinds)):
            if new_ids[i] is None:
                record = self._new_record(verts, kind)
                new_ids[i] = record.roi_id
                self._roi_records[record.roi_id] = record
            else:
                record = self._roi_records[new_ids[i]]
                record.verts = np.asarray(verts, dtype=float).copy()
                record.kind = kind

        for stale_id in set(old_ids) - set(new_ids):
            del self._roi_records[stale_id]
        self._projection_ids = new_ids

    @staticmethod
    def _filter_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=columns)
        return df.loc[:, columns]

    def _set_saved_table_view(self) -> None:
        """
        Set the saved table view to the current saved full dataframe, filtered to the visible columns.
        """
        if self.patari_controller.roi is None:
            return
        cols = saved_table_columns()
        self.patari_controller.roi.saved_table.value = self._filter_columns(
            self._saved_full_df, cols
        )

    def _set_live_table_selection(self, selected_rows: list[int]) -> None:
        if self.patari_controller.roi is None:
            return
        table = self.patari_controller.roi.live_table.native
        with QSignalBlocker(table):
            table.clearSelection()
            for row in selected_rows:
                if row < table.rowCount():
                    table.selectRow(row)

    def _update_save_button_state(self) -> None:
        """Update save button enabled state based on current ROI selection."""
        selected = self.patari_controller.shapes_layer.selected_data
        self.patari_controller.roi.save_button.setEnabled(len(selected) > 0)

    def on_shapes_selection_changed(self, event=None) -> None:
        """Sync shapes selection -> live table selection on selection changes only."""
        shapes = self.patari_controller.shapes_layer
        if self._syncing or shapes is None or self.patari_controller.roi is None:
            return
        selected = list(shapes.selected_data)
        self._syncing = True
        try:
            self._set_live_table_selection(selected)
        finally:
            self._syncing = False
        
        self._update_save_button_state()

    def on_live_table_selection_changed(self) -> None:
        """Sync live table row selection → shapes layer selection."""
        shapes = self.patari_controller.shapes_layer
        if self._syncing or shapes is None or self.patari_controller.roi is None:
            return
        # Never write selection back into napari during shape drag/select interactions.
        if getattr(shapes, "_is_moving", False) or getattr(shapes, "_is_selecting", False):
            return
        rows = {idx.row() for idx in self.patari_controller.roi.live_table.native.selectedIndexes()}
        self._syncing = True
        try:
            if rows and self.viewer.layers.selection.active is not shapes:
                self.viewer.layers.selection.active = shapes
            shapes.selected_data = rows
        finally:
            self._syncing = False

        # The selection callback is suppressed while _syncing is True,
        # so update the Save button state explicitly after table -> viewer sync.
        self._update_save_button_state()

    def on_live_table_delete_key(self) -> None:
        """Delete selected shapes when Delete is pressed in the live table.
        TODO: check is this working?
        """
        if self.patari_controller.shapes_layer is None:
            return
        if self.patari_controller.shapes_layer.selected_data:
            self.patari_controller.shapes_layer.remove_selected()

    def _on_empty_roi_text_changed(self, text: str) -> None:
        if not (text or "").strip():
            self.patari_controller._on_roi_intensity_settings_changed()

    def _on_roi_intensity_toggle_changed(self, checked: bool) -> None:
        self.patari_controller._on_roi_intensity_settings_changed()

    def bind_events(self) -> None:
        """Connect ROI and annotation dock signals."""
        # ROI table buttons
        self.patari_controller.roi.save_button.clicked.connect(
            self.on_save_clicked
        )
        self.patari_controller.roi.live_table_delete_shortcut.activated.connect(
            self.on_live_table_delete_key
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
            edit.textChanged.connect(self._on_empty_roi_text_changed)

        ann.roi_clipping_box.toggled.connect(
            self._on_roi_intensity_toggle_changed
        )
        ann.roi_exclusion_box.toggled.connect(
            self._on_roi_intensity_toggle_changed
        )

        # ROI presets
        ann.roi_presets_list.itemClicked.connect(
            self.on_roi_preset_item_selected
        )
        ann.roi_presets_list.itemDoubleClicked.connect(
            self.on_roi_preset_item_clicked
        )
        ann.save_roi_preset_button.clicked.connect(
            self.on_save_roi_preset_clicked
        )
        ann.remove_roi_preset_button.clicked.connect(
            self.on_remove_roi_preset_clicked
        )
        ann.place_roi_button.clicked.connect(self.on_place_roi_clicked)

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
            self.patari_controller.roi.live_table_delete_shortcut.activated.disconnect(
                self.on_live_table_delete_key
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
                edit.textChanged.disconnect(self._on_empty_roi_text_changed)

            ann.roi_clipping_box.toggled.disconnect(
                self._on_roi_intensity_toggle_changed
            )
            ann.roi_exclusion_box.toggled.disconnect(
                self._on_roi_intensity_toggle_changed
            )

            ann.roi_presets_list.itemClicked.disconnect(
                self.on_roi_preset_item_selected
            )
            ann.roi_presets_list.itemDoubleClicked.disconnect(
                self.on_roi_preset_item_clicked
            )
            ann.save_roi_preset_button.clicked.disconnect(
                self.on_save_roi_preset_clicked
            )
            ann.remove_roi_preset_button.clicked.disconnect(
                self.on_remove_roi_preset_clicked
            )
            ann.place_roi_button.clicked.disconnect(self.on_place_roi_clicked)
        except Exception as e:
            logger.exception(
                "Error unbinding ROI and annotation dock signals: %s", e
            )

    def _refresh_shape_display(self) -> None:
        """Recolor and relabel ROI shapes from their records."""
        shapes = self.patari_controller.shapes_layer
        records = self.current_records()
        shapes.edge_color = [roi_color_for_index(i) for i in range(len(records))]
        shapes.properties = {
            "roi_id": [r.roi_id for r in records],
            "roi_group_id": [r.roi_group_id for r in records],
            "roi_source": [r.source for r in records],
            "roi_position": [r.position for r in records],
        }
        # napari text supports formatting from properties.
        shapes.text = {"string": "{roi_id}", "size": 8}

    def on_shapes_data_changed(self, event=None) -> None:
        if self.patari_controller.shapes_layer is None or self._projecting:
            return

        self.sync_records_from_shapes()
        self._refresh_shape_display()

        self._update_save_button_state()
        self.update_live_table()

    def update_live_table(self, event=None) -> None:
        if self.patari_controller.roi is None:
            return

        if self.patari_controller.shapes_layer is None:
            self.patari_controller.roi.live_table.value = pd.DataFrame(
                columns=live_table_columns()
            )
            return

        if self.patari_controller.active_recon_layer is None:
            cols = live_table_columns()
            self.patari_controller.roi.live_table.value = pd.DataFrame(columns=cols)
            return

        pt = list(self.viewer.dims.point)
        if len(pt) < 2:
            return

        frame_idx = int(round(pt[0]))
        channel_idx = int(round(pt[1]))
        live_cols = live_table_columns()

        try:
            df_live = compute_roi_stats(
                self.current_records(),
                self.patari_controller.active_recon_layer,
                frame_idx,
                channel_idx,
                clamp_min=self.patari_controller.roi_intensity_min,
                clamp_max=self.patari_controller.roi_intensity_max,
                clamp_mode=(
                    self.patari_controller.roi_intensity_mode or "clip"
                ),
                feature_ids=live_cols,
            )
        except Exception:
            logger.exception("update_live_table failed")
            df_live = pd.DataFrame(columns=live_cols)

        selected_rows = []
        if self.patari_controller.shapes_layer is not None:
            selected_rows = list(self.patari_controller.shapes_layer.selected_data)

        self._syncing = True
        try:
            self.patari_controller.roi.live_table.value = self._filter_columns(
                df_live, live_cols
            )
            self._set_live_table_selection(selected_rows)
        finally:
            self._syncing = False

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
        """
        Save selected ROIs from the live table to the saved table.
        If "include all frames/channels" is enabled, compute stats for all frames/channels of the active recon layer and include rows for all selected ROIs.
        """
        if (
            self.patari_controller.roi is None
            or self.patari_controller.shapes_layer is None
        ):
            return

        selected_indices = list(self.patari_controller.shapes_layer.selected_data)
        if not selected_indices:
            logger.info("Select at least one ROI to save")
            return
        selected_ids = {
            self._projection_ids[index]
            for index in selected_indices
            if index < len(self._projection_ids)
        }

        include_all_layers = False
        include_all_frames = False
        include_all_channels = False

        if self.patari_controller.annotation is not None:
            include_all_layers = self.patari_controller.annotation.include_all_layers_checkbox.isChecked()
            include_all_frames = self.patari_controller.annotation.include_all_frames_checkbox.isChecked()
            include_all_channels = self.patari_controller.annotation.include_all_channels_checkbox.isChecked()
  

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

        target_layers = [self.patari_controller.active_recon_layer]
        if include_all_layers:
            target_layers = [
                layer
                for layer in self.viewer.layers
                if isinstance(layer, Image) and layer.metadata.get("type") == "pa"
            ]

        records = self.current_records()
        collected: list[pd.DataFrame] = []
        for layer in target_layers:
            layer_data = np.asarray(layer.data)
            if layer_data.ndim < 2:
                continue

            if include_all_frames:
                frames_meta = getattr(layer, "metadata", {}).get("frames")
                frame_indices = [int(f) for f in frames_meta] if frames_meta else list(range(layer_data.shape[0]))
            else:
                frame_indices = [frame_idx]

            channel_indices = list(range(layer_data.shape[1])) if include_all_layers or include_all_channels else [channel_idx]

            for f_idx in frame_indices:
                for c_idx in channel_indices:
                    df_slice = compute_roi_stats(
                        records,
                        layer,
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
                    df_rows = df_slice[roi_index_numeric.isin(selected_ids)]
                    if not df_rows.empty:
                        collected.append(df_rows)

        if not collected:
            logger.info("Nothing to save")
            return

        rows_to_add = pd.concat(collected, ignore_index=True)

        if rows_to_add.empty:
            logger.info("Nothing to save")
            return

        rows_to_add = rows_to_add.copy()
        rows_to_add["roi_ts"] = pd.Timestamp.now().isoformat(timespec="seconds")

        if self._saved_full_df.empty:
            self._saved_full_df = rows_to_add.loc[:, saved_export_columns()].copy()
        else:
            self._saved_full_df = pd.concat(
                [self._saved_full_df, rows_to_add.loc[:, saved_export_columns()]],
                ignore_index=True,
            )

        self._set_saved_table_view()
        logger.info("Saved %s ROI(s) (%s total row(s))", len(selected_indices), len(rows_to_add))

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

        if self._saved_full_df.empty:
            return

        self._saved_full_df = self._saved_full_df.drop(selected_indices).reset_index(drop=True)
        self._set_saved_table_view()
        logger.info("Deleted %s saved rows", len(selected_indices))

    def on_xlsx_export_clicked(self, event=None) -> None:
        if self.patari_controller.roi is None:
            return

        if self._saved_full_df.empty:
            logger.info("Saved table empty")
            return

        filename = export_roi_table_to_xlsx(self._saved_full_df)
        if filename is None:
            return

        logger.info("Saved ROI table to %s", filename)

    def _refresh_roi_presets_ui(self) -> None:
        if self.patari_controller.annotation is None:
            return
        try:
            names = [preset.name for preset in self._roi_preset_store.list_presets()]
        except (TypeError, ValueError, OSError) as exc:
            self.patari_controller.annotation.set_roi_preset_names([])
            self.patari_controller.annotation.roi_presets_description_label.setText(
                f"Could not load ROI presets: {exc}"
            )
            return
        self.patari_controller.annotation.set_roi_preset_names(names)
        self.patari_controller.annotation.roi_presets_description_label.setText("")

    def on_save_roi_preset_clicked(self, event=None) -> None:
        if self.patari_controller.shapes_layer is None:
            return

        selected = list(self.patari_controller.shapes_layer.selected_data)
        if len(selected) == 0:
            logger.info("Save ROI preset clicked with no selected ROI")
            if self.patari_controller.annotation is not None:
                self.patari_controller.annotation.roi_presets_description_label.setText(
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

        fov_m = self.patari_controller._get_fov()
        if fov_m is None:
            self.patari_controller.annotation.roi_presets_description_label.setText(
                "Could not save ROI preset: current scan has no valid FOV."
            )
            return
        source_fov_x_mm = float(fov_m[0]) * 1000.0
        source_fov_y_mm = float(fov_m[1]) * 1000.0

        try:
            preset_path = self._roi_preset_store.save_preset(
                name=roi_id,
                description=str(description or ""),
                position=str(position or "undefined"),
                shape_type=shape_type,
                vertices=[[float(v[0]), float(v[1])] for v in verts[:, -2:]],
                source_fov_x_mm=source_fov_x_mm,
                source_fov_y_mm=source_fov_y_mm,
            )
        except (TypeError, ValueError, OSError) as exc:
            self.patari_controller.annotation.roi_presets_description_label.setText(
                f"Could not save ROI preset: {exc}"
            )
            return

        self._refresh_roi_presets_ui()
        logger.info("Saved ROI preset '%s' to %s", roi_id, preset_path)

    def on_remove_roi_preset_clicked(self, event=None) -> None:
        if self.patari_controller.annotation is None:
            return
        item = self.patari_controller.annotation.roi_presets_list.currentItem()
        if item is None:
            return
        preset_name = item.text()
        if not preset_name:
            return

        try:
            removed = self._roi_preset_store.delete(preset_name)
        except (TypeError, ValueError, OSError) as exc:
            self.patari_controller.annotation.roi_presets_description_label.setText(
                f"Could not remove ROI preset: {exc}"
            )
            return
        if removed:
            self._refresh_roi_presets_ui()
            logger.info("Removed ROI preset '%s'", preset_name)

    def _set_roi_placement_mode(self, mode: str) -> None:

        combo = self.patari_controller.annotation.roi_placement_mode_combo
        idx = combo.findData(mode)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _default_roi_placement_mode_for_preset(self, preset) -> str:
        position_name = str(getattr(preset, "position", "") or "").strip()
        if not position_name or position_name == "undefined":
            return "static"

        result = self.patari_controller.segmentation_ctrl.active_seg_mask_2d()
        if result is None:
            return "static"

        seg, seg_layer = result
        class_names = (seg_layer.metadata or {}).get("class_names", {})
        class_name_to_id = {
            str(name).strip(): int(class_id) for class_id, name in class_names.items()
        }

        if position_name not in class_name_to_id:
            return "static"

        class_id = class_name_to_id[position_name]
        return "auto" if np.any(seg == int(class_id)) else "static"

    @staticmethod
    def _place_roi_preset_static(controller, preset) -> None:
        """Place a preset while preserving its physical size across FOVs."""
        verts = np.asarray(preset.vertices, dtype=float)[:, -2:]
        target_fov = controller._get_fov()
        if target_fov is None:
            raise ValueError("Current scan has no valid FOV.")

        source_fov = (
            preset.source_fov_x_mm / 1000.0,
            preset.source_fov_y_mm / 1000.0,
        )
        source_center = np.mean(verts, axis=0)
        target_center = np.array(
            [
                source_center[0] * target_fov[1] / source_fov[1],
                source_center[1] * target_fov[0] / source_fov[0],
            ]
        )
        verts += target_center - source_center

        if (
            np.any(verts[:, 0] < 0)
            or np.any(verts[:, 0] > target_fov[1] * 1000)
            or np.any(verts[:, 1] < 0)
            or np.any(verts[:, 1] > target_fov[0] * 1000)
        ):
            raise ValueError("ROI preset does not fit in the target FOV.")

        controller.shapes_layer.add(verts, shape_type=preset.shape_type)
        # Auto-select the newly placed ROI so the Save button activates immediately.
        new_idx = len(controller.shapes_layer.data) - 1
        controller.shapes_layer.selected_data = {new_idx}

    @staticmethod
    def _place_roi_preset_auto(controller, preset) -> None:
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

        target_class_name = str(preset.position or "").strip()
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
                f"Class '{target_class_name}' is not present in the selected frame.",
            )
            return

        verts = np.asarray(preset.vertices, dtype=float)[:, -2:]
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

        controller.shapes_layer.add(verts_shifted, shape_type=preset.shape_type)
        # Auto-select the newly placed ROI so the Save button activates immediately.
        new_idx = len(controller.shapes_layer.data) - 1
        controller.shapes_layer.selected_data = {new_idx}

    def _place_selected_roi_preset(self) -> None:
        if self.patari_controller.shapes_layer is None:
            return
        annotation = self.patari_controller.annotation
        item = annotation.roi_presets_list.currentItem()
        if item is None:
            return
        try:
            preset = self._roi_preset_store.get(item.text())
        except (TypeError, ValueError, OSError) as exc:
            annotation.roi_presets_description_label.setText(
                f"Could not load ROI preset: {exc}"
            )
            return

        try:
            mode = str(annotation.roi_placement_mode_combo.currentData())
            if mode == "auto":
                self._place_roi_preset_auto(self.patari_controller, preset)
            else:
                self._place_roi_preset_static(self.patari_controller, preset)
            if annotation.all_frames_radio.isChecked():
                self.expand_current_projection_to_all_frames()
        except ValueError as exc:
            annotation.roi_presets_description_label.setText(
                f"Could not place ROI preset: {exc}"
            )

    def on_place_roi_clicked(self, event=None) -> None:
        self._place_selected_roi_preset()

    def on_roi_preset_item_clicked(self, item) -> None:
        self._place_selected_roi_preset()

    def on_roi_preset_item_selected(self, item) -> None:
        if self.patari_controller.annotation is None:
            return
        try:
            preset = self._roi_preset_store.get(item.text())
        except (TypeError, ValueError, OSError) as exc:
            self.patari_controller.annotation.roi_presets_description_label.setText(
                f"Could not load ROI preset: {exc}"
            )
            return

        self._set_roi_placement_mode(
            self._default_roi_placement_mode_for_preset(preset)
        )

        desc = str(preset.description or "")
        pos = str(preset.position or "undefined")

        desc = (
            f"{desc} (default position: {pos})"
            if desc
            else f"(default position: {pos})"
        )
        self.patari_controller.annotation.roi_presets_description_label.setText(
            desc
        )

    def initialize_ui(self) -> None:
        """Initialize ROI preset controls and current ROI display state."""
        self._refresh_roi_presets_ui()
        self.refresh_ui()

    def refresh_ui(self) -> None:
        """Refresh ROI controls after scan or active-layer state changes."""
        if self.patari_controller.roi is None:
            return
        if self.patari_controller.shapes_layer is None:
            self.patari_controller.roi.save_button.setEnabled(False)
            self.update_live_table()
            return
        self._update_save_button_state()
        self.update_live_table()
