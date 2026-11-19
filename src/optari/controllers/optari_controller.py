"""``OptariController``, the hub every dock and controller hangs off."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import patato as pat  # type: ignore
from napari.layers import Image, Shapes
from napari.viewer import Viewer

if TYPE_CHECKING:
    from napari.qt.threading import GeneratorWorker
    from qtpy.QtWidgets import QDockWidget

from optari.config import settings
from optari.controllers.analysis_controller import AnalysisController
from optari.controllers.base import TaskControllerBase
from optari.controllers.menu_manager import MenuManager
from optari.controllers.reconstruction_controller import (
    ReconstructionController,
)
from optari.controllers.roi_controller import RoiController
from optari.controllers.scan_controller import ScanController
from optari.controllers.segmentation_controller import SegmentationController
from optari.controllers.shortcut_manager import ShortcutManager

# from optari.controllers.demo_controller import DemoController # Demo feature
from optari.controllers.ui_manager import UiManager
from optari.controllers.unmixing_controller import UnmixingController
from optari.controllers.viewer_export_controller import ViewerExportController
from optari.io.discovery import ScanInfo
from optari.patato_bridge import is_pa_layer, pa_layers
from optari.roi.roi_utils import slice_datetime
from optari.utils.viewer import selected_frame_and_channel
from optari.widgets.annotation_dock import AnnotationDock
from optari.widgets.histogram_dock import HistogramDock
from optari.widgets.info_dock import InfoDock
from optari.widgets.layer_metadata_dialog import LayerMetadataDialog
from optari.widgets.motion_dock import MotionDock
from optari.widgets.reconstruction_dock import ReconstructionDock
from optari.widgets.roi_dock import RoiDock
from optari.widgets.scan_browser_dock import ScanBrowserDock
from optari.widgets.segmentation_dock import SegmentationDock
from optari.widgets.spectrum_dock import SpectrumDock
from optari.widgets.time_analysis_dock import TimeAnalysisDock
from optari.widgets.unmixing_dock import UnmixingDock

logger = logging.getLogger(__name__)


class OptariController:
    """The session: viewer, loaded scan, docks and one instance of each controller.

    Attributes ending in ``_dock`` are the dock widget dataclasses, those ending in
    ``_ctrl`` the controllers. Controllers never hold each other and go through this
    object instead. Every lifecycle step (initialize, bind, refresh, shut down) and
    every viewer hook runs over ``controllers``.
    """

    def __init__(self, viewer: Viewer):

        self.viewer = viewer
        self.path: Path | None = None
        self.scan_info: ScanInfo | None = None  # of the loaded scan

        self.pa_data: pat.PAData | None = None
        self.patato_objects: dict[str, pat.ImageSequence] = {}
        self.derived_patato_objects: dict[str, pat.ImageSequence] = {}
        # (fov_x_m, fov_y_m) the scan's ROIs are stored in, resolved once at load so
        # removing a layer cannot change it
        self.scan_fov: tuple[float, float] | None = None
        self.clinical_metadata_edits: dict[str, str] | None = None

        self.shapes_layer: Shapes | None = None
        self._last_frame_idx: int | None = None
        self.active_recon_layer: Image | None = None
        self.active_us_layer: Image | None = None
        self.active_task: GeneratorWorker | None = None
        # A batch run loads scans and measures on the main thread
        self.batch_running = False

        # Docks, set by UiManager.setup_docks() from its DOCKS table. dock_widgets maps
        # each dock's title to the Qt dock widget holding it, napari's own Layer
        # Controls/List included.
        self.dock_widgets: dict[str, QDockWidget] = {}
        self.scan_browser_dock: ScanBrowserDock | None = None
        self.info_dock: InfoDock | None = None
        self.roi_dock: RoiDock | None = None
        self.time_analysis_dock: TimeAnalysisDock | None = None
        self.motion_dock: MotionDock | None = None
        self.histogram_dock: HistogramDock | None = None
        self.spectrum_dock: SpectrumDock | None = None
        self.annotation_dock: AnnotationDock | None = None
        self.segmentation_dock: SegmentationDock | None = None
        self.unmixing_dock: UnmixingDock | None = None
        self.reconstruction_dock: ReconstructionDock | None = None

        self.viewer_export_ctrl = ViewerExportController(self)
        self.scan_ctrl = ScanController(self)
        self.roi_ctrl = RoiController(self)
        self.segmentation_ctrl = SegmentationController(self)
        self.analysis_ctrl = AnalysisController(self)
        self.unmixing_ctrl = UnmixingController(self)
        self.reconstruction_ctrl = ReconstructionController(self)
        # Every task controller. Each step (initialize, bind, refresh, shut down) and
        # viewer hook runs over this list in this order, so a new one is added here
        # only.
        self.controllers: list[TaskControllerBase] = [
            self.scan_ctrl,
            self.roi_ctrl,
            self.analysis_ctrl,
            self.unmixing_ctrl,
            self.reconstruction_ctrl,
            self.segmentation_ctrl,
            # DemoController(self),  # demo feature
        ]

        # Track event bindings for proper cleanup
        self._shapes_layer_bindings = []

        self.settings_dialog = None
        self.batch_dialog = None
        self.is_shut_down = False

        self._setup_viewer()
        self.ui_manager = UiManager(self)
        self.ui_manager.setup_docks()
        self.menu_manager = MenuManager(self)
        self.menu_manager.setup()
        for controller in self.controllers:
            controller.initialize_ui()
        self.refresh_controller_uis()
        self.ui_manager.connect_events()
        self.shortcut_manager = ShortcutManager(self)
        self.shortcut_manager.register_all()

        self.refresh_all()

    def shutdown(self) -> None:
        """Disconnect every signal and release resources before the widget tree is
        destroyed.

        Called from the main window's close event (see
        UiManager._install_shutdown_hook), which is the last moment at which the dock
        widgets still exist, and again from the launcher as a fallback
        """
        if self.is_shut_down:
            return
        self.is_shut_down = True

        if self.active_task is not None:
            # A worker thread still driving the UI while Qt tears the widget tree down
            # is a crash, so give it a bounded moment to leave its generator.
            try:
                self.active_task.await_workers(msecs=5000)
            except RuntimeError:
                logger.warning("background task did not stop within 5 s of shutdown")
            self.active_task = None

        for controller in self.controllers:
            controller.unbind_events()
            controller.teardown()

        self.viewer.dims.events.point.disconnect(self.on_dims_changed)
        self.viewer.layers.selection.events.changed.disconnect(
            self.on_selection_changed
        )
        for evt, handler in self._shapes_layer_bindings:
            evt.disconnect(handler)

        # An error above reaches the log through napari's exception hook (close event)
        # or the launcher, which ends the process with os._exit either way, releasing
        # the file.
        self.scan_ctrl.close_current_scan()
        logger.info("OptariController: Shutdown complete")

    # ============ viewer setup ============
    def _setup_viewer(self) -> None:
        self.viewer.scene.overlays.axes.visible = False  # axes hidden by default
        self.viewer.scene.overlays.axes.labels = True
        self.viewer.canvas.grid.enabled = False
        self.viewer.canvas.overlays.scale_bar.visible = True
        self.viewer.dims.axis_labels = ("Frame", "Channel", "z", "x")

    def connect_shapes_layer_events(self) -> None:
        """
        Connects events for the shapes layer to the ROI controller. This includes data
        changes and selection changes. data changes mean ROIs were
        added/removed/replaced selection changes mean the active ROI set changed
        """
        if self.shapes_layer is None:
            return

        # drop the previous scan's bindings, the live table signal would otherwise fire
        # twice
        for evt, handler in self._shapes_layer_bindings:
            evt.disconnect(handler)

        self._shapes_layer_bindings = [
            # Shapes layer data changes drive ROI table refresh, label updates, and
            # formatting.
            (
                self.shapes_layer.events.data,
                self.roi_ctrl.on_shapes_data_changed,
            ),
            # Shape copy/paste appends shapes without emitting events.data, so watch
            # set_data too.
            (
                self.shapes_layer.events.set_data,
                self.roi_ctrl.on_shapes_set_data,
            ),
            # selected_data.items_changed is the selection signal for viewer -> table
            # sync.
            (
                self.shapes_layer.selected_data.events.items_changed,
                self.roi_ctrl.on_shapes_selection_changed,
            ),
            # Live table itemSelectionChanged is signal for table -> viewer sync.
            (
                self.roi_dock.live_table.native.itemSelectionChanged,
                self.roi_ctrl.on_live_table_selection_changed,
            ),
        ]

        for evt, handler in self._shapes_layer_bindings:
            evt.connect(handler)

    # ============ ROI layer management ============
    def ensure_shapes_layer_on_top(self) -> None:
        """
        Moves ROI layer to top. Necessary because some operations (e.g. unmixing) add
        new image layers on top of the ROI layer ROI layer should always be on top of
        the layer stack to be visible and interactive.
        """
        if self.shapes_layer is None:
            return

        current_index = self.viewer.layers.index(self.shapes_layer)
        top_index = len(self.viewer.layers) - 1
        if current_index != top_index:
            # Layer order defines draw order. the last layer renders above all others.
            self.viewer.layers.move(current_index, len(self.viewer.layers))
            logger.info("moved ROI layer to top index %s", top_index)

    # ============ scan state ============
    @property
    def study_path(self) -> Path | None:
        """Folder holding the loaded scan."""
        return None if self.path is None else self.path.parent

    @property
    def task_running(self) -> bool:
        """Whether a background task or a batch run holds the UI."""
        return self.active_task is not None or self.batch_running

    def set_active_task(self, worker: GeneratorWorker | None) -> None:
        """Track the running background task and gate the UI around it.

        Only one heavy task at a time: while one runs, the other run buttons and the
        scan browser stay disabled.
        """
        self.active_task = worker
        self.refresh_controller_uis()

    def refresh_controller_uis(self) -> None:
        """Refresh all controller-owned UI after a state transition."""
        for controller in self.controllers:
            controller.refresh_ui()

    def select_default_pa_layer(self) -> None:
        """Select the configured default PA layer, else the first PA layer.

        Raises RuntimeError when the scan has images but none of them is a PA layer.
        """
        first_pa = None
        default_pa = settings.general.DEFAULT_PA_LAYER
        images = [l for l in self.viewer.layers if isinstance(l, Image)]
        for layer in images:
            if layer.name == default_pa:
                self.viewer.layers.selection.select_only(layer)
                return
            if first_pa is None and is_pa_layer(layer):
                first_pa = layer

        if first_pa is not None:
            self.viewer.layers.selection.select_only(first_pa)
            return

        if not images:
            # Raw time series scans (e.g. IPASC) carry no images until reconstructed.
            return

        raise RuntimeError(f"No PA image layer found (looking for '{default_pa}')")

    # ============ layer selection ============
    def resolve_active_recon_layer(self) -> None:
        """Set `active_recon_layer` to the selected PA image layer (if exactly one is
        selected).
        """

        selection = self.viewer.layers.selection

        if len(selection) != 1:
            # no layer selected or multiple layers selected
            return

        selected_layer = selection.active

        # only change active layer if selected layer is a PA image layer
        if is_pa_layer(selected_layer):
            # No-op if nothing changed (avoids duplicate work/logging).
            if self.active_recon_layer is selected_layer:
                return

            self.active_recon_layer = selected_layer
            logger.info("active layer set to %s", self.active_recon_layer.name)
            # show only the active PA layer. blending and auto contrast are set when PA
            # layers are created
            for layer in pa_layers(self.viewer.layers):
                layer.visible = layer is self.active_recon_layer

    # ============ viewer events ============
    def on_layer_removed(self, event) -> None:
        """Drop any PATATO object tracked under a removed layer's name.

        Otherwise a deleted reconstruction/unmixed layer stays in
        `derived_patato_objects` and gets written into the next HDF5 export as if it
        were still on screen.
        """
        layer = event.value
        self.patato_objects.pop(layer.name, None)
        self.derived_patato_objects.pop(layer.name, None)

        if layer is not self.active_recon_layer and layer is not self.active_us_layer:
            return
        if layer is self.active_us_layer:
            self.active_us_layer = None
        if layer is self.active_recon_layer:
            self.active_recon_layer = None
            self.resolve_active_recon_layer()
        for controller in self.controllers:
            controller.on_active_layers_changed()
        self.refresh_controller_uis()
        self.refresh_all()

    def on_selection_changed(self, event=None) -> None:
        """Follow a new layer selection: active layer, hooks, dims and readouts."""
        self.resolve_active_recon_layer()
        for controller in self.controllers:
            controller.on_active_layers_changed()
        if self._snap_dims_to_active_layer():
            return
        self.refresh_all()

    def on_dims_changed(self, event=None) -> None:
        """Snap to a slice the active layer holds and tell the controllers."""
        if self._snap_dims_to_active_layer():
            return

        frame_idx = int(round(self.viewer.dims.point[0]))
        if frame_idx != self._last_frame_idx:
            self._last_frame_idx = frame_idx
            for controller in self.controllers:
                controller.on_frame_changed(frame_idx)

        self.refresh_all()

    # ============ update everything ============
    def refresh_all(self) -> None:
        """Refresh everything that follows the shown slice: the info dock and the
        controllers' live readouts.
        """
        self.update_info_labels()
        for controller in self.controllers:
            controller.on_slice_shown()

    # ============ snapping dims to the active layer ============
    def snap_to_reconstructed_frame(self, frame_idx: int) -> int:
        """
        snap the given frame index to the closest available frame in the active layer's
        metadata
        """
        if self.active_recon_layer is None:
            return frame_idx
        frames = self.active_recon_layer.metadata.get("frames", None)
        if not frames:
            return frame_idx
        frames = np.asarray(frames, dtype=int)
        return int(frames[np.argmin(np.abs(frames - frame_idx))])

    def snap_to_available_channel(self, channel_idx: int) -> int:
        """Clamp *channel_idx* to the channels the active layer's data holds."""
        if self.active_recon_layer is None:
            return channel_idx

        shape = self.active_recon_layer.data.shape
        if len(shape) < 2:
            return 0

        n_channels = shape[1]
        return int(np.clip(channel_idx, 0, max(0, n_channels - 1)))

    def _snap_dims_to_active_layer(self) -> bool:
        """Move the viewer onto a frame and channel the active layer holds.

        True if it moved, in which case the dims event that follows does the refresh.
        """
        if self.active_recon_layer is None:
            return False

        frame_channel = selected_frame_and_channel(self.viewer)
        if frame_channel is None:
            return False
        frame_idx, channel_idx = frame_channel

        snapped_frame = self.snap_to_reconstructed_frame(frame_idx)
        snapped_channel = self.snap_to_available_channel(channel_idx)

        changed = False
        # Enforce valid index support of the active layer to avoid sampling zero-padded
        # channels.
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
    def timestamp_for_slice(
        self, frame_idx: int, channel_idx: int
    ) -> tuple[str, float]:
        """Wall-clock time of the slice ("N/A" if the scan cannot be dated) and its
        seconds since the first frame."""
        ts = self.active_recon_layer.metadata["timestamps"]
        return (
            slice_datetime(self.active_recon_layer, frame_idx, channel_idx),
            float(ts[frame_idx, channel_idx] - ts[0, 0]),
        )

    def update_info_labels(self, event=None) -> None:
        """Show the active slice's scan, layer, frame and time in the info dock."""
        # Scan, IPASC and clinical metadata need no layer, only the Layer tab does.
        self.info_dock.metadata_button.setEnabled(self.pa_data is not None)
        if self.active_recon_layer is None:
            self.info_dock.set_message("Select a PA image layer")
            return

        frame_channel = selected_frame_and_channel(self.viewer)
        if frame_channel is None:
            self.info_dock.set_rows([("Layer", self.active_recon_layer.name)])
            return
        frame_idx, channel_idx = frame_channel

        # Every PA layer labels its channel axis, dims are snapped to its channels.
        channel = str(self.active_recon_layer.metadata["axis1_labels"][channel_idx])

        frames = self.active_recon_layer.metadata.get("frames")
        is_reconstructed = frames is None or frame_idx in frames
        frame_label = (
            f"Frame: {frame_idx} (reconstructed)"
            if is_reconstructed
            else f"Frame: {frame_idx} (missing)"
        )

        self.viewer.dims.axis_labels = (
            frame_label,
            f"Channel: {channel}",
            "z",
            "x",
        )

        ts, ts_delta = self.timestamp_for_slice(frame_idx, channel_idx)
        scan_folder = self.path.stem if self.path else "N/A"
        scan_name = self.scan_info.internal_name if self.scan_info else ""
        scan_display = f"{scan_folder} ({scan_name})" if scan_name else scan_folder
        study_str = self.study_path.stem if self.study_path else "N/A"
        self.info_dock.set_rows(
            [
                ("Study", study_str),
                ("Scan", scan_display),
                ("Layer", self.active_recon_layer.name),
                ("Frame", f"{frame_idx} | Channel: {channel}"),
                ("Timestamp", f"{ts} ({ts_delta:.2f} s)"),
            ]
        )

    def on_metadata_clicked(self) -> None:
        """Open the metadata window.

        Scan metadata are shown even without an image layer.
        """
        selected_layers = list(self.viewer.layers.selection)
        layer = next(
            (
                candidate
                for candidate in reversed(selected_layers)
                if isinstance(candidate, Image)
            ),
            self.active_recon_layer,
        )

        dialog = LayerMetadataDialog(
            layer=layer,
            pa_data=self.pa_data,
            scan_path=self.path,
            study_path=self.study_path,
            scan_info=self.scan_info,
            controller=self,
            parent=self.viewer.window._qt_window,
        )
        dialog.exec()
