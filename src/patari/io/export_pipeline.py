from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

import h5py
import numpy as np
import patato as pat
from qtpy.QtWidgets import QFileDialog

from patari import __version__
from patari.config import settings
from patari.config.config import CONFIG_SCHEMA_VERSION
from patari.patato_bridge import napari_shapes_to_patato_rois
from patato.io.attribute_tags import HDF5Tags


logger = logging.getLogger(__name__)

PATARI_FILE_FORMAT_VERSION = 2  # increment if the HDF5 file format changes in a way that breaks backward compatibility
PATARI_SOURCE_URL = "https://github.com/Mo-Sc/PATARI"
PATARI_DOCS_URL = "https://mo-sc.github.io/PATARI/"
PATARI_PUBLICATION_DOI = "DOI pending publication"  # TODO: fill in once published


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
        logger.error("export target already exists: %s", destination)
        return False

    try:
        controller.pa_data.save_hdf5(str(destination))
        _write_file_origin(destination)
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


def _write_file_origin(destination: Path) -> None:
    file_origin = {
        "tool": "PATARI",
        "tool_version": __version__,
        "operator": settings.general.OPERATOR,
        "creation_time": dt.datetime.now(dt.timezone.utc).isoformat(),
        "format_version": PATARI_FILE_FORMAT_VERSION,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "source_url": PATARI_SOURCE_URL,
        "documentation_url": PATARI_DOCS_URL,
        "publication_doi": PATARI_PUBLICATION_DOI,

    }
    with h5py.File(destination, "r+") as file:
        file.attrs[HDF5Tags.FILE_ORIGIN] = json.dumps(file_origin)


def _write_rois(controller, destination_pa_data) -> None:
    if controller.shapes_layer is None or controller.shapes_layer.data is None:
        return

    controller.roi_ctrl.sync_records_from_shapes()
    records = controller.roi_ctrl.roi_records
    if not records:
        return

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
    z_values = controller.pa_data.scan_reader.get_scanner_z_position()
    run_values = controller.pa_data.scan_reader.get_run_numbers()
    rep_values = controller.pa_data.scan_reader.get_repetition_numbers()
    channel_idx = int(controller.viewer.dims.current_step[1])

    for record in records:
        frame_idx = int(record.frame_id)
        try:
            z = z_values[frame_idx, channel_idx]
            run = run_values[frame_idx, channel_idx]
            rep = rep_values[frame_idx, channel_idx]
        except (IndexError, KeyError):
            z, run, rep = 0, 0, 0
        roi = napari_shapes_to_patato_rois(
            [np.asarray(record.verts, dtype=float)],
            [record.kind],
            [record.position],
            fov_x_m,
            fov_y_m,
            z,
            run,
            rep,
            frame_idx,
            roi_class=export_roi_class,
            roi_ids=[record.roi_id],
            roi_group_ids=[record.roi_group_id],
        )[0]
        destination_pa_data.add_roi(roi, generated=True)

    logger.info("saved %s PATARI ROI(s)", len(records))


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
