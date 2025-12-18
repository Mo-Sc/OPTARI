from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from napari.layers import Image, Shapes
from napari.viewer import Viewer
from qtpy.QtGui import QColor
from qtpy.QtWidgets import QFileDialog
import pyqtgraph as pg


from patari.config import (
    DEFAULT_FRAME_START_IDX,
    DEFAULT_WAV_START_IDX,
    dtype_map,
    ROI_LABELS,
    DEFAULT_PA_LAYER,
)
from patari.roi_utils import (
    compute_roi_stats,
    compute_roi_time_series,
    extract_roi_pixels_for_slice,
)
from patari.utils.misc import parse_float_input, roi_color_for_index

# from patari.utils.napari_layers import resolve_active_image_layer
from patari.widgets.info_dock import InfoDock, create_info_dock
from patari.widgets.roi_dock import RoiDock, create_roi_dock
from patari.widgets.scan_browser_dock import (
    ScanBrowserDock,
    create_scan_browser_dock,
)
from patari.widgets.annotation_dock import (
    AnnotationDock,
    create_annotation_dock,
)
from patari.widgets.time_analysis_dock import (
    TimeAnalysisDock,
    create_time_analysis_dock,
)
from patari.widgets.histogram_dock import HistogramDock, create_histogram_dock


class PatariController:
    def __init__(
        self,
        viewer: Viewer,
        path: Path | None,
        *,
        reader,
    ):
        self.viewer = viewer
        self.path = Path(path) if path is not None else Path()
        self.reader = reader

        self._scan_paths: list[Path] = []

        self.shapes_layer: Shapes | None = None
        self.active_layer: Image | None = None

        # --- left elements ---
        self.info: InfoDock | None = None

        # --- right elements ---
        self.scan_browser: ScanBrowserDock | None = None
        self.annotation: AnnotationDock | None = None

        self.roi_intensity_min: float | None = None
        self.roi_intensity_max: float | None = None

        # -- bottom elements --
        self.roi: RoiDock | None = None
        self.time_analysis: TimeAnalysisDock | None = None
        self.histograms: HistogramDock | None = None
        self._roi_dock_widget = None
        self._time_analysis_dock_widget = None
        self._histograms_dock_widget = None

        self._setup_viewer()
        self._ensure_shapes_layer()
        self._ensure_docks()
        self._connect_events()
        self._init_dims_point()

        # If a path is provided, populate scan browser / load scan.
        # Otherwise, the Scan Browser dock drives loading.
        if path is not None:
            self._init_path(self.path)
        elif self.scan_browser is not None:
            # Show an empty folder field instead of defaulting to '.'
            self.scan_browser.folder_lineedit.setText("")

        self.refresh_all()

    # ---------------- setup ----------------
    def _setup_viewer(self) -> None:
        self.viewer.axes.visible = True
        self.viewer.axes.labels = True
        self.viewer.grid.enabled = False
        self.viewer.scale_bar.visible = True
        self.viewer.scale_bar.unit = "mm"
        self.viewer.dims.axis_labels = ("Frame", "Wavelength", "z", "x")

    def _ensure_shapes_layer(self) -> None:
        if "ROIs" in self.viewer.layers and isinstance(
            self.viewer.layers["ROIs"], Shapes
        ):
            self.shapes_layer = self.viewer.layers["ROIs"]
            self._ensure_roi_on_top()
            return

        self.shapes_layer = self.viewer.add_shapes(
            name="ROIs",
            edge_color=roi_color_for_index(0),
            face_color="transparent",
            edge_width=0.1,
            ndim=2,
            metadata={"type": "roi"},
        )

        # this is not necessary if shape layer is initially empty
        # self._apply_roi_colors()
        # if ROI_LABELS:
        #     self._apply_roi_labels()
        self._ensure_roi_on_top()

    def _ensure_roi_on_top(self) -> None:
        """
        Necessary because ROI layer should persist across different scans and will therefore
        end up below newly added image layers. This ensures it is always on top.
        TODO: could be extended to full ordering: ROIs > PA images > US images
        """

        if self.shapes_layer is None:
            return
        try:
            self.shapes_layer.visible = True
        except Exception:
            pass

        # Keep ROIs above newly-added image layers.
        try:
            layers = self.viewer.layers
            idx = list(self.viewer.layers).index(self.shapes_layer)
            # Put ROIs at the very top of the stack.
            if idx != len(layers) - 1:
                layers.move(idx, len(layers))
        except Exception:
            print("PATARI: failed to move ROIs layer to top")
            pass

    def _ensure_docks(self) -> None:
        # Create docks once per controller instance.
        if self.scan_browser is None:
            self.scan_browser = create_scan_browser_dock()

        if self.info is None:
            self.info = create_info_dock()
            dock = self.viewer.window.add_dock_widget(
                self.info.widget,
                name="Info",
                area="left",
            )
            # in case info dock should be floating
            # dock.setFloating(True)
            # dock.show()

        if self.roi is None:
            self.roi = create_roi_dock()
            self._roi_dock_widget = self.viewer.window.add_dock_widget(
                self.roi.widget,
                name="Tabular",
                area="bottom",
            )

        if self.time_analysis is None:
            self.time_analysis = create_time_analysis_dock()
            self._time_analysis_dock_widget = (
                self.viewer.window.add_dock_widget(
                    self.time_analysis.widget,
                    name="Time Analysis",
                    area="bottom",
                )
            )

        if self.histograms is None:
            self.histograms = create_histogram_dock()
            self._histograms_dock_widget = self.viewer.window.add_dock_widget(
                self.histograms.widget,
                name="Histograms",
                area="bottom",
            )

        if self.annotation is None:
            self.annotation = create_annotation_dock()
            self.viewer.window.add_dock_widget(
                self.annotation.widget,
                name="Annotation",
                area="right",
            )

        # make sure ROI, Time Analysis and Histogram docks are tabified
        qt_window = getattr(self.viewer.window, "_qt_window", None)
        if qt_window is not None:
            qt_window.tabifyDockWidget(
                self._roi_dock_widget, self._time_analysis_dock_widget
            )
            qt_window.tabifyDockWidget(
                self._roi_dock_widget, self._histograms_dock_widget
            )

    def _connect_events(self) -> None:
        if self.shapes_layer is not None:
            self.shapes_layer.events.data.connect(self._on_shapes_data_changed)

        self.viewer.dims.events.point.connect(self.on_dims_changed)

        # TODO: should reordering / adding / removing layers trigger anything?
        # self.viewer.layers.events.reordered.connect(self.on_layers_changed)
        # self.viewer.layers.events.inserted.connect(self.on_layers_changed)
        # self.viewer.layers.events.removed.connect(self.on_layers_changed)
        self.viewer.layers.selection.events.changed.connect(
            self.on_selection_changed
        )

        if self.roi is not None:
            self.roi.save_button.clicked.connect(self.on_save_clicked)
            self.roi.delete_button.clicked.connect(
                self.on_delete_saved_clicked
            )
            self.roi.csv_button.clicked.connect(self.on_csv_export_clicked)

        if self.time_analysis is not None:
            self.time_analysis.generate_button.clicked.connect(
                self.on_generate_time_analysis_clicked
            )

        if self.histograms is not None:
            self.histograms.refresh_button.clicked.connect(
                self.on_refresh_histograms_clicked
            )

        if self.annotation is not None:
            # if roi min is edited
            self.annotation.roi_min_edit.editingFinished.connect(
                self._on_roi_intensity_settings_changed
            )
            # if roi max is edited
            self.annotation.roi_max_edit.editingFinished.connect(
                self._on_roi_intensity_settings_changed
            )
            # required for reset via 'unset' clear button
            self.annotation.roi_min_edit.textChanged.connect(
                lambda t: (
                    self._on_roi_intensity_settings_changed()
                    if (t or "").strip() == ""
                    else None
                )
            )
            self.annotation.roi_max_edit.textChanged.connect(
                lambda t: (
                    self._on_roi_intensity_settings_changed()
                    if (t or "").strip() == ""
                    else None
                )
            )

        if self.scan_browser is not None:
            self.scan_browser.browse_button.clicked.connect(
                self.on_browse_folder_clicked
            )
            self.scan_browser.scans_list.currentRowChanged.connect(
                self.on_scan_selected
            )

    def _apply_roi_colors(self) -> None:
        """
        Assign distinct colors to each ROI shape based on its index.
        """
        if self.shapes_layer is None:
            return

        self.shapes_layer.edge_color = [
            roi_color_for_index(i) for i in range(len(self.shapes_layer.data))
        ]

    def _apply_roi_labels(self) -> None:
        """
        show ROI index labels next to shapes.
        TODO: this is a bit hacky
        """
        if self.shapes_layer is None:
            return

        try:
            props = dict(getattr(self.shapes_layer, "properties", {}) or {})
            props["roi_id"] = np.arange(len(self.shapes_layer.data), dtype=int)
            self.shapes_layer.properties = props
            # napari text supports formatting from properties.
            self.shapes_layer.text = {"string": "{roi_id}"}
            # self.shapes_layer.text.visible = True # default

        except Exception:
            print("PATARI: failed to apply ROI labels")
            pass

    def _on_shapes_data_changed(self, event=None) -> None:
        if self.shapes_layer is None:
            return

        self._apply_roi_colors()
        if ROI_LABELS:
            self._apply_roi_labels()

        self.update_live_table()

    # ---------------- scans / loading ----------------
    def _init_path(self, path: Path) -> None:
        if path.is_dir():
            self.set_scan_folder(path)
            return

        if path.is_file():
            self.load_scan(path)
            return

        # Not a real path yet (e.g. in tests). Leave UI usable.
        if self.scan_browser is not None:
            self.scan_browser.set_folder(path)

    def set_scan_folder(self, folder: Path) -> None:
        folder = Path(folder)
        self.path = folder
        self._scan_paths = sorted(
            folder.glob("Scan_*.hdf5"), key=lambda p: int(p.stem.split("_")[1])
        )

        if self.scan_browser is not None:
            self.scan_browser.set_folder(folder)
            self.scan_browser.set_scans(self._scan_paths)

        # Auto-select first scan if available.
        if self._scan_paths and self.scan_browser is not None:
            self.scan_browser.scans_list.setCurrentRow(0)

    def load_scan(self, scan_path: Path) -> None:
        scan_path = Path(scan_path)
        self.path = scan_path

        # Remove existing data layers but keep ROI shapes and docks.
        self._clear_data_layers(keep_layers={self.shapes_layer})

        if not scan_path.exists():
            print(f"PATARI: scan not found: {scan_path}")
            self.refresh_all()
            return

        try:
            layers = self.reader(str(scan_path))
        except Exception as e:
            print(f"PATARI: failed to load '{scan_path}': {e}")
            self.refresh_all()
            return

        for data, kw, lt in layers:
            if lt == "image":
                kw = dict(kw)
                kw.setdefault("metadata", {})
                kw["metadata"].setdefault("filepath", str(scan_path))
                self.viewer.add_image(data, **kw)
            else:
                kw = dict(kw)
                kw.setdefault("metadata", {})
                kw["metadata"].setdefault("filepath", str(scan_path))
                self.viewer.add_labels(data, **kw)

        # After adding layers, pick a sensible default selected layer.
        self._select_default_pa_layer()
        self._ensure_roi_on_top()
        self._init_dims_point()

        # Fit view to the newly loaded data (prevents "zoomed out" state).
        try:
            self.viewer.reset_view()
        except Exception:
            pass
        self.refresh_all()

    def _clear_data_layers(self, keep_layers: set[object]) -> None:
        # Copy list of layers first (napari list is live).
        to_remove = []
        for layer in list(self.viewer.layers):
            if layer in keep_layers:
                continue
            # Prefer removing layers that look like PATARI data layers.
            layer_type = getattr(layer, "metadata", {}).get("type")
            if layer_type in {"pa", "us"}:
                to_remove.append(layer)
            # Also remove labels layers created by our reader.
            elif layer.__class__.__name__.lower().startswith("labels"):
                to_remove.append(layer)

        for layer in to_remove:
            try:
                self.viewer.layers.remove(layer)
            except Exception:
                pass

    def _select_default_pa_layer(self) -> None:

        # Find layer named DEFAULT_PA_LAYER, otherwise pick first PA layer found
        first_pa = None
        for layer in self.viewer.layers:
            if not isinstance(layer, Image):
                continue
            if layer.name == DEFAULT_PA_LAYER:
                self.viewer.layers.selection.select_only(layer)
                return
            if first_pa is None and layer.metadata.get("type") == "pa":
                first_pa = layer

        if first_pa is not None:
            self.viewer.layers.selection.select_only(first_pa)
            return

        raise RuntimeError(
            f"No PA image layer found (looking for '{DEFAULT_PA_LAYER}')"
        )

    def on_browse_folder_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            None,
            "Select folder with HDF5 scans",
            str(self.path if self.path.exists() else Path.cwd()),
        )
        if folder:
            self.set_scan_folder(Path(folder))

    def on_scan_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._scan_paths):
            return
        self.load_scan(self._scan_paths[row])

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
        """
        Docstring for _resolve_active_layer

        :param self: Description
        """

        selection = self.viewer.layers.selection

        if len(selection) != 1:
            # no layer selected or multiple layers selected
            return

        selected_layer = getattr(selection, "active", None)

        # only change active layer if selected layer is a PA image layer
        if (
            isinstance(selected_layer, Image)
            and selected_layer.metadata.get("type") == "pa"
        ):
            self.active_layer = selected_layer
            print(f"active layer set to {self.active_layer.name}")
            # keep PA layers visually consistent; show only the active PA layer
            # set all other PA layers to invisible
            # set blending and auto contrast for all PA layers
            for layer in self.viewer.layers:
                if (
                    isinstance(layer, Image)
                    and layer.metadata.get("type") == "pa"
                ):
                    layer.blending = "multiplicative"
                    layer._keep_auto_contrast = True
                    layer.visible = layer is self.active_layer

    # ---------------- events ----------------
    # def on_layers_changed(self, event=None) -> None:
    #     # TODO: relevant?
    #     self._ensure_roi_on_top()
    #     self.refresh_all()

    def _on_roi_intensity_settings_changed(self) -> None:
        if self.annotation is None:
            return

        self.roi_intensity_min = parse_float_input(
            self.annotation.roi_min_edit.text()
        )
        self.roi_intensity_max = parse_float_input(
            self.annotation.roi_max_edit.text()
        )
        self.update_live_table()

    def on_selection_changed(self, event=None) -> None:
        self._resolve_active_layer()
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

            self.refresh_all()

        except Exception as e:
            print("on_dims_changed:", e)

    # ---------------- time analysis ----------------
    def on_generate_time_analysis_clicked(self, event=None) -> None:

        error_msg = ""

        if self.shapes_layer is None:
            error_msg = "No ROIs layer"
        elif self.active_layer is None:
            error_msg = "Select a PA image layer"
        elif len(self.shapes_layer.data) == 0:
            error_msg = "No ROIs defined"
        elif len(self.active_layer.metadata["frames"]) < 2:
            error_msg = "PA image layer has less than 2 frames"

        if error_msg:
            self.time_analysis.status_label.setText(
                f'<span style="color:red">{error_msg}</span>'
            )
            if self.time_analysis.plot_widget is not None:
                self.time_analysis.plot_widget.clear()
            return

        # Lazily create plot widget.
        if self.time_analysis.plot_widget is None:
            plot = pg.PlotWidget()
            plot.showGrid(x=True, y=True)
            plot.addLegend()
            self.time_analysis.plot_widget = plot
            layout = self.time_analysis.plot_container.layout()
            if layout is not None:
                layout.addWidget(plot)

        plot = self.time_analysis.plot_widget
        assert plot is not None

        # Current wavelength index from dims.
        pt = list(self.viewer.dims.point)
        wav_idx = int(round(pt[1])) if len(pt) >= 2 else 0

        self.time_analysis.status_label.setText("Computing time series…")
        x, series = compute_roi_time_series(
            self.shapes_layer,
            self.active_layer,
            wav_idx,
            clamp_min=self.roi_intensity_min,
            clamp_max=self.roi_intensity_max,
        )

        plot.clear()

        plot.addLegend()

        for roi_index, y in series.items():
            color = roi_color_for_index(int(roi_index))
            plot.plot(
                x,
                y,
                pen=pg.mkPen(color=color, width=2),
                name=f"ROI {roi_index}",
            )

        xlabel = (
            "Time (s)"
            if self.active_layer.metadata.get("timestamps") is not None
            else "Frame"
        )
        plot.setLabel("bottom", xlabel)
        plot.setLabel("left", "Mean intensity")

        self.time_analysis.status_label.setText(
            f"Plotted {len(series)} ROI(s) over {len(x)} frame(s)."
        )

    # ---------------- histograms ----------------
    def on_refresh_histograms_clicked(self, event=None) -> None:
        if self.histograms is None:
            return
        if self.shapes_layer is None:
            self.histograms.status_label.setText("No ROIs layer")
            return
        if self.active_layer is None:
            self.histograms.status_label.setText("Select a PA image layer")
            return

        pt = list(self.viewer.dims.point)
        if len(pt) < 2:
            frame_idx, wav_idx = 0, 0
        else:
            frame_idx = int(round(pt[0]))
            wav_idx = int(round(pt[1]))

        self.histograms.status_label.setText("Computing histograms…")

        roi_vals = extract_roi_pixels_for_slice(
            self.shapes_layer,
            self.active_layer,
            frame_idx,
            wav_idx,
            clamp_min=self.roi_intensity_min,
            clamp_max=self.roi_intensity_max,
        )

        # Clear previous plots
        container = self.histograms.plots_container
        layout = container.layout()
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget() if item is not None else None
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()

        n_plotted = 0
        for roi_index, vals in roi_vals.items():
            vals = np.asarray(vals)
            if vals.size == 0:
                continue

            # Histogram bins: simple default.
            try:
                counts, edges = np.histogram(vals, bins=50)
            except Exception:
                continue

            if counts.size == 0 or edges.size < 2:
                continue

            x = (edges[:-1] + edges[1:]) / 2.0
            width = float(edges[1] - edges[0])

            color = roi_color_for_index(int(roi_index))
            brush = pg.mkBrush(color)
            pen = pg.mkPen(color)

            plot = pg.PlotWidget()
            plot.setTitle(f"ROI {roi_index}")
            plot.showGrid(x=True, y=True)
            bar = pg.BarGraphItem(
                x=x,
                height=counts,
                width=width,
                brush=brush,
                pen=pen,
            )
            plot.addItem(bar)

            if layout is not None:
                layout.addWidget(plot)
            n_plotted += 1

        self.histograms.status_label.setText(
            f"Plotted {n_plotted} histogram(s) for frame {frame_idx}, wav {wav_idx}."
        )

    # ---------------- info/roi updates ----------------
    def refresh_all(self) -> None:
        """
        refresh all info that should be live updated
        """
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
        scan_str = (
            str(self.path.stem) if getattr(self, "path", None) else "N/A"
        )
        self.info.label.setText(
            f"Scan: {scan_str}\n"
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
                clamp_min=self.roi_intensity_min,
                clamp_max=self.roi_intensity_max,
            )
        except Exception as e:
            print("update_live_table:", e)
            df = pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)

        self.roi.live_table.value = df

        # Keep shapes layer colors in sync with indices.
        self._apply_roi_colors()

        # color first column cells background to match ROI colors
        num_shapes = len(self.shapes_layer.data)
        for row_idx in range(num_shapes):
            item = self.roi.live_table.native.item(row_idx, 0)
            if item is not None:
                item.setBackground(QColor(roi_color_for_index(row_idx)))

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
        # TODO: export all data
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
