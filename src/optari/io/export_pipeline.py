"""HDF5 and IPASC scan export, and the ROI table XLSX round-trip.

export_scan_to_hdf5() writes the scan through PATATO's own save_hdf5(), then reopens
the file to rewrite the ROI and derived-data datasets (segmentation mask, derived PA
images, clinical metadata) so in-session OPTARI edits are captured, not just what was
already in the source file. No controller reads a PATATO array or writes an HDF5
attribute directly outside this module and patato_bridge.py.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import tempfile
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import patato as pat
from qtpy.QtWidgets import QFileDialog

from optari import __version__
from optari.config import settings
from optari.config.config import CONFIG_SCHEMA_VERSION
from optari.patato_bridge import patato_roi_from_geometry
from optari.io.utils import filename_token
from optari.roi.roi_features import SAVED_FIXED_SOURCE_COLUMNS
from optari.roi.roi_geometry import RoiGeometry
from optari.roi.roi_utils import saved_export_columns
from patato.io.attribute_tags import HDF5Tags

logger = logging.getLogger(__name__)

OPTARI_FILE_FORMAT_VERSION = 2  # increment if the HDF5 file format changes in a way that breaks backward compatibility
OPTARI_SOURCE_URL = "https://github.com/Mo-Sc/OPTARI"
OPTARI_DOCS_URL = "https://mo-sc.github.io/OPTARI/"
OPTARI_PUBLICATION_DOI = (
    "DOI pending publication"  # TODO: fill in once published
)

# Bump only when the meaning of saved-table columns changes (units, semantics).
# Columns being added or removed can be handled without a schema version bump.
ROI_TABLE_SCHEMA_VERSION = 1
ROI_TABLE_SHEET = "roi_table"
ROI_TABLE_META_SHEET = "optari_meta"


def default_roi_table_filename() -> str:
    """``roi_data_<operator>_<analysis id>_<timestamp>.xlsx``.

    The timestamp is UTC so it matches ``creation_time`` in the provenance sheet.
    """
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        f"roi_data_{filename_token(settings.general.OPERATOR)}"
        f"_{filename_token(settings.general.ANALYSIS_ID)}_{timestamp}.xlsx"
    )


def export_roi_table_to_xlsx(df_saved, path=None) -> str | None:
    """Write the ROI table as an XLSX file, prompting for a path if *path* is None."""

    if path is not None:
        filename = str(path)
    else:
        filename, _ = QFileDialog.getSaveFileName(
            None,
            "Save ROIs as Excel",
            default_roi_table_filename(),
            "Excel Files (*.xlsx)",
        )
        if not filename:
            return None
        if not filename.endswith(".xlsx"):
            filename += ".xlsx"

    meta = file_origin(roi_table_schema_version=ROI_TABLE_SCHEMA_VERSION)
    meta_df = pd.DataFrame(
        {"key": list(meta.keys()), "value": [str(v) for v in meta.values()]}
    )
    with pd.ExcelWriter(Path(filename)) as writer:
        df_saved.to_excel(writer, sheet_name=ROI_TABLE_SHEET, index=False)
        meta_df.to_excel(writer, sheet_name=ROI_TABLE_META_SHEET, index=False)

    return filename


def import_roi_table_from_xlsx(path=None) -> tuple[pd.DataFrame, str] | None:
    """Read a previously exported ROI table, prompting for a file if *path* is None."""
    if path is not None:
        filename = str(path)
    else:
        filename, _ = QFileDialog.getOpenFileName(
            None,
            "Import ROI Analysis Table",
            "",
            "Excel Files (*.xlsx)",
        )
        if not filename:
            return None

    path = Path(filename)

    try:
        meta_df = pd.read_excel(path, sheet_name=ROI_TABLE_META_SHEET)
        meta = dict(zip(meta_df["key"], meta_df["value"]))
    except (ValueError, KeyError) as exc:
        raise ValueError(
            f"'{Path(path).name}' is not a OPTARI ROI table."
        ) from exc

    file_version = str(meta.get("roi_table_schema_version", ""))
    if file_version != str(ROI_TABLE_SCHEMA_VERSION):
        raise ValueError(
            f"ROI table schema version {file_version or 'missing'} cannot be read by "
            f"this OPTARI version, which expects version {ROI_TABLE_SCHEMA_VERSION}."
        )

    df = pd.read_excel(path, sheet_name=ROI_TABLE_SHEET)

    missing_required = [
        c for c in SAVED_FIXED_SOURCE_COLUMNS if c not in df.columns
    ]
    if missing_required:
        raise ValueError(
            f"ROI table is missing required column(s): {', '.join(missing_required)}."
        )

    # Without a group identity a row cannot be grouped or restored, and a blank one
    # would drop out of every groupby silently rather than failing.
    if df["roi_group_uid"].fillna("").astype(str).str.strip().eq("").any():
        raise ValueError("ROI table has row(s) with no roi_group_uid.")

    # Reconcile by name, not position, the export column set follows FEATURE_REGISTRY
    # and can grow between releases without a schema version bump.
    expected = saved_export_columns()
    dropped = [c for c in df.columns if c not in expected]
    added = [c for c in expected if c not in df.columns]
    if dropped:
        logger.warning(
            "ignoring unknown column(s) in %s: %s", path, ", ".join(dropped)
        )
    if added:
        logger.warning(
            "filling absent column(s) in %s: %s", path, ", ".join(added)
        )

    return df.reindex(columns=expected).reset_index(drop=True), filename


def export_scan_to_hdf5(controller, destination: Path) -> bool:
    """Export scan data and OPTARI additions (ROIs and derived images)."""
    if controller.pa_data is None:
        logger.warning("No scan loaded, nothing to export")
        return False

    destination = _hdf5_destination(destination)
    if destination is None:
        return False

    fd, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.stem}-",
        suffix=destination.suffix,
    )
    os.close(fd)
    temporary_destination = Path(temporary_name)
    temporary_destination.unlink()
    destination_pa_data = None
    try:
        controller.pa_data.save_hdf5(str(temporary_destination))
        _write_file_origin(temporary_destination)
        destination_pa_data = pat.PAData.from_hdf5(
            str(temporary_destination), mode="r+"
        )
        _write_rois(controller, destination_pa_data)
        _write_derived_data(controller, destination_pa_data)
        destination_pa_data.close()
        destination_pa_data = None
        temporary_destination.replace(destination)
        logger.info("exported scan to %s", destination)
        return True
    except Exception:
        logger.exception("Failed to export scan to %s", destination.name)
        return False
    finally:
        if destination_pa_data is not None:
            try:
                destination_pa_data.close()
            except Exception:
                pass
        temporary_destination.unlink(missing_ok=True)


def export_scan_to_ipasc(controller, destination: Path) -> bool:
    """Export the raw time series of the loaded scan as a native IPASC file."""
    if controller.pa_data is None:
        logger.warning("No scan loaded, nothing to export")
        return False

    destination = _hdf5_destination(destination)
    if destination is None:
        return False

    try:
        pat.write_ipasc(controller.pa_data.scan_reader, str(destination))
    except Exception:
        logger.exception(
            "Failed to export raw time series to %s", destination.name
        )
        return False

    logger.info("exported raw time series to %s", destination)
    return True


def ipasc_export_report(destination: Path) -> str:
    """Summarise how complete the IPASC metadata of an exported file are.

    Reports which of IPASC's minimal fields are present. Fields IPASC marks "report if
    present" are absent when the source format never recorded them, so their
    absence is not a failure and is not counted here.
    """
    import pacfish as pf
    from pacfish import MetadataAcquisitionTags

    data = pf.load_data(str(destination))
    missing = [
        datum.tag
        for datum in MetadataAcquisitionTags.TAGS
        if datum.mandatory and datum.tag not in data.meta_data_acquisition
    ]
    detectors = data.meta_data_device.get("detectors", {})
    if not detectors:
        missing.append("detector positions")

    if missing:
        return f"IPASC minimal metadata incomplete: {', '.join(missing)} not recorded."
    return f"IPASC minimal metadata complete, {len(detectors)} detection elements."


def _hdf5_destination(destination: Path) -> Path | None:
    """*destination* with an .hdf5 suffix, or None (logged) when a file is already there."""
    destination = Path(destination)
    if destination.suffix.lower() not in {".hdf5", ".h5"}:
        destination = destination.with_suffix(".hdf5")
    if destination.exists():
        logger.error("Not exported, the file already exists: %s", destination)
        return None
    return destination


def file_origin(**extra) -> dict:
    """origin recorded in every file OPTARI writes."""
    return {
        "tool": "OPTARI",
        "tool_version": __version__,
        "operator": settings.general.OPERATOR,
        "analysis_id": settings.general.ANALYSIS_ID,
        "creation_time": dt.datetime.now(dt.timezone.utc).isoformat(),
        "format_version": OPTARI_FILE_FORMAT_VERSION,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "source_url": OPTARI_SOURCE_URL,
        "documentation_url": OPTARI_DOCS_URL,
        "publication_doi": OPTARI_PUBLICATION_DOI,
        **extra,
    }


def _write_file_origin(destination: Path) -> None:
    with h5py.File(destination, "r+") as file:
        file.attrs[HDF5Tags.FILE_ORIGIN] = json.dumps(file_origin())


def _write_rois(controller, destination_pa_data) -> None:
    """Replace OPTARI's ROI groups in the export with the session's own records.

    Annotations from other tools (vendor software, PATATO) are kept as stored.
    An edited one became OPTARI's in the session and is written next to the original.
    """
    roi_ctrl = controller.roi_ctrl
    roi_ctrl.sync_records_from_shapes()

    # Stored OPTARI ROIs that failed to restore are not in the session, so keep them.
    if roi_ctrl.stored_rois_restored:
        stored = destination_pa_data.get_rois()
        for name_position in {
            name
            for (name, _), roi in stored.items()
            if roi.roi_class.startswith("OPTARI")
        }:
            destination_pa_data.delete_rois(name_position=name_position)

    records = [
        r for r in roi_ctrl.roi_records if r.source.startswith("OPTARI")
    ]
    if not records:
        return

    fov_x_m, fov_y_m = controller.scan_ctrl.get_fov()
    z_values = controller.pa_data.scan_reader.get_scanner_z_position()
    run_values = controller.pa_data.scan_reader.get_run_numbers()
    rep_values = controller.pa_data.scan_reader.get_repetition_numbers()

    for record in records:
        frame_idx = int(record.frame_id)
        # Position, run and repetition belong to the frame; every wavelength shares them.
        try:
            z = z_values[frame_idx, 0]
            run = run_values[frame_idx, 0]
            rep = rep_values[frame_idx, 0]
        except (IndexError, KeyError):
            z, run, rep = 0, 0, 0
        roi = patato_roi_from_geometry(
            RoiGeometry.from_record(record, fov_x_m, fov_y_m),
            fov_x_m,
            fov_y_m,
            z=z,
            run=run,
            rep=rep,
            frame_idx=frame_idx,
            roi_id=record.roi_id,
            track_id=record.track_id,
            roi_group_uid=record.roi_group_uid,
        )
        destination_pa_data.add_roi(roi, generated=True)

    logger.info("saved %s OPTARI ROI(s)", len(records))


def _write_derived_data(controller, destination_pa_data) -> None:
    """Write runtime-only OPTARI additions: derived PA images, the segmentation mask, and clinical metadata.

    replaces any existing derived data, segmentation mask, and clinical metadata in the export.
    """
    for image in controller.derived_patato_objects.values():
        destination_pa_data.scan_writer.add_image(image)
    if controller.derived_patato_objects:
        logger.info(
            "saved %s derived image dataset(s)",
            len(controller.derived_patato_objects),
        )

    seg_layer = controller.segmentation_ctrl.seg_layer
    if seg_layer is not None:
        writer = destination_pa_data.scan_writer
        if HDF5Tags.SEGMENTATION in writer.file:
            del writer.file[HDF5Tags.SEGMENTATION]
        writer.set_segmentation(
            np.asarray(seg_layer.data)[:, 0].astype(np.int32)
        )
        meta = {
            "source_model_id": seg_layer.metadata.get("source_model_id", ""),
            "frame_mode": seg_layer.metadata.get("frame_mode", "all"),
            "frames": [int(f) for f in seg_layer.metadata.get("frames", [])],
            "class_names": {
                str(k): v
                for k, v in seg_layer.metadata.get("class_names", {}).items()
            },
        }
        writer.file[HDF5Tags.SEGMENTATION].attrs["optari_meta"] = json.dumps(
            meta
        )
        logger.info(
            "saved segmentation mask (model '%s')", meta["source_model_id"]
        )

    if controller.clinical_metadata_edits is not None:
        destination_pa_data.scan_writer.set_clinical_metadata(
            controller.clinical_metadata_edits
        )
        logger.info(
            "saved clinical metadata (%s field(s))",
            len(controller.clinical_metadata_edits),
        )
