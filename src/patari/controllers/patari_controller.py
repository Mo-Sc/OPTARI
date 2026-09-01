from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import patato as pat # type: ignore
from napari.layers import Image, Shapes
from napari.viewer import Viewer

if TYPE_CHECKING:
    from napari.qt.threading import GeneratorWorker

from patari.utils.viewer import selected_frame_and_channel
from patari.widgets.info_dock import InfoDock
from patari.widgets.roi_dock import RoiDock
from patari.widgets.scan_browser_dock import ScanBrowserDock
from patari.controllers.scan_controller import ScanInfo
from patari.widgets.annotation_dock import AnnotationDock
from patari.widgets.reconstruction_dock import ReconstructionDock
from patari.widgets.time_analysis_dock import TimeAnalysisDock
from patari.widgets.unmixing_dock import UnmixingDock
from patari.widgets.histogram_dock import HistogramDock
from patari.widgets.spectrum_dock import SpectrumDock
from patari.widgets.layer_metadata_dialog import LayerMetadataDialog
from patari.controllers.ui_manager import UiManager
from patari.controllers.menu_manager import MenuManager
from patari.controllers.shortcut_manager import ShortcutManager
from patari.controllers.scan_controller import ScanController
from patari.controllers.roi_controller import RoiController
from patari.controllers.segmentation_controller import SegmentationController
from patari.controllers.analysis_controller import AnalysisController
from patari.controllers.unmixing_controller import UnmixingController
from patari.controllers.reconstruction_controller import ReconstructionController

from patari.config import settings

logger = logging.getLogger(__name__)


