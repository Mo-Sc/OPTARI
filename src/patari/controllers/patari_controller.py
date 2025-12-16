from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from napari.layers import Image, Shapes
from napari.viewer import Viewer
from qtpy.QtGui import QColor
from qtpy.QtWidgets import QFileDialog

from patari.config import (
    DEFAULT_FRAME_START_IDX,
    DEFAULT_WAV_START_IDX,
    dtype_map,
    roi_colors,
)
from patari.roi_utils import compute_roi_stats
from patari.utils.napari_layers import resolve_active_image_layer
from patari.widgets.info_dock import InfoDock, create_info_dock
from patari.widgets.roi_dock import RoiDock, create_roi_dock


class PatariController:
    def __init__(
        self,
        viewer: Viewer,
        path: Path,
        *,
        reader,
    ):
        self.viewer = viewer
        self.path = Path(path)
        self.reader = reader

        self.info: InfoDock | None = None
        self.roi: RoiDock | None = None

        self.shapes_layer: Shapes | None = None
        self.active_layer: Image | None = None

        self._setup_viewer()
        self._maybe_load_layers()
        self._ensure_shapes_layer()
        self._ensure_docks()
        self._connect_events()
        self._init_dims_point()

        self.refresh_all()

    # ---------------- setup ----------------
    def _setup_viewer(self) -> None:
        self.viewer.axes.visible = True
        self.viewer.axes.labels = True
        self.viewer.grid.enabled = False
        self.viewer.scale_bar.visible = True
        self.viewer.scale_bar.unit = "mm"
        self.viewer.dims.axis_labels = ("Frame", "Wavelength", "z", "x")

    def _maybe_load_layers(self) -> None:
        if len(self.viewer.layers) > 0:
            return

        try:
            layers = self.reader(str(self.path))
        except Exception as e:
            # Keep the UI usable even if the provided path is invalid.
            print(f"PATARI: failed to load '{self.path}': {e}")
            return
        for data, kw, lt in layers:
            if lt == "image":
                kw = dict(kw)
                kw.setdefault("metadata", {})
                self.viewer.add_image(data, **kw)
            else:
                self.viewer.add_labels(data, **kw)

    def _ensure_shapes_layer(self) -> None:
        if "ROIs" in self.viewer.layers and isinstance(
            self.viewer.layers["ROIs"], Shapes
        ):
            self.shapes_layer = self.viewer.layers["ROIs"]
            return

        self.shapes_layer = self.viewer.add_shapes(
            name="ROIs",
            edge_color="#aa0000ff",
            face_color="transparent",
            edge_width=0.2,
            ndim=2,
            metadata={"type": "roi"},
        )

    def _ensure_docks(self) -> None:
        # Create docks once per controller instance.
        if self.info is None:
            self.info = create_info_dock()
            self.viewer.window.add_dock_widget(
                self.info.widget,
                name="Info",
                area="right",
            )

        if self.roi is None:
            self.roi = create_roi_dock()
            self.viewer.window.add_dock_widget(
                self.roi.widget,
                name="ROI Tables",
                area="bottom",
            )

    def _connect_events(self) -> None:
        if self.shapes_layer is not None:
            self.shapes_layer.events.data.connect(self.update_live_table)

        self.viewer.dims.events.point.connect(self.on_dims_changed)
        self.viewer.layers.events.reordered.connect(self.on_layers_changed)
        self.viewer.layers.events.inserted.connect(self.on_layers_changed)
        self.viewer.layers.events.removed.connect(self.on_layers_changed)

        # selection change (preferred for selected-layer rule)
        try:
            self.viewer.layers.selection.events.changed.connect(
                self.on_selection_changed
            )
        except Exception:
            # older napari or different event model
            pass

        if self.roi is not None:
            self.roi.save_button.clicked.connect(self.on_save_clicked)
            self.roi.delete_button.clicked.connect(
                self.on_delete_saved_clicked
            )
            self.roi.csv_button.clicked.connect(self.on_csv_export_clicked)

    def _init_dims_point(self) -> None:
        # Only set if viewer has at least 2 dims (frame/wavelength)
        try:
            pt = list(self.viewer.dims.point)
        except Exception:
            return

        if len(pt) < 2:
            return

        pt[0] = DEFAULT_FRAME_START_IDX
        pt[1] = DEFAULT_WAV_START_IDX
        self.viewer.dims.point = tuple(pt)

    # ---------------- layer selection ----------------
    def _resolve_active_layer(self) -> None:
        res = resolve_active_image_layer(self.viewer, require_pa=True)
        self.active_layer = res.layer if res is not None else None

        # keep PA layers visually consistent; show only the active PA layer
        for layer in self.viewer.layers:
            if isinstance(layer, Image) and layer.metadata.get("type") == "pa":
                layer.blending = "multiplicative"
                layer._keep_auto_contrast = True
                layer.visible = layer is self.active_layer

    # ---------------- events ----------------
    def on_layers_changed(self, event=None) -> None:
        self.refresh_all()

    def on_selection_changed(self, event=None) -> None:
        self.refresh_all()

    def on_dims_changed(self, event=None) -> None:
        # snap frames for sparse recon and refresh
        try:
            pt = list(self.viewer.dims.point)
            if len(pt) < 2:
                return

            frame_idx = int(round(pt[0]))
            snapped = self.snap_to_reconstructed_frame(frame_idx)
            if snapped != frame_idx:
                self.viewer.dims.set_point(0, snapped)
                return

            # Scrolling dims should not re-resolve the active layer or toggle
            # layer visibility; that work is selection-dependent and can be
            # expensive. Only update the dims-dependent UI.
            # (no refresh_all call)
            self.update_info_labels()
            self.update_live_table()
        except Exception as e:
            print("on_dims_changed:", e)

    # ---------------- info/roi updates ----------------
    def refresh_all(self) -> None:
        self._resolve_active_layer()
        self.update_info_labels()
        self.update_live_table()

    def snap_to_reconstructed_frame(self, frame_idx: int) -> int:
        if self.active_layer is None:
            return frame_idx
        frames = self.active_layer.metadata.get("frames", None)
        if not frames:
            return frame_idx
        frames = np.asarray(frames, dtype=int)
        return int(frames[np.argmin(np.abs(frames - frame_idx))])

    def timestamp_for_slice(self, frame_idx: int, wav_idx: int):
        if self.active_layer is None:
            return "N/A", 0.0

        ts = self.active_layer.metadata.get("timestamps")
        if ts is None:
            return "N/A", 0.0

        if frame_idx >= ts.shape[0] or wav_idx >= ts.shape[1]:
            return "N/A", 0.0

        ts_seconds = ts[frame_idx, wav_idx]
        ts_start_seconds = ts[0, 0]

        # iThera uses .NET DateTime ticks sometimes; your data seems to already
        # be in seconds. Keep display conservative.
        try:
            from datetime import datetime, timedelta

            dt = datetime(1, 1, 1) + timedelta(seconds=float(ts_seconds))
        except Exception:
            dt = "N/A"

        return dt, float(ts_seconds) - float(ts_start_seconds)

    def update_info_labels(self, event=None) -> None:
        if self.info is None:
            return
        if self.active_layer is None:
            self.info.label.setText("Select a PA image layer")
            return

        pt = list(self.viewer.dims.point)
        if len(pt) < 2:
            self.info.label.setText(f"Layer: {self.active_layer.name}")
            return

        frame_idx = int(round(pt[0]))
        wav_idx = int(round(pt[1]))

        wavelengths = self.active_layer.metadata.get("wavelengths")
        wav_label = (
            f"{wavelengths[wav_idx]} nm"
            if isinstance(wavelengths, (list, tuple))
            and 0 <= wav_idx < len(wavelengths)
            else str(wav_idx)
        )

        frames = self.active_layer.metadata.get("frames")
        is_reconstructed = frames is None or frame_idx in frames
        frame_label = (
            f"Frame: {frame_idx} (reconstructed)"
            if is_reconstructed
            else f"Frame: {frame_idx} (missing)"
        )

        self.viewer.dims.axis_labels = (
            frame_label,
            f"Wavelength: {wav_label}",
            "z",
            "x",
        )

        ts, ts_delta = self.timestamp_for_slice(frame_idx, wav_idx)
        self.info.label.setText(
            f"Layer: {self.active_layer.name}\n"
            f"Frame: {frame_idx}\n"
            f"Timestamp: {ts} ({ts_delta:.2f} s)\n"
            f"Wavelength: {wav_label}"
        )

    def update_live_table(self, event=None) -> None:
        if self.roi is None or self.shapes_layer is None:
            return

        if self.active_layer is None:
            self.roi.live_table.value = pd.DataFrame(
                columns=list(dtype_map.keys())
            ).astype(dtype_map)
            return

        pt = list(self.viewer.dims.point)
        if len(pt) < 2:
            return

        frame_idx = int(round(pt[0]))
        wav_idx = int(round(pt[1]))

        try:
            df = compute_roi_stats(
                self.shapes_layer,
                self.active_layer,
                frame_idx,
                wav_idx,
            )
        except Exception as e:
            print("update_live_table:", e)
            df = pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)

        self.roi.live_table.value = df

        # color ROIs in shapes layer to distinct colors
        num_shapes = len(self.shapes_layer.data)
        colors_for_shapes = [
            roi_colors[i % len(roi_colors)] for i in range(num_shapes)
        ]
        self.shapes_layer.edge_color = colors_for_shapes

        # color first column cells background to match colors
        for row_idx, color_hex in enumerate(colors_for_shapes):
            item = self.roi.live_table.native.item(row_idx, 0)
            if item is not None:
                item.setBackground(QColor(color_hex))

    # ---------------- table helpers ----------------
    @staticmethod
    def _table_value_to_df(table: object) -> pd.DataFrame:
        # magicgui Table.value is sometimes a DataFrame and sometimes dict-like
        val = getattr(table, "value", table)
        if isinstance(val, pd.DataFrame):
            return val
        if isinstance(val, dict) and "data" in val and "columns" in val:
            return pd.DataFrame(val["data"], columns=val["columns"])
        return pd.DataFrame()

    # ---------------- button callbacks ----------------
    def on_save_clicked(self, event=None) -> None:
        if self.roi is None or self.shapes_layer is None:
            return

        selected = self.shapes_layer.selected_data
        if len(selected) != 1:
            print("Select one ROI to save")
            return

        roi_idx = list(selected)[0]
        df_live = self._table_value_to_df(self.roi.live_table)
        if df_live.empty or roi_idx >= len(df_live):
            print("Nothing to save")
            return

        row = df_live.iloc[[roi_idx]].astype(dtype_map)

        df_saved = self._table_value_to_df(self.roi.saved_table)
        if df_saved.empty:
            df_saved = row.copy()
        else:
            df_saved = pd.concat([df_saved, row], ignore_index=True)

        self.roi.saved_table.value = df_saved.astype(dtype_map)
        print(f"Saved ROI {roi_idx}")

    def on_delete_saved_clicked(self, event=None) -> None:
        if self.roi is None:
            return

        selection_model = self.roi.saved_table.native.selectionModel()
        selected_rows = selection_model.selectedRows()
        selected_indices = [idx.row() for idx in selected_rows]
        if not selected_indices:
            print("No row selected to delete.")
            return

        df_saved = self._table_value_to_df(self.roi.saved_table)
        if df_saved.empty:
            return

        df_saved = df_saved.drop(selected_indices).reset_index(drop=True)
        self.roi.saved_table.value = df_saved.astype(dtype_map)
        print(f"Deleted {len(selected_indices)} saved rows")

    def on_csv_export_clicked(self, event=None) -> None:
        if self.roi is None:
            return

        df_saved = self._table_value_to_df(self.roi.saved_table).astype(
            dtype_map
        )
        if df_saved.empty:
            print("Saved table empty")
            return

        filename, _ = QFileDialog.getSaveFileName(
            None,
            "Save Saved ROIs as CSV",
            "saved_rois.csv",
            "CSV Files (*.csv)",
        )
        if not filename:
            return
        if not filename.endswith(".csv"):
            filename += ".csv"
        df_saved.to_csv(filename, index=False)
        print(f"Saved ROI table to {filename}")
