"""Scan and study discovery, and loading a scan into the viewer."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
from typing import TYPE_CHECKING

import numpy as np
import patato as pat
from napari.layers import Image
from napari.utils.notifications import show_info, show_warning
from patato.io.ithera.read_ithera import iTheraMSOT
from qtpy.QtWidgets import QFileDialog

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


@dataclass(frozen=True)
class ScanInfo:
    """Metadata for a discovered scan."""

    kind: str  # "hdf5", "ipasc", "ithera"
    internal_name: str | None


class ScanController(TaskControllerBase):
    """Scan/session lifecycle and data-loading helpers for OPTARI."""

    def __init__(self, parent_controller: OptariController):
        """Initialize with reference to parent controller.

        Args:
            parent_controller: OptariController instance with viewer and session state.
        """
        super().__init__(parent_controller)
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

    def wavelengths(self) -> "list[int] | None":
        """Return scan wavelengths in nm, or ``None`` if unavailable."""
        if self.optari_controller.pa_data is None:
            return None
        try:
            return [
                int(w)
                for w in self.optari_controller.pa_data.get_wavelengths()
            ]
        except Exception:
            logger.exception("failed to read wavelengths from scan metadata")
            return None

    def timestamps(self) -> "np.ndarray | None":
        """Return scan timestamps array, or ``None`` if unavailable."""
        if self.optari_controller.pa_data is None:
            return None
        try:
            return np.array(self.optari_controller.pa_data.get_timestamps())
        except Exception:
            logger.exception("failed to read timestamps from scan metadata")
            return None

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
        self.optari_controller._patato_objects = {}
        self.optari_controller._derived_patato_objects = {}
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

    def init_path(self, path: Path) -> None:
        """Initialize the scan browser from a startup path, whether it's a folder or a scan file."""
        if path.is_dir():
            self.set_scan_folder(path)
            return

        if path.is_file():
            self.open_scan_file(path)
            return

        # Not a real path yet (e.g. in tests). Leave UI usable.
        self.optari_controller.scan_browser.set_folder(path)

    def on_browse_study_clicked(self) -> None:
        """Prompt for a study folder or HDF5 scan file."""
        dialog = QFileDialog(
            None,
            "Select study folder or HDF5 scan file",
            str(Path.cwd()),
        )
        dialog.setFileMode(QFileDialog.AnyFile)
        dialog.setNameFilter("HDF5 scans (*.hdf5);;All files (*)")
        if not dialog.exec():
            return
        selected = dialog.selectedFiles()
        if not selected:
            return
        target = Path(selected[0])
        if target.is_dir():
            self.set_scan_folder(target)
        elif target.is_file():
            self.open_scan_file(target)

    def open_scan_file(self, scan_path: Path) -> None:
        """Discover a scan's study and select that scan in the browser."""
        self.set_scan_folder(scan_path.parent, selected_scan=scan_path)

    def on_scan_selected(self, row: int) -> None:
        """Load the scan at *row* in the scan list, ignoring an out-of-range selection."""
        scans = list(self.optari_controller._scans.items())
        if row < 0 or row >= len(scans):
            return
        self.load_scan(*scans[row])

    def set_scan_folder(
        self, folder: Path, *, selected_scan: Path | None = None
    ) -> None:
        """Discover scans in *folder* and select *selected_scan* or the first available scan."""
        folder = Path(folder)
        self.optari_controller._scans = self.discover_scans(folder)

        self.optari_controller.scan_browser.set_folder(folder)
        self.optari_controller.scan_browser.set_scans(
            list(self.optari_controller._scans.items())
        )

        # Auto-select first scan if available.
        if self.optari_controller._scans:
            selected_scan = selected_scan or next(
                iter(self.optari_controller._scans)
            )
            try:
                row = list(self.optari_controller._scans).index(selected_scan)
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
        self.optari_controller.study_path = scan_path.parent
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
        self.optari_controller._connect_shapes_layer_events()

        # After adding layers, pick a sensible default selected layer.
        try:
            self.optari_controller._select_default_pa_layer()
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
        self.optari_controller._resolve_active_recon_layer()
        self.optari_controller.segmentation_ctrl.restore_from_scan(
            self.optari_controller.pa_data
        )
        self.optari_controller.refresh_controller_uis()

        # Initialize viewer position to DEFAULT_FRAME_INDEX and DEFAULT_CHANNEL_INDEX
        try:
            self.go_to_frame(settings.general.DEFAULT_FRAME_INDEX)
            self.viewer.dims.set_point(
                1, settings.general.DEFAULT_CHANNEL_INDEX
            )
        except Exception:
            logger.warning(
                "failed to set initial viewer position. Setting to (0, 0)",
                exc_info=True,
            )
            self.viewer.dims.set_point(0, 0)
            self.viewer.dims.set_point(1, 0)

        # Populate ROIs after dims are initialized to avoid computing stats before the viewer is ready.
        self.init_shapes_from_scan()

        # Fit view to the newly loaded data (prevents "zoomed out" state).
        try:
            self.viewer.reset_view()
        except Exception:
            logger.info("failed to reset viewer view", exc_info=True)

        return True

    def go_to_frame(self, selector: int | str) -> int:
        """Show the frame *selector* means for the loaded scan, and return it.

        ``"motion"`` is the lowest-motion frame. The scores are computed here on demand
        if the scan was opened with a different default, and cached on the US layer so
        the next caller gets them for free. A scan with no ultrasound (a raw time
        series) has nothing to score and falls back to frame 0. Both the viewer and a
        batch run go through this, so "motion" means the same frame in either.

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

    def _lowest_motion_frame(self) -> int:
        us_layer = self.optari_controller.active_us_layer
        if us_layer is None:
            logger.info("no ultrasound to score motion on, using frame 0")
            return 0

        scores = us_layer.metadata.get("motion_scores")
        if scores is None:
            scores = k_motion_scores_optimized(np.asarray(us_layer.data))
            us_layer.metadata["motion_scores"] = scores
        frame_id = int(np.argmin(scores))
        logger.info(
            "motion-based frame selection: frame %d, score %.4f",
            frame_id,
            scores[frame_id],
        )
        return frame_id

    @staticmethod
    def scan_key(scan_path: Path) -> str:
        """Return the ``Scan_<n>`` prefix of *scan_path*'s name, or the full name if it doesn't match."""
        name = scan_path.stem if scan_path.is_file() else scan_path.name
        m = re.match(r"^(Scan_\d+)", name)
        return m.group(1) if m else name

    @staticmethod
    def scan_sort_key(scan_path: Path):
        """Sort key that orders ``Scan_<n>`` names numerically, ahead of any other name sorted alphabetically."""
        key = ScanController.scan_key(scan_path)
        m = re.match(r"^Scan_(\d+)$", key)
        if m:
            return (0, int(m.group(1)), key)
        return (1, 0, key)

    @staticmethod
    def scan_type(path: Path) -> str | None:
        """
        Identify the format of a scan on disk, or ``None`` if the path is not a scan.
        """
        import h5py
        from patato.io.attribute_tags import HDF5Tags, IPASCTags

        if path.is_dir():
            return "ithera" if any(path.glob("*.msot")) else None
        if path.suffix.lower() != ".hdf5":
            return None
        try:
            with h5py.File(path, "r") as file:
                if IPASCTags.BINARY_DATA in file:
                    return "ipasc"
                if HDF5Tags.RAW_DATA in file:
                    return "hdf5"
        except OSError:
            logger.debug("could not open '%s' as HDF5", path, exc_info=True)
        return None

    @staticmethod
    def _read_internal_scan_name(path: Path, kind: str) -> str | None:
        """
        Read the name the scanner gave the scan, or ``None`` if the format has none.
        Tries to avoid reading the whole scan into memory.
        """
        if kind == "ipasc":
            return None

        try:
            if kind == "ithera":
                # Parse only the relevant XML node rather than the whole scan.
                import xml.dom.minidom

                msot = path / f"{path.name}.msot"
                tree = xml.dom.minidom.parse(str(msot))
                scan_nodes = tree.getElementsByTagName("ScanNode")
                if scan_nodes:
                    name_nodes = scan_nodes[0].getElementsByTagName("Name")
                    if name_nodes and name_nodes[0].firstChild:
                        return name_nodes[0].firstChild.nodeValue.strip()
            else:
                from patato.io.hdf.hdf5_reader_factory import get_hdf5_reader

                reader = get_hdf5_reader(str(path))
                name = reader.get_scan_name()
                reader.close()
                return str(name) if name else None
        except Exception:
            logger.debug(
                "failed to read internal scan name from '%s'",
                path,
                exc_info=True,
            )
        return None

    @staticmethod
    def discover_studies(
        root: Path, max_depth: int = 3
    ) -> dict[Path, dict[Path, ScanInfo]]:
        """Map each study folder under *root* to its scans, in folder-name order.

        A study is simply any folder that holds at least one scan, so a flat folder
        of scans comes back as a single study and no naming convention is imposed
        beyond the ``Scan_*`` one ``discover_scans`` already relies on. A folder that
        is itself a study is not descended into.
        """
        root = Path(root)
        studies: dict[Path, dict[Path, ScanInfo]] = {}

        def walk(folder: Path, depth: int) -> None:
            """Recurse into *folder* up to *max_depth*, stopping at the first folder that holds a scan."""
            scans = ScanController.discover_scans(folder)
            if scans:
                studies[folder] = scans
                return
            if depth >= max_depth:
                return
            try:
                children = sorted(
                    child
                    for child in folder.iterdir()
                    # Following symlinks here risks walking a cycle or wandering
                    # outside the dataset the user picked.
                    if child.is_dir() and not child.is_symlink()
                )
            except (PermissionError, OSError):
                logger.warning("could not list '%s', skipping", folder)
                return
            for child in children:
                walk(child, depth + 1)

        walk(root, 0)
        return studies

    @staticmethod
    def discover_scans(folder: Path) -> dict[Path, ScanInfo]:
        """Find every scan directly under *folder*, keyed by path and deduplicated by ``scan_key``.

        When both an HDF5 file and an iThera folder resolve to the same key, the HDF5
        one wins.
        """
        # One entry per scan key; if both exist, prefer HDF5 over iThera folder.
        by_key: dict[str, tuple[Path, str, str | None]] = {}

        # check every hdf5 file and every Scan_* folder in the directory for a valid scan
        for p in sorted(folder.glob("*.hdf5")):
            kind = ScanController.scan_type(p)
            if kind is None:
                continue
            internal = ScanController._read_internal_scan_name(p, kind)
            by_key[ScanController.scan_key(p)] = (p, kind, internal)

        for d in folder.glob("Scan_*"):
            kind = ScanController.scan_type(d)
            if kind is None:
                continue
            key = ScanController.scan_key(d)
            if key not in by_key:
                internal = ScanController._read_internal_scan_name(d, kind)
                by_key[key] = (d, kind, internal)

        entries = sorted(
            ((v[0], v[1], v[2]) for v in by_key.values()),
            key=lambda item: ScanController.scan_sort_key(item[0]),
        )
        return {p: ScanInfo(kind=k, internal_name=n) for p, k, n in entries}

    def layers_from_pa_data(self) -> list[tuple]:
        """Build napari LayerData tuples from the open ``controller.pa_data`` handle."""
        layers, self.optari_controller._patato_objects = build_napari_layers(
            self.optari_controller.pa_data
        )
        return layers

    def get_fov(self) -> "tuple[float, float] | None":
        """Return ``(fov_x_m, fov_y_m)`` from stored PATATO objects, or ``None``."""
        return fov_from_objects(self.optari_controller._patato_objects)

    def init_shapes_from_scan(self) -> None:
        """Clear the ROIs layer and populate it with any ROIs stored in the scan."""
        shapes_layer = self.optari_controller.shapes_layer
        if shapes_layer is None:
            return

        data_event = shapes_layer.events.data
        data_event.disconnect(self.optari_controller._on_shapes_data_changed)
        try:
            shapes: list = []
            self.optari_controller.roi_ctrl.clear_roi_records()
            shapes_layer.data = []
            fov = (
                self.get_fov()
                if self.optari_controller.pa_data is not None
                else None
            )
            if fov is not None:
                records = roi_records_from_scan_rois(
                    self.optari_controller.pa_data, *fov
                )
                self.optari_controller.roi_ctrl.restore_roi_records(records)
                shapes = [
                    (
                        record.verts,
                        record.kind,
                        record.tissue_class,
                        record.source,
                    )
                    for record in records
                    if record.frame_id == int(self.viewer.dims.point[0])
                ]

                # Auto select the loaded ROIs for convenience and to activate the button
                if shapes:
                    shapes_layer.selected_data = set(range(len(shapes)))

                # add roi_tissue_class property to shapes layer
                props = dict(getattr(shapes_layer, "properties", {}) or {})
                props["roi_tissue_class"] = [tc for _, _, tc, _ in shapes]
                props["roi_source"] = [src for _, _, _, src in shapes]
                shapes_layer.properties = props

                if shapes:
                    logger.info("loaded %s ROI(s) from scan", len(shapes))

        except ValueError as exc:
            logger.warning(
                "could not restore stored ROIs from %s: %s",
                self.optari_controller.path,
                exc,
                exc_info=True,
            )
            show_warning(
                "Scan loaded without saved ROI annotations: " f"{exc}"
            )
        finally:
            data_event.connect(self.optari_controller._on_shapes_data_changed)
            # Single refresh at the end regardless of success/failure.
            self.optari_controller._on_shapes_data_changed()

    def export_hdf5(self, destination: Path) -> bool:
        """Export scan to HDF5 including OPTARI ROIs and derived datasets."""
        return export_scan_to_hdf5(self.optari_controller, destination)

    def on_hdf5_export_clicked(self, event=None) -> None:
        """Prompt for a destination and export the current scan to HDF5."""
        destination = self._choose_export_path()
        if destination is None:
            return

        if self.export_hdf5(destination):
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
