from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
from napari.layers import Labels
from qtpy.QtCore import QSignalBlocker
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
)

from patari.config import settings
from patari.controllers.base import TaskControllerBase
from patari.io.export_pipeline import (
    export_roi_table_to_xlsx,
    import_roi_table_from_xlsx,
)
from patari.roi.roi_geometry import RoiGeometry, napari_to_patato
from patari.roi.roi_presets import RoiPresetStore
from patari.roi.roi_records import ROIRecord
from patari.roi.roi_shapes import class_top_at_center_column
from patari.roi.roi_table import SavedRoiTable
from patari.roi.roi_utils import (
    IntensityClamp,
    clear_mask_cache,
    compute_roi_stats,
    layer_fov_m,
    records_by_track_and_frame,
    visible_feature_columns,
)
from patari.utils.misc import parse_float_input, roi_color_for_index
from patari.utils.setup import get_user_roi_autosave_file, get_user_roi_presets_dir
from patari.utils.viewer import selected_frame_and_channel, selected_frame_idx

from napari.layers import Image
from napari.utils.notifications import show_error, show_info

logger = logging.getLogger(__name__)
ROI_EDGE_WIDTH = 0.1

# napari actions that we are listening to for ROI changes
# usually emit two events: an intent event before the layer is mutated, and a completion event after
_COMPLETED_DATA_ACTIONS = {"added", "changed", "removed"}


def _roi_name_popup() -> tuple[str, str, str] | None:
    dialog = QDialog()
    dialog.setWindowTitle("Save ROI")

    form = QFormLayout(dialog)
    roi_id_edit = QLineEdit()
    description_edit = QLineEdit()
    tissue_class_edit = QLineEdit()
    tissue_class_edit.setPlaceholderText("undefined")
    tissue_class_edit.setToolTip(
        "Segmentation class name to auto-place this preset in, e.g. \"muscle\""
    )
    form.addRow("ROI Name:", roi_id_edit)
    form.addRow("Description (optional):", description_edit)
    form.addRow("Tissue class (optional):", tissue_class_edit)

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
    tissue_class = (tissue_class_edit.text() or "").strip() or "undefined"
    return roi_id, description, tissue_class


