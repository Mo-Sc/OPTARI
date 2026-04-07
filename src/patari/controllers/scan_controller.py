from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import patato as pat
from patato.io.ithera.read_ithera import iTheraMSOT

from patari.patato_bridge import (
    build_napari_layers,
    fov_from_objects,
    napari_shapes_to_patato_rois,
    napari_shapes_from_scan_rois,
)
from patari.utils.misc import roi_color_for_index


class ScanController:
    """Scan/session lifecycle and data-loading helpers for PATARI."""

    @staticmethod
    def wavelengths(controller) -> "list[int] | None":
        """Return scan wavelengths in nm, or ``None`` if unavailable."""
        if controller.pa_data is None:
            return None
        try:
            return [int(w) for w in controller.pa_data.get_wavelengths()]
        except Exception as e:
            print(
                f"PATARI: failed to read wavelengths from scan metadata: {e}"
            )
            return None

    @staticmethod
    def timestamps(controller) -> "np.ndarray | None":
        """Return scan timestamps array, or ``None`` if unavailable."""
        if controller.pa_data is None:
            return None
        try:
            return np.array(controller.pa_data.get_timestamps())
        except Exception as e:
            print(f"PATARI: failed to read timestamps from scan metadata: {e}")
            return None

    @staticmethod
    def close_current_scan(controller) -> None:
        """Close the HDF5 handle for the current scan."""
        if controller.pa_data is None:
            return
        try:
            controller.pa_data.close()
        except Exception:
            pass
        controller.pa_data = None
        controller._patato_objects = {}

    @staticmethod
    def reset_scan_state(controller) -> None:
        """Clear current scan state and remove all viewer layers."""
        ScanController.close_current_scan(controller)

        for layer in list(controller.viewer.layers):
            controller.viewer.layers.remove(layer)
        controller.active_layer = None
        controller.shapes_layer = None

    @staticmethod
    def init_path(controller, path: Path) -> None:
        if path.is_dir():
            ScanController.set_scan_folder(controller, path)
            return

        if path.is_file():
            ScanController.load_scan(controller, path)
            return

        # Not a real path yet (e.g. in tests). Leave UI usable.
        if controller.scan_browser is not None:
            controller.scan_browser.set_folder(path)

    @staticmethod
    def set_scan_folder(controller, folder: Path) -> None:
        folder = Path(folder)
        controller.study_path = folder

        controller._scans = ScanController.discover_scans(folder)

        if controller.scan_browser is not None:
            controller.scan_browser.set_folder(folder)
            controller.scan_browser.set_scans(list(controller._scans.keys()))

        # Auto-select first scan if available.
        if controller._scans and controller.scan_browser is not None:
            controller.scan_browser.scans_list.setCurrentRow(0)

    @staticmethod
    def load_scan(controller, scan_path: Path) -> None:
        scan_path = Path(scan_path)
        controller.path = scan_path
        ScanController.reset_scan_state(controller)

        if not scan_path.exists():
            print(f"PATARI: scan not found: {scan_path}")
            controller.refresh_all()
            return

        scan_kind = controller._scans.get(
            scan_path,
            (
                "hdf5"
                if scan_path.suffix.lower() in {".hdf5", ".h5"}
                else "ithera"
            ),
        )

        try:
            if scan_kind == "hdf5":
                controller.pa_data = pat.PAData.from_hdf5(
                    str(scan_path), mode="r"
                )
            else:
                controller.pa_data = pat.PAData(iTheraMSOT(str(scan_path)))
        except Exception as e:
            print(f"PATARI: failed to open scan '{scan_path}': {e}")
            controller.refresh_all()
            return

        try:
            layers = ScanController.layers_from_pa_data(controller)
        except Exception as e:
            print(f"PATARI: failed to load '{scan_path}': {e}")
            ScanController.close_current_scan(controller)
            controller.refresh_all()
            return

        for data, kw, lt in layers:
            if lt == "image":
                kw = dict(kw)
                kw.setdefault("metadata", {})
                kw["metadata"].setdefault("filepath", str(scan_path))
                controller.viewer.add_image(data, **kw)
            else:
                kw = dict(kw)
                kw.setdefault("metadata", {})
                kw["metadata"].setdefault("filepath", str(scan_path))
                controller.viewer.add_labels(data, **kw)

        # Create a fresh ROIs layer after image/label layers so it stays on top.
        controller.shapes_layer = controller.viewer.add_shapes(
            name="ROIs",
            edge_color=roi_color_for_index(0),
            face_color="transparent",
            edge_width=0.1,
            ndim=2,
            metadata={"type": "roi"},
        )
        controller._connect_shapes_layer_events()

        # After adding layers, pick a sensible default selected layer.
        controller._select_default_pa_layer()
        controller._resolve_active_layer()

        # Initialize viewer position to middle frame/wav for each scan.
        try:
            data = np.asarray(controller.active_layer.data)
            if data.ndim >= 2:
                controller.viewer.dims.set_point(
                    0, int((data.shape[0] - 1) // 2)
                )
                controller.viewer.dims.set_point(
                    1, int((data.shape[1] - 1) // 2)
                )
        except Exception:
            print("PATARI: failed to set initial viewer position")
            pass

        # Populate ROIs after dims are initialized to avoid computing stats before the viewer is ready.
        ScanController.init_shapes_from_scan(controller)

        # Fit view to the newly loaded data (prevents "zoomed out" state).
        try:
            controller.viewer.reset_view()
        except Exception:
            pass

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
    def discover_scans(folder: Path) -> dict[Path, str]:
        # One entry per scan key; if both exist, prefer HDF5 over iThera folder.
        by_key: dict[str, tuple[Path, str]] = {}

        for p in folder.glob("Scan_*.hdf5"):
            by_key[ScanController.scan_key(p)] = (p, "hdf5")

        for d in folder.glob("Scan_*"):
            if not d.is_dir():
                continue
            if any(d.glob("*.msot")):
                key = ScanController.scan_key(d)
                if key not in by_key:
                    by_key[key] = (d, "ithera")

        entries = sorted((v[0], v[1]) for v in by_key.values())
        entries.sort(key=lambda item: ScanController.scan_sort_key(item[0]))
        return {p: k for p, k in entries}

    @staticmethod
    def layers_from_pa_data(controller) -> list[tuple]:
        """Build napari LayerData tuples from the open ``controller.pa_data`` handle."""
        layers, controller._patato_objects = build_napari_layers(
            controller.pa_data
        )
        return layers

    @staticmethod
    def get_fov(controller) -> "tuple[float, float] | None":
        """Return ``(fov_x_m, fov_y_m)`` from stored PATATO objects, or ``None``."""
        return fov_from_objects(controller._patato_objects)

    @staticmethod
    def init_shapes_from_scan(controller) -> None:
        """Clear the ROIs layer and populate it with any ROIs stored in the scan."""
        if controller.shapes_layer is None:
            return

        # Disconnect the data-change handler for the duration of the bulk
        # operation — otherwise it fires once per shape.add(), triggering
        # redundant compute_roi_stats calls and table refreshes.
        try:
            controller.shapes_layer.events.data.disconnect(
                controller._on_shapes_data_changed
            )
        except Exception:
            pass

        shapes: list = []
        try:
            controller.shapes_layer.data = []
            fov = (
                ScanController.get_fov(controller)
                if controller.pa_data is not None
                else None
            )
            if fov is not None:
                shapes = napari_shapes_from_scan_rois(controller.pa_data, *fov)
                for verts, stype in shapes:
                    controller.shapes_layer.add(verts, shape_type=stype)
                if shapes:
                    print(f"PATARI: loaded {len(shapes)} ROI(s) from scan")
        finally:
            try:
                controller.shapes_layer.events.data.connect(
                    controller._on_shapes_data_changed
                )
            except Exception:
                pass
            # Single refresh at the end regardless of success/failure.
            controller._on_shapes_data_changed()

    @staticmethod
    def export_hdf5(controller, destination: Path) -> bool:
        """Export the current scan to a new HDF5 file and persist live ROIs.

        Returns ``True`` on success, ``False`` on failure.
        """
        if controller.pa_data is None:
            print("PATARI: no scan loaded")
            return False

        destination = Path(destination)
        if destination.suffix.lower() not in {".hdf5", ".h5"}:
            destination = destination.with_suffix(".hdf5")
        if destination.exists():
            print(f"PATARI: export target already exists: {destination}")
            return False

        try:
            controller.pa_data.save_hdf5(str(destination))
        except Exception as e:
            print(f"PATARI: failed to export scan to HDF5: {e}")
            return False

        if controller.shapes_layer is None:
            print(f"PATARI: exported scan to {destination} (no ROIs layer)")
            return True

        fov = ScanController.get_fov(controller)
        if fov is None:
            print(
                f"PATARI: exported scan to {destination} (ROIs skipped: no FOV)"
            )
            return True

        fov_x_m, fov_y_m = fov
        pt = list(controller.viewer.dims.point)
        frame_idx = int(round(pt[0])) if pt else 0
        try:
            z = float(
                controller.pa_data.scan_reader.get_scanner_z_position()[
                    frame_idx, 0
                ]
            )
            run = float(
                controller.pa_data.scan_reader.get_run_numbers()[frame_idx, 0]
            )
            rep = float(
                controller.pa_data.scan_reader.get_repetition_numbers()[
                    frame_idx, 0
                ]
            )
        except Exception:
            z, run, rep = 0.0, 0.0, 0.0

        shapes_snapshot = [
            np.asarray(v, dtype=float) for v in controller.shapes_layer.data
        ]
        shape_types_snapshot = list(controller.shapes_layer.shape_type)

        try:
            destination_pa_data = pat.PAData.from_hdf5(
                str(destination), mode="r+"
            )
        except Exception as e:
            print(
                f"PATARI: exported scan, but failed to reopen destination: {e}"
            )
            return False

        try:
            # Replace any ROIs copied by the base PATATO export with the
            # current live napari shapes.
            destination_pa_data.delete_rois()
            rois = napari_shapes_to_patato_rois(
                shapes_snapshot,
                shape_types_snapshot,
                fov_x_m,
                fov_y_m,
                z,
                run,
                rep,
                frame_idx,
            )
            for roi in rois:
                destination_pa_data.add_roi(roi, generated=True)
            if not rois:
                print(f"PATARI: exported scan to {destination}; no ROIs saved")
            else:
                print(
                    f"PATARI: exported scan to {destination}; saved {len(rois)} ROI(s)"
                )
            return True
        except Exception as e:
            print(f"PATARI: exported scan, but failed to write ROIs: {e}")
            return False
        finally:
            try:
                destination_pa_data.close()
            except Exception:
                pass
