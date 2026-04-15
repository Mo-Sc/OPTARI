from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import numpy as np
import patato as pat
from qtpy.QtWidgets import QFileDialog

from patari.patato_bridge import napari_shapes_to_patato_rois


logger = logging.getLogger(__name__)


def export_roi_table_to_xlsx(df_saved) -> str | None:
    """Prompt for a file path and export the ROI table as an XLSX file."""
    filename, _ = QFileDialog.getSaveFileName(
        None,
        "Save ROIs as Excel",
        "roi_data.xlsx",
        "Excel Files (*.xlsx)",
    )
    if not filename:
        return None
    if not filename.endswith(".xlsx"):
        filename += ".xlsx"

    df_saved.to_excel(filename, index=False)
    return filename


def export_scan_to_hdf5(controller, destination: Path) -> bool:
    """Export scan data and PATARI additions (ROIs and derived images)."""
    if controller.pa_data is None:
        logger.warning("no scan loaded")
        return False

    destination = Path(destination)
    if destination.suffix.lower() not in {".hdf5", ".h5"}:
        destination = destination.with_suffix(".hdf5")
    if destination.exists():
        logger.warning("export target already exists: %s", destination)
        return False

    try:
        controller.pa_data.save_hdf5(str(destination))
    except Exception:
        logger.exception("failed to export scan to HDF5")
        return False

    destination_pa_data = None
    try:
        destination_pa_data = pat.PAData.from_hdf5(str(destination), mode="r+")
        _write_rois(controller, destination_pa_data)
        _write_derived_images(controller, destination_pa_data)
        logger.info("exported scan to %s", destination)
        return True
    except Exception:
        logger.exception("exported scan, but failed to write PATARI additions")
        return False
    finally:
        if destination_pa_data is not None:
            try:
                destination_pa_data.close()
            except Exception:
                pass


def _write_rois(controller, destination_pa_data) -> None:
    if controller.shapes_layer is None or controller.shapes_layer.data is None:
        return

    # Use the current slice to annotate ROI acquisition context.
    frame_idx = int(controller.viewer.dims.current_step[0])
    channel_idx = int(controller.viewer.dims.current_step[1])

    try:
        z = int(
            controller.pa_data.scan_reader.get_scanner_z_position()[
                frame_idx, channel_idx
            ]
        )
        run = int(
            controller.pa_data.scan_reader.get_run_numbers()[
                frame_idx, channel_idx
            ]
        )
        rep = int(
            controller.pa_data.scan_reader.get_repetition_numbers()[
                frame_idx, channel_idx
            ]
        )
    except Exception:
        logger.exception(
            "failed to read z/run/repetition when exporting ROIs; defaulting to 0"
        )
        z, run, rep = 0, 0, 0

    shapes_snapshot = [
        np.asarray(verts, dtype=float)
        for verts in controller.shapes_layer.data
    ]
    shape_types_snapshot = list(controller.shapes_layer.shape_type)
    roi_positions_snapshot = list(
        controller.shapes_layer.properties["roi_position"]
    )

    # Overwrite PATARI-created ROI groups while preserving non-PATARI groups.
    existing_rois = dict(destination_pa_data.get_rois())
    patari_groups_to_delete: set[str] = set()
    for (name_position, _number), roi in list(existing_rois.items()):
        if not str(getattr(roi, "roi_class", "")).startswith("PATARI"):
            continue
        patari_groups_to_delete.add(str(name_position))

    for name_position in patari_groups_to_delete:
        destination_pa_data.delete_rois(name_position=name_position)

    fov_x_m, fov_y_m = controller._get_fov()
    export_roi_class = f"PATARI_{dt.datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    rois = napari_shapes_to_patato_rois(
        shapes_snapshot,
        shape_types_snapshot,
        roi_positions_snapshot,
        fov_x_m,
        fov_y_m,
        z,
        run,
        rep,
        frame_idx,
        roi_class=export_roi_class,
    )
    for roi in rois:
        destination_pa_data.add_roi(roi, generated=True)

    logger.info("saved %s PATARI ROI(s)", len(rois))


def _write_derived_images(controller, destination_pa_data) -> None:
    if not controller._derived_patato_objects:
        return

    # Keep export logic simple: write all runtime-generated derived datasets.
    for image in controller._derived_patato_objects.values():
        # Sanitize attributes to make them h5py-compatible (fix numpy string dtypes).
        _sanitize_image_attributes(image)
        destination_pa_data.scan_writer.add_image(image)

    logger.info(
        "saved %s derived image dataset(s)",
        len(controller._derived_patato_objects),
    )


def _sanitize_image_attributes(image) -> None:
    """Clean image attributes in place to ensure h5py compatibility."""
    if not hasattr(image, "attributes"):
        return

    attrs = image.attributes
    for key in list(attrs.keys()):
        val = attrs[key]
        # Convert numpy string arrays to Python lists of strings (h5py-safe).
        if isinstance(val, np.ndarray) and val.dtype.kind == "U":
            attrs[key] = val.tolist()
        # Convert single numpy strings to Python strings.
        elif isinstance(val, (np.str_, np.bytes_)):
            attrs[key] = str(val)
        # Convert dict values recursively for nested attributes.
        elif isinstance(val, dict):
            for nested_key in list(val.keys()):
                nested_val = val[nested_key]
                if (
                    isinstance(nested_val, np.ndarray)
                    and nested_val.dtype.kind == "U"
                ):
                    val[nested_key] = nested_val.tolist()
                elif isinstance(nested_val, (np.str_, np.bytes_)):
                    val[nested_key] = str(nested_val)