class RoiController(TaskControllerBase):
    """ROI visualization, table management, and ROI export helpers."""

    def __init__(self, parent_controller):
        super().__init__(parent_controller)
        self.saved_table = SavedRoiTable(get_user_roi_autosave_file())
        self._syncing = False
        self._roi_records: dict[int, ROIRecord] = {}
        self._projection_ids: list[int] = []
        self._next_roi_id = 0
        self._next_track_id = 0
        self._projecting = False
        self.intensity_clamp = IntensityClamp()
        self._roi_preset_store = RoiPresetStore(get_user_roi_presets_dir())

    @property
    def roi_records(self) -> list[ROIRecord]:
        return list(self._roi_records.values())

    def _n_frames(self) -> int:
        layer = self.patari_controller.active_us_layer
        if layer is None:
            layer = self.patari_controller.active_recon_layer
        if layer is not None:
            return int(layer.data.shape[0])
        return int(self.patari_controller.pa_data.shape[0])

    def _new_record(self, verts, kind: str) -> ROIRecord:
        record = ROIRecord(
            roi_id=self._next_roi_id,
            track_id=self._next_track_id,
            frame_id=selected_frame_idx(self.viewer, self._n_frames()),
            verts=verts,
            kind=kind,
        )
        self._next_roi_id += 1
        self._next_track_id += 1
        return record

    def set_roi_records(self, records: list[ROIRecord]) -> None:
        self._roi_records = {record.roi_id: record for record in records}
        self._next_roi_id = max((record.roi_id for record in records), default=-1) + 1
        self._next_track_id = max(
            (record.track_id for record in records), default=-1
        ) + 1
        self.project_current_frame()

    def clear_roi_records(self) -> None:
        self._roi_records.clear()
        self._projection_ids = []
        clear_mask_cache()

    def current_records(self) -> list[ROIRecord]:
        """Records for the ROIs currently displayed, in display order."""
        return [self._roi_records[roi_id] for roi_id in self._projection_ids]

    def expand_current_projection_to_all_frames(
        self,
        verts_for_frame: Callable[[int, np.ndarray], np.ndarray | None] | None = None,
    ) -> None:
        """Duplicate the last-placed ROI onto every other frame, as one group.

        `verts_for_frame(frame_id, source_verts)` lets a caller resolve each
        frame's own geometry instead of reusing `source_verts` unchanged e.g.
        auto-placement re-anchoring to that frame's own segmentation mask. 
        Returning None skips that frame entirely
        """
        self.sync_records_from_shapes()
        if not self._projection_ids:
            return
        source = self._roi_records[self._projection_ids[-1]]
        resolve = verts_for_frame or (lambda frame_id, verts: verts)
        for frame_id in range(self._n_frames()):
            if frame_id == source.frame_id:
                continue
            verts = resolve(frame_id, source.verts)
            if verts is None:
                continue
            record = ROIRecord(
                roi_id=self._next_roi_id,
                track_id=source.track_id,
                frame_id=frame_id,
                verts=verts,
                kind=source.kind,
                source=source.source,
                tissue_class=source.tissue_class,
                roi_group_uid=source.roi_group_uid,
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

    def sync_records_from_shapes(self) -> bool:
        """Keep frame-owned ROI records in sync with the projected Shapes layer.

        Same/grown shape count: ids are kept positionally (napari always
        appends new shapes at the end. in-place edits keep their position).
        Smaller shape count: removal preserves the relative order of remaining shapes,
        so ids are recovered by matching remaining geometry to the old records.

        Returns whether anything actually changed, so callers can skip the 
        refresh when the layer already agrees with the records.
        """
        shapes = self.patari_controller.shapes_layer
        if shapes is None or self._projecting:
            return False

        data = list(shapes.data)
        kinds = [str(k) for k in shapes.shape_type]
        old_ids = self._projection_ids

        if len(data) < len(old_ids):
            new_ids = self._match_ids_after_removal(data, kinds)
        else:
            new_ids = old_ids + [None] * (len(data) - len(old_ids))

        changed = len(data) != len(old_ids)
        for i, (verts, kind) in enumerate(zip(data, kinds)):
            if new_ids[i] is None:
                record = self._new_record(verts, kind)
                new_ids[i] = record.roi_id
                self._roi_records[record.roi_id] = record
                changed = True
            else:
                record = self._roi_records[new_ids[i]]
                verts = np.asarray(verts, dtype=float)
                changed = changed or record.kind != kind or not np.array_equal(
                    record.verts, verts
                )
                record.verts = verts.copy()
                record.kind = kind

        for stale_id in set(old_ids) - set(new_ids):
            del self._roi_records[stale_id]
            changed = True
        self._projection_ids = new_ids
        return changed

    @staticmethod
    def _filter_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=columns)
        return df.loc[:, columns]

    def _set_saved_table_view(self) -> None:
        """Push the saved rows into the widget and gate the actions that need rows."""
        if self.patari_controller.roi is None:
            return
        self.patari_controller.roi.saved_table.value = self.saved_table.visible_rows()
        has_rows = not self.saved_table.is_empty
        self.patari_controller.roi.delete_button.setEnabled(has_rows)
        self.patari_controller.roi.xlsx_button.setEnabled(has_rows)

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
        on MacOS the actual Delete (forward-delete) key (Fn+Backspace) has to be pressed, not just the backspace key
        """
        if self.patari_controller.shapes_layer is None:
            return
        if self.patari_controller.shapes_layer.selected_data:
            self.patari_controller.shapes_layer.remove_selected()

    # ============ ROI intensity filtering ============

    def on_intensity_settings_changed(self, _=None) -> None:
        """Read the intensity filter and measure."""
        annotation = self.patari_controller.annotation
        if annotation is None:
            return

        if annotation.roi_exclusion_box.isChecked():
            self.intensity_clamp =  IntensityClamp(
                minimum=parse_float_input(annotation.roi_exclude_min_edit.text()),
                maximum=parse_float_input(annotation.roi_exclude_max_edit.text()),
                mode="exclude",
            )
        if annotation.roi_clipping_box.isChecked():
            self.intensity_clamp = IntensityClamp(
                minimum=parse_float_input(annotation.roi_clip_min_edit.text()),
                maximum=parse_float_input(annotation.roi_clip_max_edit.text()),
            )

        self.update_live_table()

    def _signal_bindings(self) -> list[tuple[object, object]]:
        """Every (signal, handler) pair this controller owns.

        Declared once and walked in both directions, so a new binding cannot be
        connected but forgotten on teardown
        """
        roi = self.patari_controller.roi
        ann = self.patari_controller.annotation
        intensity_edits = (
            ann.roi_clip_min_edit,
            ann.roi_clip_max_edit,
            ann.roi_exclude_min_edit,
            ann.roi_exclude_max_edit,
        )
        return [
            # ROI table buttons and shortcuts
            (roi.save_button.clicked, self.on_save_clicked),
            (roi.delete_button.clicked, self.on_delete_saved_clicked),
            (roi.xlsx_button.clicked, self.on_xlsx_export_clicked),
            (roi.import_button.clicked, self.on_import_clicked),
            (roi.saved_table.native.cellDoubleClicked, self.on_saved_row_double_clicked),
            (roi.saved_table_restore_shortcut.activated, self.on_restore_selected_rows),
            (roi.live_table_delete_shortcut.activated, self.on_live_table_delete_key),
            # Annotation dock: ROI intensity settings
            *(
                (edit.editingFinished, self.on_intensity_settings_changed)
                for edit in intensity_edits
            ),
            (ann.roi_clipping_box.toggled, self.on_intensity_settings_changed),
            (ann.roi_exclusion_box.toggled, self.on_intensity_settings_changed),
            # ROI presets
            (ann.roi_presets_list.itemClicked, self.on_roi_preset_item_selected),
            (ann.roi_presets_list.itemDoubleClicked, self.on_roi_preset_item_clicked),
            (ann.roi_presets_list.itemSelectionChanged,
             self._update_remove_roi_preset_button_state),
            (ann.save_roi_preset_button.clicked, self.on_save_roi_preset_clicked),
            (ann.remove_roi_preset_button.clicked, self.on_remove_roi_preset_clicked),
            (ann.place_roi_button.clicked, self.on_place_roi_clicked),
        ]

    def bind_events(self) -> None:
        """Connect ROI and annotation dock signals."""
        for signal, handler in self._signal_bindings():
            signal.connect(handler)

    def unbind_events(self) -> None:
        """Disconnect ROI and annotation dock signals."""
        for signal, handler in self._signal_bindings():
            # Per binding, so one already-disconnected signal cannot abort the rest.
            try:
                signal.disconnect(handler)
            except (RuntimeError, TypeError):
                logger.debug("ROI signal was already disconnected", exc_info=True)

    def _refresh_shape_display(self) -> None:
        """Recolor and relabel ROI shapes from their records."""
        shapes = self.patari_controller.shapes_layer
        records = self.current_records()
        shapes.edge_color = [roi_color_for_index(i) for i in range(len(records))]
        shapes.properties = {
            "roi_id": [r.roi_id for r in records],
            "track_id": [r.track_id for r in records],
            "roi_group_uid": [r.roi_group_uid for r in records],
            "roi_source": [r.source for r in records],
            "roi_tissue_class": [r.tissue_class for r in records],
        }
        # napari text supports formatting from properties.
        label = "{roi_id}/{track_id}" if settings.annotation.show_track_id else "{roi_id}"
        shapes.text = {"string": label, "size": settings.annotation.roi_label_size}

    def on_shapes_data_changed(self, event=None) -> None:
        # napari emits events.data in pairs: an intent event before the layer is
        # mutated (adding/changing/removing) and a completion event after. 
        # We only want to refresh the ROI table on the completion event, so ignore the intent event.
        action = getattr(event, "action", None)
        if action is not None and str(action) not in _COMPLETED_DATA_ACTIONS:
            return
        if self.patari_controller.shapes_layer is None or self._projecting:
            return

        # Several napari signals can report the same edit. only refresh for real ones.
        projected_before = list(self._projection_ids)
        if not self.sync_records_from_shapes():
            return

        # Shape labels and colours come from ids, sources and positions, none of which
        # is affected by geometry edits. So only refresh the display if the set of projected ids changed
        if self._projection_ids != projected_before:
            self._refresh_shape_display()

        self._update_save_button_state()
        self.update_live_table()

    def on_shapes_set_data(self, event=None) -> None:
        """Catch shape additions that never emit ``events.data``.

        copy/pasting shapes (e.g. from one frame to another) appends to the layer and emits
        only ``set_data``, so a pasted ROI would stay invisible. ``set_data`` also fires on every redraw, 
        hence the count check before doing any real work.
        """
        shapes = self.patari_controller.shapes_layer
        if shapes is None or self._projecting:
            return
        if len(shapes.data) != len(self._projection_ids):
            self.on_shapes_data_changed()

    def update_live_table(self, event=None) -> None:
        if self.patari_controller.roi is None:
            return

        if self.patari_controller.shapes_layer is None:
            self.patari_controller.roi.live_table.value = pd.DataFrame(
                columns=visible_feature_columns()
            )
            return

        if self.patari_controller.active_recon_layer is None:
            cols = visible_feature_columns()
            self.patari_controller.roi.live_table.value = pd.DataFrame(columns=cols)
            return

        frame_channel = selected_frame_and_channel(self.viewer)
        if frame_channel is None:
            return
        frame_idx, channel_idx = frame_channel
        live_cols = visible_feature_columns()

        try:
            df_live = compute_roi_stats(
                self.current_records(),
                self.patari_controller.active_recon_layer,
                frame_idx,
                channel_idx,
                clamp=self.intensity_clamp,
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
            self.patari_controller.roi.live_table.value = df_live
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

    def on_save_clicked(self, event=None) -> None:
        """Measure the ROIs selected in the viewer and add to the Saved Analysis table."""
        selected_ids = self._selected_roi_ids()
        if not selected_ids:
            return

        rows = self._measure_selected_rois(selected_ids)
        if rows.empty:
            logger.info("Nothing to save")
            return

        self._append_saved_rows(rows, n_rois=len(selected_ids))

    def _selected_roi_ids(self) -> set[int]:
        """roi_ids of the ROIs selected in the viewer, empty (with a reason) if none."""
        if (
            self.patari_controller.roi is None
            or self.patari_controller.shapes_layer is None
        ):
            return set()

        selected = list(self.patari_controller.shapes_layer.selected_data)
        if not selected:
            logger.info("Select at least one ROI to save")
            return set()
        return {
            self._projection_ids[index]
            for index in selected
            if index < len(self._projection_ids)
        }

    def _save_scope(self) -> tuple[bool, bool, bool]:
        """The three "include all ..." checkboxes, all off without an annotation dock."""
        annotation = self.patari_controller.annotation
        if annotation is None:
            return False, False, False
        return (
            annotation.include_all_layers_checkbox.isChecked(),
            annotation.include_all_frames_checkbox.isChecked(),
            annotation.include_all_channels_checkbox.isChecked(),
        )

    def _follow_track_across_frames(self) -> bool:
        """Which record "Include all frames" should use on each frame: the one
        the user selected, reused everywhere (default), or that ROI's tracked group's own record per frame, skipping a
        frame the track has no record on."""
        annotation = self.patari_controller.annotation
        return annotation is not None and annotation.save_scope_track_radio.isChecked()

    def _track_histories_for_selection(
        self, selected_ids: set[int]
    ) -> dict[int, tuple[ROIRecord, dict[int, ROIRecord]]]:
        """For each selected ROI's track: the record the user actually selected
        (as fallback), and that track's whole {frame_id: record} history.

        Computed once per save, not once per frame: building this scales with how
        many tracks are selected, not with how many frames/layers are being saved,
        which matters once "include all frames" is combined with a large sequence.
        Uses the same ``records_by_track_and_frame`` that Time Analysis's Track ID
        scope does; ``_records_at_frame`` decides what a missing frame does with
        this, mirroring Time Analysis's own scope choice.
        """
        fallbacks = {
            self._roi_records[roi_id].track_id: self._roi_records[roi_id]
            for roi_id in selected_ids
        }
        return {
            track_id: (
                fallback,
                records_by_track_and_frame(self._roi_records.values(), track_id),
            )
            for track_id, fallback in fallbacks.items()
        }

    @staticmethod
    def _records_at_frame(
        tracks: dict[int, tuple[ROIRecord, dict[int, ROIRecord]]],
        frame_idx: int,
        *,
        follow_track: bool,
    ) -> list[ROIRecord]:
        """One record per selected track, as it exists on *frame_idx*.

        `follow_track=False`: the record the user selected, reused unchanged
        on every frame. 
        `follow_track=True`: that track's own record on this
        frame. a track with none here is left out.
        """
        if not follow_track:
            return [fallback for fallback, _ in tracks.values()]
        return [track[frame_idx] for _, track in tracks.values() if frame_idx in track]

    def _measure_selected_rois(self, selected_ids: set[int]) -> pd.DataFrame:
        """Measure the selected ROIs over every layer, frame and channel in scope."""
        active_layer = self.patari_controller.active_recon_layer
        if active_layer is None:
            logger.info("Select an image layer to save ROI stats")
            return pd.DataFrame()

        frame_channel = selected_frame_and_channel(self.viewer)
        if frame_channel is None or np.asarray(active_layer.data).ndim < 2:
            logger.info("Active layer has no frame/channel dimensions")
            return pd.DataFrame()
        frame_idx, channel_idx = frame_channel

        all_layers, all_frames, all_channels = self._save_scope()
        follow_track = all_frames and self._follow_track_across_frames()
        target_layers = (
            [
                layer
                for layer in self.viewer.layers
                if isinstance(layer, Image) and layer.metadata.get("type") == "pa"
            ]
            if all_layers
            else [active_layer]
        )

        tracks = self._track_histories_for_selection(selected_ids)

        collected: list[pd.DataFrame] = []
        for layer in target_layers:
            layer_data = np.asarray(layer.data)
            if layer_data.ndim < 2:
                continue

            frames_meta = getattr(layer, "metadata", {}).get("frames")
            frame_indices = (
                [int(f) for f in frames_meta or range(layer_data.shape[0])]
                if all_frames
                else [frame_idx]
            )
            channel_indices = (
                list(range(layer_data.shape[1]))
                if all_layers or all_channels
                else [channel_idx]
            )

            for f_idx in frame_indices:
                records_here = self._records_at_frame(tracks, f_idx, follow_track=follow_track)
                for c_idx in channel_indices:
                    measured = compute_roi_stats(
                        records_here,
                        layer,
                        f_idx,
                        c_idx,
                        clamp=self.intensity_clamp,
                    )
                    if not measured.empty:
                        collected.append(measured)

        return (
            pd.concat(collected, ignore_index=True) if collected else pd.DataFrame()
        )

    def _append_saved_rows(self, rows: pd.DataFrame, *, n_rois: int) -> None:
        """Append measured rows and report anything measured a second time.
        TODO: is this desired, or should we rather fail / overwrite / prompt?
        """
        remeasured = self.saved_table.add_measurements(rows)
        self._set_saved_table_view()

        if remeasured:
            show_info(
                f"{len(remeasured)} ROI(s) already had earlier measurements. The new "
                f"rows were added alongside them; roi_ts tells them apart."
            )
        logger.info("Saved %s ROI(s) (%s total row(s))", n_rois, len(rows))

    def on_delete_saved_clicked(self, event=None) -> None:
        if self.patari_controller.roi is None:
            return

        selection_model = (
            self.patari_controller.roi.saved_table.native.selectionModel()
        )
        selected_rows = selection_model.selectedRows()
        selected_indices = [idx.row() for idx in selected_rows]
        if not selected_indices:
            logger.warning("No row selected to delete.")
            return

        deleted = self.saved_table.delete_at(selected_indices)
        self._set_saved_table_view()
        logger.info("Deleted %s saved rows", deleted)

    def on_xlsx_export_clicked(self, event=None) -> None:
        if self.patari_controller.roi is None:
            return

        filename = export_roi_table_to_xlsx(self.saved_table.rows)
        if filename is None:
            return

        show_info(f"Exported ROI table to {Path(filename).name}")
        logger.info("Saved ROI table to %s", filename)

    def on_import_clicked(self, event=None) -> None:
        """Append a previously exported table to the saved table.
        """
        if self.patari_controller.roi is None:
            return

        try:
            imported = import_roi_table_from_xlsx()
        except ValueError as exc:
            QMessageBox.warning(None, "Import failed", str(exc))
            return
        if imported is None:
            return

        rows, filename = imported
        added, skipped = self.saved_table.merge_imported(rows)
        self._set_saved_table_view()

        already = f", {skipped} already present" if skipped else ""
        show_info(f"Imported {added} row(s) from {Path(filename).name}{already}")
        logger.info("Imported %s of %s row(s) from %s", added, len(rows), filename)

    def on_saved_row_double_clicked(self, row: int, _column: int = 0) -> None:
        """Restore the ROI of the double-clicked row onto that row's frame."""
        if row >= len(self.saved_table):
            return
        self.on_restore_selected_rows(default_row=row)

    def on_restore_selected_rows(self, default_row: int | None = None) -> None:
        """Put the selected saved rows back into the viewer, one ROI per row.
        Restoring is per row, not per ROI group
        """
        selection = self.patari_controller.roi.saved_table.native.selectionModel()
        positions = [index.row() for index in selection.selectedRows()]
        if not positions and default_row is not None:
            positions = [default_row]
        if not positions:
            logger.info("No row selected to restore.")
            return

        rows = self.saved_table.rows_at(positions)
        try:
            problem = self._saved_rows_match_current_context(rows)
            if problem:
                show_error(problem)
                return
            records = self._records_from_saved_rows(rows)
        except (ValueError, TypeError) as exc:
            show_error(f"Could not restore ROI: {exc}")
            return

        if not records:
            show_info("Already in the viewer.")
            return

        for record in records:
            self._roi_records[record.roi_id] = record

        self._go_to_frame(int(rows["frame"].min()))
        self.project_current_frame()
        self.update_live_table()
        restored_ids = {r.roi_id for r in records}
        self.patari_controller.shapes_layer.selected_data = {
            index
            for index, roi_id in enumerate(self._projection_ids)
            if roi_id in restored_ids
        }
        show_info(f"Restored {len(records)} ROI(s)")

    def _saved_rows_match_current_context(self, rows: pd.DataFrame) -> str | None:
        """Refuse restoring a ROI row unless the exact scan, layer and frames the rows were measured on are loaded.
        """
        layer = self.patari_controller.active_recon_layer
        if layer is None:
            return "Select an image layer before restoring an ROI."

        scans = set(rows["scan_name"].astype(str))
        current_scan = str(layer.metadata.get("scan_name", ""))
        if scans != {current_scan}:
            return (
                f"That ROI was measured on scan '{', '.join(sorted(scans))}', "
                f"but '{current_scan}' is loaded."
            )

        layers = set(rows["src_layer"].astype(str))
        if layers != {str(layer.name)}:
            return (
                f"That ROI was measured on layer '{', '.join(sorted(layers))}', "
                f"but '{layer.name}' is selected."
            )

        n_frames = self._n_frames()
        if not rows["frame"].astype(int).between(0, n_frames - 1).all():
            return f"That ROI references frames outside this scan's {n_frames} frame(s)."
        return None

    def _records_from_saved_rows(self, rows: pd.DataFrame) -> list[ROIRecord]:
        """Rebuild one record per frame present in *rows*.

        *rows* is an arbitrary selection from the Saved table. Enter can restore a
        selection spanning several distinct ROIs at once, so grouping by
        ``roi_group_uid`` first . Within one group, group by ``frame`.
        The uid is carried through. ``roi_id`` and ``track_id`` are
        session-local counters, but a restored ROI must stay groupable with the
        measurements it came from, and with a group restored incrementally across
        several separate actions (see ``track_ids`` below).
        """
        layer = self.patari_controller.active_recon_layer
        fov_x_m, fov_y_m = layer_fov_m(layer, layer.data.shape[-2:])
        # Restoring one frame of a track must not block restoring its other frames,
        # so an ROI already in the viewer is identified by group *and* frame.
        present = {
            (record.roi_group_uid, record.frame_id)
            for record in self._roi_records.values()
        }
        track_ids: dict[str, int] = {
            record.roi_group_uid: record.track_id
            for record in self._roi_records.values()
        }

        records: list[ROIRecord] = []
        for roi_group_uid, group in rows.groupby("roi_group_uid"):
            roi_group_uid = str(roi_group_uid)
            # Rejoin the group already in the viewer, if any, so frames restored
            # separately still belong together.
            if roi_group_uid not in track_ids:
                track_ids[roi_group_uid] = self._next_track_id
                self._next_track_id += 1
            track_id = track_ids[roi_group_uid]
            for frame, frame_rows in group.groupby("frame"):
                if (roi_group_uid, int(frame)) in present:
                    continue
                geometry = RoiGeometry.from_json(str(frame_rows.iloc[0]["roi_geometry"]))
                records.append(
                    geometry.to_record(
                        roi_id=self._next_roi_id,
                        track_id=track_id,
                        frame_id=int(frame),
                        roi_group_uid=roi_group_uid,
                        fov_x_m=fov_x_m,
                        fov_y_m=fov_y_m,
                    )
                )
                self._next_roi_id += 1
        return records

    def _go_to_frame(self, frame_idx: int) -> None:
        dims = self.viewer.dims
        dims.current_step = (int(frame_idx), *dims.current_step[1:])

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
        self._update_remove_roi_preset_button_state()

    def _update_remove_roi_preset_button_state(self) -> None:
        """Update remove-preset button enabled state based on the current list selection."""
        if self.patari_controller.annotation is None:
            return
        ann = self.patari_controller.annotation
        ann.remove_roi_preset_button.setEnabled(ann.roi_presets_list.currentItem() is not None)

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
        roi_id, description, tissue_class = metadata

        fov_m = self.patari_controller._get_fov()
        if fov_m is None:
            self.patari_controller.annotation.roi_presets_description_label.setText(
                "Could not save ROI preset: current scan has no valid FOV."
            )
            return
        geometry = RoiGeometry(
            verts_m=napari_to_patato(verts[:, -2:], *fov_m),
            kind=shape_type,
            tissue_class=str(tissue_class or "undefined"),
        )
        try:
            preset_path = self._roi_preset_store.save_preset(
                name=roi_id,
                description=str(description or ""),
                geometry=geometry,
                source_fov_m=fov_m,
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
        tissue_class = preset.geometry.tissue_class.strip()
        if not tissue_class or tissue_class == "undefined":
            return "static"

        result = self.patari_controller.segmentation_ctrl.active_seg_mask_2d()
        if result is None:
            return "static"

        seg, seg_layer = result
        class_names = (seg_layer.metadata or {}).get("class_names", {})
        class_name_to_id = {
            str(name).strip(): int(class_id) for class_id, name in class_names.items()
        }

        if tissue_class not in class_name_to_id:
            return "static"

        class_id = class_name_to_id[tissue_class]
        return "auto" if np.any(seg == int(class_id)) else "static"

    @staticmethod
    def _place_roi_preset_static(controller, preset) -> None:
        """Place a preset while preserving its physical size across FOVs."""
        target_fov = controller._get_fov()
        if target_fov is None:
            raise ValueError("Current scan has no valid FOV.")

        geometry = preset.geometry.repositioned(preset.source_fov_m, target_fov)
        verts = geometry.verts_mm(*target_fov)
        if (
            np.any(verts[:, 0] < 0)
            or np.any(verts[:, 0] > target_fov[1] * 1000)
            or np.any(verts[:, 1] < 0)
            or np.any(verts[:, 1] > target_fov[0] * 1000)
        ):
            raise ValueError("ROI preset does not fit in the target FOV.")

        controller.shapes_layer.add(verts, shape_type=geometry.kind)
        # Auto-select the newly placed ROI so the Save button activates immediately.
        new_idx = len(controller.shapes_layer.data) - 1
        controller.shapes_layer.selected_data = {new_idx}

    @staticmethod
    def _place_roi_preset_auto(controller, preset) -> tuple[Labels, int] | None:
        """Place a saved ROI by aligning it to the selected segmentation class.

        Returns the segmentation layer and class id used, so a caller that's
        about to expand this to every frame (`_per_frame_auto_resolver`) can
        re-anchor onto each frame's own mask instead of re-resolving "current
        frame" a second time. None means placement failed; a message box
        already explains why.
        """
        result = controller.segmentation_ctrl.active_seg_mask_2d()
        if result is None:
            QMessageBox.critical(
                None, "Auto ROI",
                "No segmentation mask found. Generate segmentation first.",
            )
            return None

        seg, seg_layer = result
        class_names = (seg_layer.metadata or {}).get("class_names", {})
        class_name_to_id = {
            str(name): int(class_id) for class_id, name in class_names.items()
        }

        target_class_name = preset.geometry.tissue_class.strip()
        if target_class_name not in class_name_to_id:
            QMessageBox.critical(
                None, "Auto ROI",
                f"ROI tissue class '{target_class_name}' not found in segmentation classes.",
            )
            return None
        class_id = class_name_to_id[target_class_name]

        target_fov = controller._get_fov()
        if target_fov is None:
            raise ValueError("Current scan has no valid FOV.")
        verts = preset.geometry.verts_mm(*target_fov)

        try:
            verts_shifted = RoiController._anchor_verts_to_mask(
                verts, seg == class_id, seg_layer
            )
        except ValueError as exc:
            QMessageBox.critical(None, "Auto ROI", f"Class '{target_class_name}': {exc}")
            return None

        controller.shapes_layer.add(verts_shifted, shape_type=preset.geometry.kind)
        # Auto-select the newly placed ROI so the Save button activates immediately.
        new_idx = len(controller.shapes_layer.data) - 1
        controller.shapes_layer.selected_data = {new_idx}
        return seg_layer, class_id

    @staticmethod
    def _anchor_verts_to_mask(
        verts: np.ndarray, class_mask: np.ndarray, seg_layer: Labels
    ) -> np.ndarray:
        """Shift `verts` so their top-center sits on `class_mask`'s top-center.

        Raises ValueError (message safe to show the user) if the class isn't
        present in `class_mask` at all, or not at the image's horizontal centre.
        """
        if not np.any(class_mask):
            raise ValueError("not present in this frame")
        y_min = float(np.min(verts[:, 0]))
        x_min = float(np.min(verts[:, 1]))
        x_max = float(np.max(verts[:, 1]))
        source_center_x = 0.5 * (x_min + x_max)

        # isolate the largest connected component before anchoring
        # TODO: necessary? If we always do that as mask postprocessing anyways
        top_row, center_col = class_top_at_center_column(class_mask)

        sy = float(seg_layer.scale[-2])
        sx = float(seg_layer.scale[-1])
        ty = float(seg_layer.translate[-2])
        tx = float(seg_layer.translate[-1])

        dy = ty + float(top_row) * sy - y_min
        dx = tx + float(center_col) * sx - source_center_x
        return verts + np.asarray([dy, dx], dtype=float)

    def _per_frame_auto_resolver(
        self, seg_layer: Labels, class_id: int
    ) -> Callable[[int, np.ndarray], np.ndarray | None]:
        """Per-frame geometry for auto placement across All Frames: re-anchors
        onto each frame's own segmentation mask, skipping (returning None for)
        a frame the class isn't present on there
        """
        seg_data = np.asarray(seg_layer.data)

        def resolve(frame_id: int, source_verts: np.ndarray) -> np.ndarray | None:
            if frame_id >= seg_data.shape[0]:
                return None
            try:
                return self._anchor_verts_to_mask(
                    source_verts, seg_data[frame_id, 0] == class_id, seg_layer
                )
            except ValueError:
                return None

        return resolve

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
            resolver = None
            if mode == "auto":
                placed = self._place_roi_preset_auto(self.patari_controller, preset)
                if placed is None:
                    return
                resolver = self._per_frame_auto_resolver(*placed)
            else:
                self._place_roi_preset_static(self.patari_controller, preset)
            if annotation.all_frames_radio.isChecked():
                self.expand_current_projection_to_all_frames(resolver)
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
        tissue_class = preset.geometry.tissue_class

        desc = (
            f"{desc} (tissue class: {tissue_class})"
            if desc
            else f"(tissue class: {tissue_class})"
        )
        self.patari_controller.annotation.roi_presets_description_label.setText(
            desc
        )

    def initialize_ui(self) -> None:
        """Initialize ROI preset controls and current ROI display state."""
        self._refresh_roi_presets_ui()
        self._set_saved_table_view()
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
