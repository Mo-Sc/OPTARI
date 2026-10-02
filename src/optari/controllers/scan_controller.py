"""Scan and study discovery, and loading a scan into the viewer."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import patato as pat
from napari.layers import Image
from napari.utils.notifications import show_info, show_warning
from patato.io.ithera.read_ithera import iTheraMSOT
from qtpy.QtWidgets import QDialog, QFileDialog

from optari.io.discovery import ScanInfo, discover_scans, scan_type
from optari.patato_bridge import (
    build_napari_layers,
    fov_from_objects,
    roi_records_from_scan_rois,
)
from optari.io.export_pipeline import (
    export_scan_to_hdf5,
    export_scan_to_ipasc,
    ipasc_export_report,
)
from optari.utils.misc import roi_color_for_index
from optari.utils.motion import k_motion_scores_optimized
from optari.utils.setup import load_startup_logo
from optari.controllers.base import TaskControllerBase
from optari.controllers.viewer_export_controller import ViewerExportController


from optari.config import settings

if TYPE_CHECKING:
    from optari.controllers.optari_controller import OptariController

logger = logging.getLogger(__name__)


class _StudyOrScanDialog(QFileDialog):
    """Picks a study folder, an iThera scan folder or an HDF5 scan in one dialog.
    Used as a workaround for windows, where the native file dialog does not allow
    selecting both folders and files.
    """

    def __init__(self) -> None:
        super().__init__(None, "Select study folder or scan", str(Path.cwd()))
        self.setOption(QFileDialog.DontUseNativeDialog)
        self.setFileMode(QFileDialog.AnyFile)
        self.setNameFilter("HDF5 scans (*.hdf5);;All files (*)")

    def accept(self) -> None:
        target = Path(self.selectedFiles()[0])
        if target.is_dir():
            QDialog.accept(self)
        elif target.is_file():
            super().accept()


class ScanController(TaskControllerBase):
    """Scan/session lifecycle and data-loading helpers for OPTARI."""

    def __init__(self, parent_controller: OptariController):
        """Initialize with reference to parent controller.

        Args:
            parent_controller: OptariController instance with viewer and session state.
        """
        super().__init__(parent_controller)
        # The Scan Browser's study. A batch run loads scans from elsewhere.
        self.scans: dict[Path, ScanInfo] = {}
        self._export_view_handler = (
            lambda: ViewerExportController.on_export_clicked(
                self.optari_controller
            )
        )

    def _signal_bindings(self) -> list[tuple[object, Callable]]:
        """Scan browser signals."""
        dock = self.optari_controller.scan_browser
        return [
            (dock.browse_button.clicked, self.on_browse_study_clicked),
            (dock.scans_list.currentRowChanged, self.on_scan_selected),
            (dock.hdf5_button.clicked, self.on_hdf5_export_clicked),
            (dock.ipasc_button.clicked, self.on_ipasc_export_clicked),
            (dock.export_layer_button.clicked, self._export_view_handler),
        ]

    def refresh_ui(self) -> None:
        """Lock the scan browser while a task runs, and gate HDF5 export on a scan being loaded."""
        self.optari_controller.scan_browser.widget.setEnabled(
            not self.optari_controller.task_running
        )
        self.optari_controller.scan_browser.hdf5_button.setEnabled(
            self.optari_controller.pa_data is not None
        )
        self.optari_controller.scan_browser.ipasc_button.setEnabled(
            self.optari_controller.pa_data is not None
        )

    def scan_name(self) -> "str | None":
        """The scan's internal (vendor) name, for stamping onto layers OPTARI creates."""
        return self.optari_controller.scan_info.internal_name

    def close_current_scan(self) -> None:
        """Close the HDF5 handle for the current scan."""
        if self.optari_controller.pa_data is not None:
            try:
                self.optari_controller.pa_data.close()
            except Exception:
                logger.info(
                    "failed to close current scan handle", exc_info=True
                )
        self.optari_controller.pa_data = None
        self.optari_controller.scan_info = None
        self.optari_controller.patato_objects = {}
        self.optari_controller.derived_patato_objects = {}
        self.optari_controller.clinical_metadata_edits = None

    def reset_scan_state(self, restore_startup_logo: bool = True) -> None:
        """Clear current scan state and remove all viewer layers."""
        self.close_current_scan()
        self.optari_controller.segmentation_ctrl.teardown()
        self.optari_controller.active_recon_layer = None
        self.optari_controller.active_us_layer = None
        self.optari_controller.shapes_layer = None
        self.optari_controller.roi_ctrl.clear_roi_records()
        self.optari_controller._last_frame_idx = None

        for layer in list(self.viewer.layers):
            self.viewer.layers.remove(layer)
        self.optari_controller.refresh_controller_uis()
        if restore_startup_logo:
            load_startup_logo(self.viewer)

    def on_browse_study_clicked(self) -> None:
        """Prompt for a study folder, or a single scan to open together with its study."""
        dialog = _StudyOrScanDialog()
        if not dialog.exec():
            return
        target = Path(dialog.selectedFiles()[0])
        # An iThera scan is a folder too, but opens like a scan file.
        if target.is_dir() and scan_type(target) is None:
            self.set_scan_folder(target)
        else:
            self.open_scan_file(target)

    def open_scan_file(self, scan_path: Path) -> None:
        """Discover a scan's study and select that scan in the browser."""
        self.set_scan_folder(scan_path.parent, selected_scan=scan_path)

    def on_scan_selected(self, row: int) -> None:
        """Load the scan at *row* in the scan list, ignoring an out-of-range selection."""
        scans = list(self.scans.items())
        if row < 0 or row >= len(scans):
            return
        self.load_scan(*scans[row])

    def set_scan_folder(
        self, folder: Path, *, selected_scan: Path | None = None
    ) -> None:
        """Discover scans in *folder* and select *selected_scan* or the first available scan."""
        folder = Path(folder)
        self.scans = discover_scans(folder)

        self.optari_controller.scan_browser.set_folder(folder)
        self.optari_controller.scan_browser.set_scans(list(self.scans.items()))

        # Auto-select first scan if available.
        if self.scans:
            selected_scan = selected_scan or next(iter(self.scans))
            try:
                row = list(self.scans).index(selected_scan)
            except ValueError:
                self.reset_scan_state()
                return
            self.optari_controller.scan_browser.scans_list.setCurrentRow(row)
        else:
            self.reset_scan_state()

    def load_scan(self, scan_path: Path, scan_info: ScanInfo) -> bool:
        """Open *scan_path* and build its layers. False if the scan could not be loaded.

        Failures fall back to the startup logo rather than raising, which is what the
        GUI wants. The return value is what lets an unattended caller (batch mode) tell
        a loaded scan from an empty viewer. *scan_info* comes from discovery, so the
        Scan Browser's list and a batch plan can each load their own scans.
        """
        logger.info("loading scan: %s", scan_path)

        self.optari_controller.path = scan_path
        self.reset_scan_state(restore_startup_logo=False)

        if not scan_path.exists():
            logger.warning("scan not found: %s", scan_path)
            load_startup_logo(self.viewer)
            self.optari_controller.refresh_all()
            return False

        try:
            if scan_info.kind == "ithera":
                self.optari_controller.pa_data = pat.PAData(
                    iTheraMSOT(str(scan_path))
                )
            else:
                # PATATO's reader factory tells the PATATO and IPASC layouts apart itself.
                self.optari_controller.pa_data = pat.PAData.from_hdf5(
                    str(scan_path), mode="r"
                )
        except Exception:
            logger.exception("failed to open scan '%s'", scan_path)
            load_startup_logo(self.viewer)
            self.optari_controller.refresh_all()
            return False
        self.optari_controller.scan_info = scan_info

        try:
            layers = self.layers_from_pa_data()
        except Exception:
            logger.exception("failed to load '%s'", scan_path)
            self.close_current_scan()
            load_startup_logo(self.viewer)
            self.optari_controller.refresh_all()
            return False

        for data, kw in layers:
            kw["metadata"] = {
                "filepath": str(scan_path),
                "scan_name": scan_info.internal_name,
                **kw["metadata"],
            }
            self.viewer.add_image(
                data, units=self.image_units, **kw
            ).colorbar.visible = True

        # Create the ROIs layer after image layers so it stays on top.
        self.optari_controller.shapes_layer = self.viewer.add_shapes(
            name="ROIs",
            edge_color=roi_color_for_index(0),
            face_color="transparent",
            edge_width=0.1,
            ndim=2,
            metadata={"type": "roi"},
            units=("mm", "mm"),
        )
        self.optari_controller.shapes_layer.locked = True
        self.optari_controller.connect_shapes_layer_events()

        # After adding layers, pick a sensible default selected layer.
        try:
            self.optari_controller.select_default_pa_layer()
        except RuntimeError as e:
            logger.info("Default PA layer not found", exc_info=True)
            show_warning(str(e))

        # Set the active US layer if available.
        self.optari_controller.active_us_layer = next(
            (
                l
                for l in self.viewer.layers
                if isinstance(l, Image) and l.metadata.get("type") == "us"
            ),
            None,
        )
        self.optari_controller.resolve_active_recon_layer()
        self.optari_controller.segmentation_ctrl.restore_from_scan(
            self.optari_controller.pa_data
        )
        self.optari_controller.refresh_controller_uis()

        # Initialize viewer position to DEFAULT_FRAME_INDEX and DEFAULT_CHANNEL_INDEX
        try:
            self.go_to_frame(settings.general.DEFAULT_FRAME_INDEX)
        except ValueError as exc:  # a configured frame this scan does not have
            logger.warning("%s, starting at frame 0 instead", exc)
            self.viewer.dims.set_point(0, 0)
        self.viewer.dims.set_point(1, settings.general.DEFAULT_CHANNEL_INDEX)

        # Populate ROIs after dims are initialized to avoid computing stats before the viewer is ready.
        self.init_shapes_from_scan()

        # Fit view to the newly loaded data (prevents "zoomed out" state).
        self.viewer.reset_view()

        return True

    def go_to_frame(self, selector: int | str) -> int:
        """Show the frame *selector* means for the loaded scan, and return it.

        ``"motion"`` is the frame with the lowest ``motion_scores()``. A scan with no
        ultrasound (a raw time series) has nothing to score and falls back to frame 0.
        Both the viewer and a batch run go through this, so "motion" means the same
        frame in either.

        Raises ValueError for a frame number the scan does not have.
        """
        if selector == "motion":
            frame_id = self._lowest_motion_frame()
        else:
            frame_id = int(selector)
            n_frames = (
                int(self.viewer.dims.nsteps[0]) if self.viewer.dims.ndim else 0
            )
            if not 0 <= frame_id < n_frames:
                raise ValueError(
                    f"frame {frame_id} is outside this scan ({n_frames} frames)"
                )
        self.viewer.dims.set_point(0, frame_id)
        return frame_id

    def motion_scores(self) -> np.ndarray | None:
        """Motion score per frame of the loaded scan (0 = stillest, 1 = most motion),
        or None without ultrasound.

        Computed on first use and cached on the US layer, so frame selection and any
        later display of the scores share one computation.
        """
        us_layer = self.optari_controller.active_us_layer
        if us_layer is None:
            return None
        if "motion_scores" not in us_layer.metadata:
            us_layer.metadata["motion_scores"] = k_motion_scores_optimized(
                np.asarray(us_layer.data)
            )
        return us_layer.metadata["motion_scores"]

    def _lowest_motion_frame(self) -> int:
        scores = self.motion_scores()
        if scores is None:
            logger.info("no ultrasound to score motion on, using frame 0")
            return 0
        frame_id = int(np.argmin(scores))
        logger.info(
            "motion-based frame selection: frame %d, score %.4f",
            frame_id,
            scores[frame_id],
        )
        return frame_id

    def layers_from_pa_data(self) -> list[tuple]:
        """Build napari LayerData tuples from the open ``controller.pa_data`` handle."""
        layers, self.optari_controller.patato_objects = build_napari_layers(
            self.optari_controller.pa_data
        )
        return layers

    def get_fov(self) -> "tuple[float, float] | None":
        """Return ``(fov_x_m, fov_y_m)`` from stored PATATO objects, or ``None``."""
        return fov_from_objects(self.optari_controller.patato_objects)

    def init_shapes_from_scan(self) -> None:
        """Fill the freshly created ROIs layer with the ROIs stored in the scan."""
        roi_ctrl = self.optari_controller.roi_ctrl
        fov = self.get_fov()
        if fov is not None:
            try:
                # Projects the current frame into the layer, with ids and properties.
                roi_ctrl.restore_roi_records(
                    roi_records_from_scan_rois(
                        self.optari_controller.pa_data, *fov
                    )
                )
                logger.info(
                    "restored %s stored ROI record(s)",
                    len(roi_ctrl.roi_records),
                )
            except ValueError as exc:
                logger.warning(
                    "could not restore stored ROIs from %s: %s",
                    self.optari_controller.path,
                    exc,
                    exc_info=True,
                )
                show_warning(
                    f"Scan loaded without saved ROI annotations: {exc}"
                )

        # Select the restored ROIs, which also enables the Save button.
        shapes_layer = self.optari_controller.shapes_layer
        shapes_layer.selected_data = set(range(len(shapes_layer.data)))
        roi_ctrl.refresh_ui()

    def on_hdf5_export_clicked(self, event=None) -> None:
        """Prompt for a destination and export the current scan to HDF5."""
        destination = self._choose_export_path()
        if destination is None:
            return

        if export_scan_to_hdf5(self.optari_controller, destination):
            show_info(f"Exported scan to {destination.name}")

    def on_ipasc_export_clicked(self, event=None) -> None:
        """Prompt for a destination and export the current scan's raw time series as IPASC."""
        destination = self._choose_export_path(
            title="Export raw time series as IPASC", suffix="_ipasc"
        )
        if destination is None:
            return

        if not export_scan_to_ipasc(self.optari_controller, destination):
            return
        show_info(
            f"Exported raw time series to {destination.name}. "
            + ipasc_export_report(destination)
        )

    def _choose_export_path(
        self, title: str = "Export scan as HDF5", suffix: str = ""
    ) -> Path | None:
        scan_path = self.optari_controller.path
        default_name = (
            f"{scan_path.stem if scan_path else 'export'}{suffix}.hdf5"
        )
        filename, _ = QFileDialog.getSaveFileName(
            None,
            title,
            str(
                (scan_path.parent if scan_path else Path.cwd()) / default_name
            ),
            "HDF5 files (*.hdf5 *.h5)",
        )
        if not filename:
            return None
        return Path(filename)
