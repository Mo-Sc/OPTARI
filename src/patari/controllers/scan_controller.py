from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
import patato as pat
from napari.layers import Image
from patato.io.ithera.read_ithera import iTheraMSOT
from qtpy.QtWidgets import QFileDialog

from patari.patato_bridge import (
    build_napari_layers,
    fov_from_objects,
    napari_shapes_from_scan_rois,
)
from patari.io.export_pipeline import export_scan_to_hdf5
from patari.utils.misc import roi_color_for_index
from patari.controllers.base import TaskControllerBase
from patari.controllers.viewer_export_controller import ViewerExportController


from patari.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanInfo:
    """Metadata for a discovered scan."""
    kind: str  # "hdf5" or "ithera"
    internal_name: str | None


class ScanController(TaskControllerBase):
    """Scan/session lifecycle and data-loading helpers for PATARI."""

    def __init__(self, parent_controller):
        super().__init__(parent_controller)

    def bind_events(self) -> None:
        """Connect scan browser signals."""
        self.patari_controller.scan_browser.browse_button.clicked.connect(
            self.on_browse_folder_clicked
        )
        self.patari_controller.scan_browser.scans_list.currentRowChanged.connect(
            self.on_scan_selected
        )
        self.patari_controller.scan_browser.hdf5_button.clicked.connect(
            self.on_hdf5_export_clicked
        )
        self.patari_controller.scan_browser.export_layer_button.clicked.connect(
            lambda: ViewerExportController.on_export_clicked(self.patari_controller)
        )

    def unbind_events(self) -> None:
        """Disconnect scan browser signals."""
        try:
            self.patari_controller.scan_browser.browse_button.clicked.disconnect(
                self.on_browse_folder_clicked
            )
            self.patari_controller.scan_browser.scans_list.currentRowChanged.disconnect(
                self.on_scan_selected
            )
            self.patari_controller.scan_browser.hdf5_button.clicked.disconnect(
                self.on_hdf5_export_clicked
            )
            self.patari_controller.scan_browser.export_layer_button.clicked.disconnect()
        except Exception as e:
            logger.exception("Error unbinding scan browser signals: %s", e)

    def wavelengths(self) -> "list[int] | None":
        """Return scan wavelengths in nm, or ``None`` if unavailable."""
        if self.patari_controller.pa_data is None:
            return None
        try:
            return [
                int(w)
                for w in self.patari_controller.pa_data.get_wavelengths()
            ]
        except Exception:
            logger.exception("failed to read wavelengths from scan metadata")
            return None

    def timestamps(self) -> "np.ndarray | None":
        """Return scan timestamps array, or ``None`` if unavailable."""
        if self.patari_controller.pa_data is None:
            return None
        try:
            return np.array(self.patari_controller.pa_data.get_timestamps())
        except Exception:
            logger.exception("failed to read timestamps from scan metadata")
            return None

    def close_current_scan(self) -> None:
        """Close the HDF5 handle for the current scan."""
        if self.patari_controller.pa_data is None:
            return
        try:
            self.patari_controller.pa_data.close()
        except Exception:
            logger.info("failed to close current scan handle", exc_info=True)
        self.patari_controller.pa_data = None
        self.patari_controller._patato_objects = {}
        self.patari_controller._derived_patato_objects = {}

    def reset_scan_state(self) -> None:
        """Clear current scan state and remove all viewer layers."""
        self.close_current_scan()
        self.patari_controller.segmentation_ctrl.teardown()

        for layer in list(self.viewer.layers):
            self.viewer.layers.remove(layer)
        self.patari_controller.active_recon_layer = None
        self.patari_controller.active_us_layer = None
        self.patari_controller.shapes_layer = None

    def init_path(self, path: Path) -> None:
        if path.is_dir():
            self.set_scan_folder(path)
            return

        if path.is_file():
            self.load_scan(path)
            return

        # Not a real path yet (e.g. in tests). Leave UI usable.
        if self.patari_controller.scan_browser is not None:
            self.patari_controller.scan_browser.set_folder(path)

    def on_browse_folder_clicked(self) -> None:
        # start_path = str(
        #     self.patari_controller.path
        #     if self.patari_controller.path.exists()
        #     else Path.cwd()
        # )

        dialog = QFileDialog(
            None,
            "Select folder or HDF5 scan file",
            str(Path.cwd()),
        )
        dialog.setFileMode(QFileDialog.Directory)

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
            self.set_scan_folder(target.parent)
            scan_paths = list(self.patari_controller._scans.keys())
            try:
                idx = scan_paths.index(target)
                if self.patari_controller.scan_browser is not None:
                    self.patari_controller.scan_browser.scans_list.setCurrentRow(
                        idx
                    )
            except ValueError:
                self.load_scan(target)

    def on_scan_selected(self, row: int) -> None:
        scan_paths = list(self.patari_controller._scans.keys())
        if row < 0 or row >= len(scan_paths):
            return
        self.load_scan(scan_paths[row])

    def set_scan_folder(self, folder: Path) -> None:
        folder = Path(folder)
        self.patari_controller.study_path = folder

        self.patari_controller._scans = self.discover_scans(folder)

        if self.patari_controller.scan_browser is not None:
            self.patari_controller.scan_browser.set_folder(folder)
            scan_items = [
                (p, info)
                for p, info in self.patari_controller._scans.items()
            ]
            self.patari_controller.scan_browser.set_scans(scan_items)

        # Auto-select first scan if available.
        if (
            self.patari_controller._scans
            and self.patari_controller.scan_browser is not None
        ):
            self.patari_controller.scan_browser.scans_list.setCurrentRow(0)

    def load_scan(self, scan_path: Path) -> None:

        logger.info("loading scan: %s", scan_path)

        scan_path = Path(scan_path)
        self.patari_controller.path = scan_path
        self.reset_scan_state()

        if not scan_path.exists():
            logger.warning("scan not found: %s", scan_path)
            self.patari_controller.refresh_all()
            return

        scan_info = self.patari_controller._scans.get(scan_path)

        try:
            if scan_info.kind == "hdf5":
                self.patari_controller.pa_data = pat.PAData.from_hdf5(
                    str(scan_path), mode="r"
                )
            else:
                self.patari_controller.pa_data = pat.PAData(
                    iTheraMSOT(str(scan_path))
                )
        except Exception:
            logger.exception("failed to open scan '%s'", scan_path)
            self.patari_controller.refresh_all()
            return

        try:
            layers = self.layers_from_pa_data()
        except Exception:
            logger.exception("failed to load '%s'", scan_path)
            self.close_current_scan()
            self.patari_controller.refresh_all()
            return

        for data, kw, lt in layers:
            if lt == "image":
                kw = dict(kw)
                kw.setdefault("metadata", {})
                kw["metadata"].setdefault("filepath", str(scan_path))
                kw["metadata"].setdefault("scan_name", scan_info.internal_name)
                self.viewer.add_image(data, **kw)
                # alternatively set unit here instead of scalebar (deprecated), but doesnt seem to work yet
                # layer = self.viewer.add_image(data, **kw)
                # layer.units = "mm"
            else:
                kw = dict(kw)
                kw.setdefault("metadata", {})
                kw["metadata"].setdefault("filepath", str(scan_path))
                kw["metadata"].setdefault("scan_name", scan_info.internal_name)
                self.viewer.add_labels(data, **kw)

        # Create the ROIs layer after image layers so it stays on top.
        self.patari_controller.shapes_layer = self.viewer.add_shapes(
            name="ROIs",
            edge_color=roi_color_for_index(0),
            face_color="transparent",
            edge_width=0.1,
            ndim=2,
            metadata={"type": "roi"},
        )
        self.patari_controller._connect_shapes_layer_events()

        # After adding layers, pick a sensible default selected layer.
        self.patari_controller._select_default_pa_layer()
        
        # Set the active US layer if available.
        self.patari_controller.active_us_layer = next(
            (
                l
                for l in self.viewer.layers
                if isinstance(l, Image) and l.metadata.get("type") == "us"
            ),
            None,
        )
        self.patari_controller._resolve_active_recon_layer()

        # Initialize viewer position to DEFAULT_FRAME_INDEX and DEFAULT_CHANNEL_INDEX
        try:
            if settings.general.DEFAULT_FRAME_INDEX == "motion":
                # find frame with lowest motion 
                motion_scores = self.patari_controller.active_us_layer.metadata.get("motion_scores")
                frame_id = int(np.argmin(motion_scores))
                logger.info("motion-based frame selection: selected frame %d with motion score %.4f", frame_id, motion_scores[frame_id])
            else:
                frame_id = settings.general.DEFAULT_FRAME_INDEX

            self.viewer.dims.set_point(0, frame_id)
            self.viewer.dims.set_point(1, settings.general.DEFAULT_CHANNEL_INDEX)
        except Exception:
            logger.warning("failed to set initial viewer position. Setting to (0, 0)", exc_info=True)
            self.viewer.dims.set_point(0, 0)
            self.viewer.dims.set_point(1, 0)


        # Populate ROIs after dims are initialized to avoid computing stats before the viewer is ready.
        self.init_shapes_from_scan()

        # Fit view to the newly loaded data (prevents "zoomed out" state).
        try:
            self.viewer.reset_view()
        except Exception:
            logger.info("failed to reset viewer view", exc_info=True)

    @staticmethod
    def scan_key(scan_path: Path) -> str:
        name = scan_path.stem if scan_path.is_file() else scan_path.name
        m = re.match(r"^(Scan_\d+)", name)
        return m.group(1) if m else name

    @staticmethod
    def scan_sort_key(scan_path: Path):
        key = ScanController.scan_key(scan_path)
        m = re.match(r"^Scan_(\d+)$", key)
        if m:
            return (0, int(m.group(1)), key)
        return (1, 0, key)

    @staticmethod
    def _read_internal_scan_name(path: Path) -> str | None:
        """
        Read the internal scan name. 
        For native ithera, we read it from the .msot XML file instead of constructing the entire iTheraMSOT object,
        For hdf5 we read it from the HDF5 metadata (cheap)
        """
        try:
            if path.is_file() and path.suffix.lower() == ".hdf5":
                from patato.io.hdf.hdf5_interface import HDF5Reader

                reader = HDF5Reader(str(path))
                name = reader.get_scan_name()
                reader.close()
                return str(name) if name else None
            elif path.is_dir():
                # iTheraMSOT.__init__ parses all frame data —> too expensive
                # Parse only the relevant XML node directly.
                import xml.dom.minidom

                msot = path / f"{path.name}.msot"
                if msot.exists():
                    tree = xml.dom.minidom.parse(str(msot))
                    scan_nodes = tree.getElementsByTagName("ScanNode")
                    if scan_nodes:
                        name_nodes = scan_nodes[0].getElementsByTagName("Name")
                        if name_nodes and name_nodes[0].firstChild:
                            return name_nodes[0].firstChild.nodeValue.strip()
        except Exception:
            logger.debug(
                "failed to read internal scan name from '%s'",
                path,
                exc_info=True,
            )
        return None

    @staticmethod
    def discover_scans(folder: Path) -> dict[Path, ScanInfo]:
        # One entry per scan key; if both exist, prefer HDF5 over iThera folder.
        by_key: dict[str, tuple[Path, str, str | None]] = {}

        for p in folder.glob("Scan_*.hdf5"):
            internal = ScanController._read_internal_scan_name(p)
            by_key[ScanController.scan_key(p)] = (p, "hdf5", internal)

        for d in folder.glob("Scan_*"):
            if not d.is_dir():
                continue
            if any(d.glob("*.msot")):
                key = ScanController.scan_key(d)
                if key not in by_key:
                    internal = ScanController._read_internal_scan_name(d)
                    by_key[key] = (d, "ithera", internal)

        entries = sorted(
            ((v[0], v[1], v[2]) for v in by_key.values()),
            key=lambda item: ScanController.scan_sort_key(item[0]),
        )
        return {p: ScanInfo(kind=k, internal_name=n) for p, k, n in entries}

    def layers_from_pa_data(self) -> list[tuple]:
        """Build napari LayerData tuples from the open ``controller.pa_data`` handle."""
        layers, self.patari_controller._patato_objects = build_napari_layers(
            self.patari_controller.pa_data
        )
        return layers

    def get_fov(self) -> "tuple[float, float] | None":
        """Return ``(fov_x_m, fov_y_m)`` from stored PATATO objects, or ``None``."""
        return fov_from_objects(self.patari_controller._patato_objects)

    def init_shapes_from_scan(self) -> None:
        """Clear the ROIs layer and populate it with any ROIs stored in the scan."""
        if self.patari_controller.shapes_layer is None:
            return

        try:
            # Disconnect the data-change handler for the duration of the bulk
            # operation — otherwise it fires once per shape.add(), triggering
            # redundant compute_roi_stats calls and table refreshes.
            self.patari_controller.shapes_layer.events.data.disconnect(
                self.patari_controller._on_shapes_data_changed
            )

            shapes: list = []
            self.patari_controller.shapes_layer.data = []
            fov = (
                self.get_fov()
                if self.patari_controller.pa_data is not None
                else None
            )
            if fov is not None:
                shapes = napari_shapes_from_scan_rois(
                    self.patari_controller.pa_data, *fov
                )
                for verts, stype, _, _ in shapes:
                    self.patari_controller.shapes_layer.add(
                        verts, shape_type=stype
                    )

                # Auto select the loaded ROIs for convenience and to activate the button
                if shapes:
                    self.patari_controller.shapes_layer.selected_data = set(range(len(shapes)))

                # add roi_position property to shapes layer
                props = dict(
                    getattr(
                        self.patari_controller.shapes_layer, "properties", {}
                    )
                    or {}
                )
                props["roi_position"] = [pos for _, _, pos, _ in shapes]
                props["roi_source"] = [src for _, _, _, src in shapes]
                self.patari_controller.shapes_layer.properties = props

                if shapes:
                    logger.info("loaded %s ROI(s) from scan", len(shapes))

            self.patari_controller.shapes_layer.events.data.connect(
                self.patari_controller._on_shapes_data_changed
            )

        except Exception:
            logging.exception("failed to initialize ROIs from scan data")
            pass
        # Single refresh at the end regardless of success/failure.
        self.patari_controller._on_shapes_data_changed()

    def export_hdf5(self, destination: Path) -> bool:
        """Export scan to HDF5 including PATARI ROIs and derived datasets."""
        return export_scan_to_hdf5(self.patari_controller, destination)

    def on_hdf5_export_clicked(self, event=None) -> None:
        destination = self._choose_export_path()
        if destination is None:
            return
        self.export_hdf5(destination)

    def _choose_export_path(self) -> Path | None:
        if self.patari_controller.pa_data is None:
            logger.warning("no scan loaded")
            return None

        default_name = (
            f"{Path(self.patari_controller.path).stem}.hdf5"
            if getattr(self.patari_controller, "path", None)
            else "export.hdf5"
        )
        filename, _ = QFileDialog.getSaveFileName(
            None,
            "Export scan as HDF5",
            str(
                (
                    Path(self.patari_controller.path).parent
                    if getattr(self.patari_controller, "path", None)
                    else Path.cwd()
                )
                / default_name
            ),
            "HDF5 files (*.hdf5 *.h5)",
        )
        if not filename:
            return None
        return Path(filename)
