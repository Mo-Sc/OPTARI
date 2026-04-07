from __future__ import annotations

from pathlib import Path

import numpy as np
import patato as pat
from napari.layers import Image, Labels, Shapes
from napari.viewer import Viewer
from qtpy.QtWidgets import QFileDialog

from patari.config import (
    DEFAULT_PA_LAYER,
)
from patari.segmentation.segmenter import DummySegmenter
from patari.utils.misc import parse_float_input
from patari.widgets.info_dock import InfoDock
from patari.widgets.roi_dock import RoiDock
from patari.widgets.scan_browser_dock import ScanBrowserDock
from patari.widgets.annotation_dock import AnnotationDock
from patari.widgets.reconstruction_dock import ReconstructionDock
from patari.widgets.time_analysis_dock import TimeAnalysisDock
from patari.widgets.unmixing_dock import UnmixingDock
from patari.widgets.histogram_dock import HistogramDock
from patari.widgets.spectrum_dock import SpectrumDock
from patari.controllers.ui_manager import UiManager
from patari.controllers.scan_controller import ScanController
from patari.controllers.roi_controller import RoiController
from patari.controllers.segmentation_controller import SegmentationController
from patari.controllers.analysis_controller import AnalysisController


class PatariController:
    def __init__(
        self,
        viewer: Viewer,
        path: Path | None,
    ):
        self.viewer = viewer
        self.path = Path(path) if path is not None else Path()
        self.study_path: Path | None = (
            self.path if self.path.is_dir() else self.path.parent
        )

        self._scans: dict[Path, str] = {}
        self.pa_data: pat.PAData | None = None
        self._patato_objects: dict[str, pat.ImageSequence] = {}

        self.shapes_layer: Shapes | None = None
        self.active_layer: Image | None = None

        # --- left elements ---
        self.info: InfoDock | None = None
        # Info widget is the plugin-provided dock widget; controller does not dock it.

        # --- right elements ---
        self.scan_browser: ScanBrowserDock | None = None
        self.annotation: AnnotationDock | None = None
        self.unmixing: UnmixingDock | None = None
        self.reconstruction: ReconstructionDock | None = None
        self._scan_browser_dock_widget = None
        self._annotation_dock_widget = None
        self._unmixing_dock_widget = None
        self._reconstruction_dock_widget = None

        self.roi_intensity_min: float | None = None
        self.roi_intensity_max: float | None = None
        self.roi_intensity_mode: str | None = "clip"

        # segmentation
        self._segmenter = DummySegmenter()

        # -- bottom elements --
        self.roi: RoiDock | None = None
        self.time_analysis: TimeAnalysisDock | None = None
        self.histograms: HistogramDock | None = None
        self.spectrum: SpectrumDock | None = None
        self._roi_dock_widget = None
        self._time_analysis_dock_widget = None
        self._histograms_dock_widget = None
        self._spectrum_dock_widget = None

        self._setup_viewer()
        self._ensure_docks()
        self._connect_events()

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

    def _ensure_docks(self) -> None:
        UiManager.setup_docks(self)

    def _connect_events(self) -> None:
        UiManager.connect_events(self)

    def _connect_shapes_layer_events(self) -> None:
        if self.shapes_layer is None:
            return
        try:
            self.shapes_layer.events.data.disconnect(
                self._on_shapes_data_changed
            )
        except Exception:
            pass
        try:
            self.shapes_layer.events.data.connect(self._on_shapes_data_changed)
        except Exception:
            pass

    def _apply_roi_colors(self) -> None:
        RoiController.apply_roi_colors(self)

    def _apply_roi_labels(self) -> None:
        RoiController.apply_roi_labels(self)

    def _on_shapes_data_changed(self, event=None) -> None:
        RoiController.on_shapes_data_changed(self, event)

    # ---------------- scans / loading ----------------
    def _close_current_scan(self) -> None:
        ScanController.close_current_scan(self)

    def _reset_scan_state(self) -> None:
        ScanController.reset_scan_state(self)

    def _init_path(self, path: Path) -> None:
        ScanController.init_path(self, path)

    def set_scan_folder(self, folder: Path) -> None:
        ScanController.set_scan_folder(self, folder)

    def load_scan(self, scan_path: Path) -> None:
        ScanController.load_scan(self, scan_path)

    @staticmethod
    def _scan_key(scan_path: Path) -> str:
        return ScanController.scan_key(scan_path)

    @staticmethod
    def _scan_sort_key(scan_path: Path):
        return ScanController.scan_sort_key(scan_path)

    def _discover_scans(self, folder: Path) -> dict[Path, str]:
        return ScanController.discover_scans(folder)

    @property
    def wavelengths(self) -> "list[int] | None":
        """
        Wavelengths (nm) for the current scan
        """
        return ScanController.wavelengths(self)

    @property
    def timestamps(self) -> "np.ndarray | None":
        """
        Acquisition timestamps for the current scan
        Returns a 2-D ``np.ndarray`` of shape ``(n_frames, n_wavelengths)`` in
        seconds
        """
        return ScanController.timestamps(self)

    def _layers_from_pa_data(self) -> list[tuple]:
        return ScanController.layers_from_pa_data(self)

    def _get_fov(self) -> "tuple[float, float] | None":
        return ScanController.get_fov(self)

    def _init_shapes_from_scan(self) -> None:
        ScanController.init_shapes_from_scan(self)

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
        start_path = str(self.path if self.path.exists() else Path.cwd())

        dialog = QFileDialog(
            None,
            "Select folder or HDF5 scan",
            start_path,
        )
        # Allow selecting either a directory or a specific file.
        # dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.AnyFile)
        dialog.setNameFilters(
            [
                "HDF5 scans (*.hdf5 *.h5)",
                "All files (*)",
            ]
        )

        if not dialog.exec():
            return

        selected = dialog.selectedFiles()
        if not selected:
            return

        target = Path(selected[0])
        if target.is_dir():
            self.set_scan_folder(target)
            return

        if target.is_file():
            # Keep browser list in sync when opening a single scan.
            self.set_scan_folder(target.parent)
            scan_paths = list(self._scans.keys())
            try:
                idx = scan_paths.index(target)
                if self.scan_browser is not None:
                    self.scan_browser.scans_list.setCurrentRow(idx)
            except ValueError:
                self.load_scan(target)

    def on_scan_selected(self, row: int) -> None:
        scan_paths = list(self._scans.keys())
        if row < 0 or row >= len(scan_paths):
            return
        self.load_scan(scan_paths[row])

    # ---------------- layer selection ----------------
    def _resolve_active_layer(self) -> None:
        """Set `active_layer` to the selected PA image layer (if exactly one is selected)."""

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
            # No-op if nothing changed (avoids duplicate work/logging).
            if self.active_layer is selected_layer:
                return

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

    def _on_roi_intensity_settings_changed(self) -> None:
        if self.annotation is None:
            return

        if self.annotation.roi_exclusion_box.isChecked():
            self.roi_intensity_mode = "exclude"
            self.roi_intensity_min = parse_float_input(
                self.annotation.roi_exclude_min_edit.text()
            )
            self.roi_intensity_max = parse_float_input(
                self.annotation.roi_exclude_max_edit.text()
            )
        elif self.annotation.roi_clipping_box.isChecked():
            self.roi_intensity_mode = "clip"
            self.roi_intensity_min = parse_float_input(
                self.annotation.roi_clip_min_edit.text()
            )
            self.roi_intensity_max = parse_float_input(
                self.annotation.roi_clip_max_edit.text()
            )
        else:
            self.roi_intensity_mode = None
            self.roi_intensity_min = None
            self.roi_intensity_max = None
        self.update_live_table()

    # ---------------- segmentation ----------------
    def _resolve_us_layer(self) -> Image | None:
        return SegmentationController.resolve_us_layer(self)

    def _us_slice_2d(self, us_layer: Image) -> np.ndarray | None:
        return SegmentationController.us_slice_2d(self, us_layer)

    def _set_roi_class_choices(self, class_names: dict[int, str]) -> None:
        SegmentationController.set_roi_class_choices(self, class_names)

    def _select_roi_class_by_name(self, class_name: str) -> None:
        SegmentationController.select_roi_class_by_name(self, class_name)

    def on_roi_preset_clicked(self, button) -> None:
        SegmentationController.on_roi_preset_clicked(self, button)

    def on_generate_tissue_segmentation_clicked(self) -> None:
        SegmentationController.on_generate_tissue_segmentation_clicked(self)

    def on_place_roi_clicked(self) -> None:
        SegmentationController.on_place_roi_clicked(self)

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
        AnalysisController.on_generate_time_analysis_clicked(self, event)

    # ---------------- histograms ----------------
    def on_refresh_histograms_clicked(self, event=None) -> None:
        AnalysisController.on_refresh_histograms_clicked(self, event)

    # ---------------- spectrum ----------------
    def on_refresh_spectrum_clicked(self, event=None) -> None:
        AnalysisController.on_refresh_spectrum_clicked(self, event)

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

        ts = self.timestamps
        if ts is None:
            return "N/A", 0.0

        if frame_idx >= ts.shape[0] or wav_idx >= ts.shape[1]:
            return "N/A", 0.0

        ts_seconds = ts[frame_idx, wav_idx]
        ts_start_seconds = ts[0, 0]

        # iThera uses .NET DateTime ticks
        try:
            from datetime import datetime, timedelta

            dt = datetime(1, 1, 1) + timedelta(seconds=float(ts_seconds))
        except Exception as e:
            print(
                "DEBUG: timestamp_for_slice: failed to convert timestamp to datetime:",
                e,
            )
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

        wavelengths = self.wavelengths
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
        study_str = (
            str(self.study_path.stem)
            if getattr(self, "study_path", None)
            else "N/A"
        )
        self.info.label.setText(
            f"Study: {study_str} | Scan: {scan_str}\n"
            f"Layer: {self.active_layer.name}\n"
            f"Frame: {frame_idx} | Wavelength: {wav_label}\n"
            f"Timestamp: {ts} ({ts_delta:.2f} s)"
        )

    def update_live_table(self, event=None) -> None:
        RoiController.update_live_table(self, event)

    # ---------------- table helpers ----------------
    @staticmethod
    def _table_value_to_df(table: object):
        return RoiController.table_value_to_df(table)

    # ---------------- button callbacks ----------------
    def on_save_clicked(self, event=None) -> None:
        RoiController.on_save_clicked(self, event)

    def on_delete_saved_clicked(self, event=None) -> None:
        RoiController.on_delete_saved_clicked(self, event)

    def on_csv_export_clicked(self, event=None) -> None:
        RoiController.on_csv_export_clicked(self, event)

    def on_hdf5_export_clicked(self, event=None) -> None:
        destination = self._choose_export_path()
        if destination is None:
            return
        ScanController.export_hdf5(self, destination)

    def _choose_export_path(self) -> Path | None:
        if self.pa_data is None:
            print("PATARI: no scan loaded")
            return None

        default_name = (
            f"{Path(self.path).stem}.hdf5"
            if getattr(self, "path", None)
            else "export.hdf5"
        )
        filename, _ = QFileDialog.getSaveFileName(
            None,
            "Export scan as HDF5",
            str(
                (
                    Path(self.path).parent
                    if getattr(self, "path", None)
                    else Path.cwd()
                )
                / default_name
            ),
            "HDF5 files (*.hdf5 *.h5)",
        )
        if not filename:
            return None
        return Path(filename)