class PatariController:
    def __init__(self, viewer: Viewer):

        self.viewer = viewer
        # self.path = Path(path) if path is not None else Path()
        # self.study_path: Path | None = (
        #     self.path if self.path.is_dir() else self.path.parent
        # )

        self._scans: dict[Path, ScanInfo] = {}
        self.pa_data: pat.PAData | None = None
        self._patato_objects: dict[str, pat.ImageSequence] = {}
        self._derived_patato_objects: dict[str, pat.ImageSequence] = {}

        self.shapes_layer: Shapes | None = None
        self._last_frame_idx: int | None = None
        self.active_recon_layer: Image | None = None
        self.active_us_layer: Image | None = None
        self.active_task: GeneratorWorker | None = None

        # --- left elements ---
        self.info: InfoDock | None = None
        # Info widget is the plugin-provided dock widget; controller does not dock it.

        # --- right elements ---
        self.scan_browser: ScanBrowserDock | None = None
        self.annotation: AnnotationDock | None = None
        self.segmentation = None
        self.unmixing: UnmixingDock | None = None
        self.reconstruction: ReconstructionDock | None = None
        self._scan_browser_dock_widget = None
        self._annotation_dock_widget = None
        self._segmentation_dock_widget = None
        self._unmixing_dock_widget = None
        self._reconstruction_dock_widget = None


        self.scan_ctrl = ScanController(self)
        self.roi_ctrl = RoiController(self)
        self.segmentation_ctrl = SegmentationController(self)
        self.analysis_ctrl = AnalysisController(self)
        self.unmixing_ctrl = UnmixingController(self)
        self.reconstruction_ctrl = ReconstructionController(self)

        # Track event bindings for proper cleanup
        self._shapes_layer_bindings = []

        # -- bottom elements --
        self.roi: RoiDock | None = None
        self.time_analysis: TimeAnalysisDock | None = None
        self.histograms: HistogramDock | None = None
        self.spectrum: SpectrumDock | None = None
        self._roi_dock_widget = None
        self._time_analysis_dock_widget = None
        self._histograms_dock_widget = None
        self._spectrum_dock_widget = None

        self.settings_dialog = None

        self._setup_viewer()
        self._ensure_docks()
        self.setup_menu()
        self.roi_ctrl.initialize_ui()
        self.segmentation_ctrl.initialize_ui()
        self.unmixing_ctrl.initialize_ui()
        self.reconstruction_ctrl.initialize_ui()
        self.analysis_ctrl.refresh_ui()
        self.scan_ctrl.refresh_ui()
        self._connect_events()
        self.register_shortcuts()

        # If a path is provided, populate scan browser / load scan.
        # Otherwise, the Scan Browser dock drives loading.
        # if path is not None:
        #     self._init_path(self.path)
        if self.scan_browser is not None:
            # Show an empty folder field instead of defaulting to '.'
            self.scan_browser.folder_lineedit.setText("")

        self.refresh_all()

    def shutdown(self) -> None:
        """
        Properly clean up resources and disconnect all signals before shutdown.
        Should prevent segfaults on exit
        """
        if self.active_task is not None:
            self.active_task.quit()

        for controller in (
            self.scan_ctrl,
            self.roi_ctrl,
            self.analysis_ctrl,
            self.unmixing_ctrl,
            self.reconstruction_ctrl,
            self.segmentation_ctrl,
        ):
            try:
                controller.unbind_events()
                controller.teardown()
            except Exception:
                logger.exception("Error shutting down %s", type(controller).__name__)

        # Disconnect events
        try:
            self.viewer.dims.events.point.disconnect(self.on_dims_changed)
            self.viewer.layers.selection.events.changed.disconnect(
                self.on_selection_changed
            )
            for evt, handler in self._shapes_layer_bindings:
                evt.disconnect(handler)
        except Exception:
            logger.exception("Error disconnecting events during shutdown")

        # Close current scan to release file handles
        try:
            self._close_current_scan()
        except Exception:
            logger.exception("Error closing current scan during shutdown")

        # Clear references to break circular references
        self.pa_data = None
        self._patato_objects.clear()
        self._derived_patato_objects.clear()
        self.shapes_layer = None
        self.active_recon_layer = None
        self.active_us_layer = None

        # Clear widget references
        self.info = None
        self.scan_browser = None
        self.annotation = None
        self.segmentation = None
        self.unmixing = None
        self.reconstruction = None
        self.roi = None
        self.time_analysis = None
        self.histograms = None
        self.spectrum = None

        logger.info("PatariController: Shutdown complete")

    # ============ viewer setup ============
    def _setup_viewer(self) -> None:
        self.viewer.axes.visible = False # dont show axes by default
        self.viewer.axes.labels = True
        self.viewer.grid.enabled = False
        self.viewer.scale_bar.visible = True
        self.viewer.dims.axis_labels = ("Frame", "Channel", "z", "x")

    def _ensure_docks(self) -> None:
        UiManager.setup_docks(self)

    def _connect_events(self) -> None:
        UiManager.connect_events(self)

    def register_shortcuts(self) -> None:
        ShortcutManager.register_all(self)

    def setup_menu(self) -> None:
        MenuManager.setup(self)

    def _connect_shapes_layer_events(self) -> None:
        """
        Connects events for the shapes layer to the ROI controller. This includes data changes and selection changes.
        data changes mean ROIs were added/removed/replaced
        selection changes mean the active ROI set changed
        """
        if self.shapes_layer is None:
            return

        self._shapes_layer_bindings = [
            # Shapes layer data changes drive ROI table refresh, label updates, and formatting.
            (
                self.shapes_layer.events.data,
                self._on_shapes_data_changed
            ),
            # Shape copy/paste appends shapes without emitting events.data, so watch set_data too.
            (
                self.shapes_layer.events.set_data,
                self._on_shapes_set_data,
            ),
            # selected_data.items_changed is the selection signal for viewer -> table sync.
            (
                self.shapes_layer.selected_data.events.items_changed,
                self._on_shapes_selection_changed,
            ),
            # Live table itemSelectionChanged is signal for table -> viewer sync.
            (
                self.roi.live_table.native.itemSelectionChanged,
                self.roi_ctrl.on_live_table_selection_changed,
            ),
        ]

        # Disconnect and reconnect to avoid duplicate connections if this is called multiple times.
        for evt, handler in self._shapes_layer_bindings:
            try:
                evt.disconnect(handler)
            except Exception:
                pass

        for evt, handler in self._shapes_layer_bindings:
            evt.connect(handler)

    # ============ ROI layer management ============
    def _on_shapes_data_changed(self, event=None) -> None:
        self.roi_ctrl.on_shapes_data_changed(event)

    def _on_shapes_set_data(self, event=None) -> None:
        self.roi_ctrl.on_shapes_set_data(event)

    def _on_shapes_selection_changed(self, event=None) -> None:
        self.roi_ctrl.on_shapes_selection_changed(event)

    def _ensure_shapes_layer_on_top(self) -> None:
        """
        Moves ROI layer to top. Necessary because some operations (e.g. unmixing) add new image layers on top of the ROI layer
        ROI layer should always be on top of the layer stack to be visible and interactive.
        """
        if self.shapes_layer is None:
            return

        current_index = self.viewer.layers.index(self.shapes_layer)
        top_index = len(self.viewer.layers)
        if current_index != top_index:
            # Layer order defines draw order; top index renders above image layers.
            self.viewer.layers.move(current_index, top_index)
            logger.info("moved ROI layer to top index %s", top_index)

    # ============ scan loading ============
    def _close_current_scan(self) -> None:
        self.scan_ctrl.close_current_scan()

    def _init_path(self, path: Path) -> None:
        self.scan_ctrl.init_path(path)

    @property
    def task_running(self) -> bool:
        return self.active_task is not None

    def set_active_task(self, worker: GeneratorWorker | None) -> None:
        """Track the running background task and gate the UI around it.

        Only one heavy task at a time: while one runs, the other run buttons and the scan
        browser stay disabled.
        """
        self.active_task = worker
        self.refresh_controller_uis()

    def refresh_controller_uis(self) -> None:
        """Refresh all controller-owned UI after a state transition."""
        for controller in (
            self.scan_ctrl,
            self.roi_ctrl,
            self.analysis_ctrl,
            self.unmixing_ctrl,
            self.reconstruction_ctrl,
            self.segmentation_ctrl,
        ):
            controller.refresh_ui()

    @property
    def wavelengths(self) -> "list[int] | None":
        """
        Wavelengths (nm) for the current scan
        """
        return self.scan_ctrl.wavelengths()

    @property
    def timestamps(self) -> "np.ndarray | None":
        """
        Acquisition timestamps for the current scan
        Returns a 2-D ``np.ndarray`` of shape ``(n_frames, n_wavelengths)`` in
        seconds
        """
        return self.scan_ctrl.timestamps()

    def _get_fov(self) -> "tuple[float, float] | None":
        return self.scan_ctrl.get_fov()

    def _select_default_pa_layer(self) -> None:

        # Find layer default PA layer, otherwise pick first PA layer found
        first_pa = None
        default_pa = settings.general.DEFAULT_PA_LAYER
        for layer in self.viewer.layers:
            if not isinstance(layer, Image):
                continue
            if layer.name == default_pa:
                self.viewer.layers.selection.select_only(layer)
                return
            if first_pa is None and layer.metadata.get("type") == "pa":
                first_pa = layer

        if first_pa is not None:
            self.viewer.layers.selection.select_only(first_pa)
            return

        raise RuntimeError(
            f"No PA image layer found (looking for '{default_pa}')"
        )

    # ============ layer selection ============
    def _resolve_active_recon_layer(self) -> None:
        """Set `active_recon_layer` to the selected PA image layer (if exactly one is selected)."""

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
            if self.active_recon_layer is selected_layer:
                return

            self.active_recon_layer = selected_layer
            logger.info("active layer set to %s", self.active_recon_layer.name)
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
                    layer.visible = layer is self.active_recon_layer

    # ============ viewer events ============
    def on_selection_changed(self, event=None) -> None:
        self._resolve_active_recon_layer()
        self.unmixing_ctrl.refresh_ui()
        self.analysis_ctrl.refresh_ui()
        if self._snap_dims_to_active_layer():
            return
        self.refresh_all()

    def on_dims_changed(self, event=None) -> None:
        # snap dims to what is available in the selected PA layer
        try:
            if self._snap_dims_to_active_layer():
                return

            frame_idx = int(round(self.viewer.dims.point[0]))
            if frame_idx != self._last_frame_idx:
                self._last_frame_idx = frame_idx
                self.roi_ctrl.project_current_frame()

            self.refresh_all()

        except Exception:
            logger.exception("on_dims_changed failed")

    # ============ update everything ============
    def refresh_all(self) -> None:
        """
        refresh all info that should be live updated
        """
        self.update_info_labels()
        self.roi_ctrl.update_live_table()

    # ============ layer snappin & constraints ============
    def snap_to_reconstructed_frame(self, frame_idx: int) -> int:
        """
        snap the given frame index to the closest available frame in the active layer's metadata
        """
        if self.active_recon_layer is None:
            return frame_idx
        frames = self.active_recon_layer.metadata.get("frames", None)
        if not frames:
            return frame_idx
        frames = np.asarray(frames, dtype=int)
        return int(frames[np.argmin(np.abs(frames - frame_idx))])

    def snap_to_available_channel(self, channel_idx: int) -> int:
        """
        snap the given channel index to a valid channel index based on the active layer's metadata
        """
        if self.active_recon_layer is None:
            return channel_idx

        data = np.asarray(self.active_recon_layer.data)
        if data.ndim < 2:
            return 0

        n_channels = data.shape[1]
        return int(np.clip(channel_idx, 0, max(0, n_channels - 1)))

    def _snap_dims_to_active_layer(self) -> bool:
        if self.active_recon_layer is None:
            return False

        frame_channel = selected_frame_and_channel(self.viewer)
        if frame_channel is None:
            return False
        frame_idx, channel_idx = frame_channel

        snapped_frame = self.snap_to_reconstructed_frame(frame_idx)
        snapped_channel = self.snap_to_available_channel(channel_idx)

        changed = False
        # Enforce valid index support of the active layer to avoid sampling zero-padded channels.
        if snapped_frame != frame_idx:
            self.viewer.dims.set_point(0, snapped_frame)
            changed = True
        if snapped_channel != channel_idx:
            self.viewer.dims.set_point(1, snapped_channel)
            changed = True

        if changed:
            logger.info(
                "snapped dims for layer %s to frame=%s, channel=%s",
                self.active_recon_layer.name,
                snapped_frame,
                snapped_channel,
            )

        return changed

    # ============ timestamps & display ============
    def timestamp_for_slice(self, frame_idx: int, channel_idx: int):
        if self.active_recon_layer is None:
            return "N/A", 0.0

        ts = self.active_recon_layer.metadata.get("timestamps")
        if ts is not None:
            ts = np.asarray(ts)
        else:
            ts = self.timestamps
        if ts is None:
            return "N/A", 0.0

        if frame_idx >= ts.shape[0] or channel_idx >= ts.shape[1]:
            return "N/A", 0.0

        ts_seconds = ts[frame_idx, channel_idx]
        ts_start_seconds = ts[0, 0]

        # iThera uses .NET DateTime ticks
        try:
            from datetime import datetime, timedelta

            dt = datetime(1, 1, 1) + timedelta(seconds=float(ts_seconds))
        except Exception:
            logger.info(
                "timestamp_for_slice failed to convert timestamp to datetime",
                exc_info=True,
            )
            dt = "N/A"

        return dt, float(ts_seconds) - float(ts_start_seconds)

    def update_info_labels(self, event=None) -> None:
        if self.info is None:
            return
        self.info.metadata_button.setEnabled(self.active_recon_layer is not None)
        if self.active_recon_layer is None:
            self.info.set_message("Select a PA image layer")
            return

        frame_channel = selected_frame_and_channel(self.viewer)
        if frame_channel is None:
            self.info.set_rows([("Layer", self.active_recon_layer.name)])
            return
        frame_idx, channel_idx = frame_channel

        axis1_name = str(
            self.active_recon_layer.metadata.get("axis1_name", "Channel")
        )
        axis1_labels = self.active_recon_layer.metadata.get("axis1_labels")

        if isinstance(axis1_labels, (list, tuple)) and 0 <= channel_idx < len(
            axis1_labels
        ):
            axis1_value = str(axis1_labels[channel_idx])
        else:
            wavelengths = self.wavelengths
            if isinstance(
                wavelengths, (list, tuple)
            ) and 0 <= channel_idx < len(wavelengths):
                axis1_value = f"{wavelengths[channel_idx]} nm"
            else:
                axis1_value = str(channel_idx)

        frames = self.active_recon_layer.metadata.get("frames")
        is_reconstructed = frames is None or frame_idx in frames
        frame_label = (
            f"Frame: {frame_idx} (reconstructed)"
            if is_reconstructed
            else f"Frame: {frame_idx} (missing)"
        )

        self.viewer.dims.axis_labels = (
            frame_label,
            f"{axis1_name}: {axis1_value}",
            "z",
            "x",
        )

        ts, ts_delta = self.timestamp_for_slice(frame_idx, channel_idx)
        scan_folder = str(self.path.stem) if getattr(self, "path", None) else "N/A"
        scan_info = self._scans.get(getattr(self, "path", Path()))
        scan_name = scan_info.internal_name if scan_info and scan_info.internal_name else ""
        scan_display = f"{scan_folder} ({scan_name})" if scan_name else scan_folder
        study_str = (
            str(self.study_path.stem)
            if getattr(self, "study_path", None)
            else "N/A"
        )
        self.info.set_rows(
            [
                ("Study", study_str),
                ("Scan", scan_display),
                ("Layer", self.active_recon_layer.name),
                ("Frame", f"{frame_idx} | {axis1_name}: {axis1_value}"),
                ("Timestamp", f"{ts} ({ts_delta:.2f} s)"),
            ]
        )

    def on_metadata_clicked(self) -> None:
        """Open metadata window for the currently selected image layer."""
        selected_layers = list(self.viewer.layers.selection)
        layer = next(
            (candidate for candidate in reversed(selected_layers) if isinstance(candidate, Image)),
            self.active_recon_layer,
        )
        if layer is None:
            return

        scan_info = self._scans.get(getattr(self, "path", Path()))
        dialog = LayerMetadataDialog(
            layer=layer,
            pa_data=self.pa_data,
            scan_path=getattr(self, "path", None),
            study_path=getattr(self, "study_path", None),
            scan_info=scan_info,
            parent=self.viewer.window._qt_window,
        )
        dialog.exec()
