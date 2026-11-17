"""HDF5 and IPASC scan export, and the ROI table XLSX round-trip.

export_scan_to_hdf5() writes the scan through PATATO's own save_hdf5(), then reopens
the file to rewrite the ROI and derived-data datasets (segmentation mask, derived PA
images, clinical metadata) so in-session OPTARI edits are captured, not just what was
already in the source file. save_scan_into_source() writes the same additions into an
OPTARI HDF5 in place, without copying what it already holds. Both, and the IPASC
export, are generators run as background steps. scan_export() takes what they write
from the session beforehand, on the main thread. No controller reads a PATATO array
or writes an HDF5 attribute directly outside this module and patato_bridge.py.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import logging
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import patato as pat
from qtpy.QtWidgets import QFileDialog

from optari import __version__
from optari.config import settings
from optari.config.config import CONFIG_SCHEMA_VERSION
from optari.patato_bridge import LAYER_NAME_ATTR, patato_roi_from_geometry
from optari.io.utils import filename_token
from optari.utils.files import atomic_destination
from optari.roi.roi_features import SAVED_FIXED_SOURCE_COLUMNS
from optari.roi.roi_geometry import RoiGeometry
from optari.roi.roi_records import ROIRecord
from optari.roi.roi_utils import saved_export_columns
from optari.segmentation.segmenter import MASK_DTYPE
from patato.io.attribute_tags import HDF5Tags

logger = logging.getLogger(__name__)

OPTARI_FILE_FORMAT_VERSION = 2  # increment if the HDF5 file format changes in a way that breaks backward compatibility
OPTARI_SOURCE_URL = "https://github.com/Mo-Sc/OPTARI"
OPTARI_DOCS_URL = "https://mo-sc.github.io/OPTARI/"
OPTARI_PUBLICATION_DOI = "10.48550/arXiv.2610.32468"

# Bump only when the meaning of saved-table columns changes (units, semantics).
# Columns being added or removed can be handled without a schema version bump.
# 2: roi_geometry always in scan coordinates, std with ddof=1, timestamps in UTC with
#    offset, derived layers dated by sweep start, lines and paths measured along the line.
ROI_TABLE_SCHEMA_VERSION = 2
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


# One row of an Excel sheet is the header.
XLSX_MAX_ROWS = 1_048_575


def append_roi_table_csv(rows: pd.DataFrame, path: Path) -> None:
    """Append *rows* to the CSV form of the ROI table, creating it with its header first.
    """
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as file:
        if new:
            meta = file_origin(
                roi_table_schema_version=ROI_TABLE_SCHEMA_VERSION
            )
            file.write(f"# {json.dumps(meta)}\n")
        rows.to_csv(file, header=new, index=False)


def write_roi_table_csv(rows: pd.DataFrame, path: Path) -> None:
    """Rewrite the CSV ROI table with *rows*, atomically (after a delete)."""
    with atomic_destination(path) as temporary:
        append_roi_table_csv(rows, temporary)


def export_roi_table_to_xlsx(df_saved, path=None) -> str | None:
    """Write the ROI table as an XLSX file, prompting for a path if *path* is None.

    Raises ValueError for a table larger than one Excel sheet.
    """
    if len(df_saved) > XLSX_MAX_ROWS:
        raise ValueError(
            f"{len(df_saved)} rows do not fit in an Excel sheet "
            f"({XLSX_MAX_ROWS} at most). The CSV form holds them all."
        )

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
    # Atomic, since a half-written file would replace the user's earlier table
    with (
        atomic_destination(Path(filename)) as temporary,
        pd.ExcelWriter(temporary) as writer,
    ):
        df_saved.to_excel(writer, sheet_name=ROI_TABLE_SHEET, index=False)
        meta_df.to_excel(writer, sheet_name=ROI_TABLE_META_SHEET, index=False)

    return filename


def import_roi_table(path=None) -> tuple[pd.DataFrame, str] | None:
    """Read an exported ROI table (XLSX) or a CSV backup, prompting if *path* is None."""
    if path is not None:
        filename = str(path)
    else:
        filename, _ = QFileDialog.getOpenFileName(
            None,
            "Import ROI Analysis Table",
            "",
            "ROI tables (*.xlsx *.csv)",
        )
        if not filename:
            return None

    path = Path(filename)

    # Folder names identify the scan when restoring: "001" must not come back as 1
    text_columns = {"study_folder": str, "scan_folder": str, "scan_name": str}
    try:
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8") as file:
                meta = json.loads(file.readline().removeprefix("# "))
        else:
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

    df = (
        pd.read_csv(path, skiprows=1, dtype=text_columns)
        if path.suffix.lower() == ".csv"
        else pd.read_excel(
            path, sheet_name=ROI_TABLE_SHEET, dtype=text_columns
        )
    )

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


@dataclass(frozen=True)
class ScanExport:
    """Everything an HDF5 write takes from the session.
    Copied on the main thread.

    The write runs in a worker while the user keeps working, so it must not read the
    viewer, the ROI layer or the controllers, which may change underneath it.
    """

    pa_data: pat.PAData
    path: Path | None
    # OPTARI's own ROIs. Other tools' annotations stay as the file stores them.
    rois: list[ROIRecord]
    # False when stored OPTARI ROIs failed to restore: they are not in the session,
    # so they must be kept.
    replace_stored_rois: bool
    fov: tuple[float, float] | None
    derived: dict
    # The segmentation layer's mask (n_frames, H, W) and metadata
    segmentation: tuple[np.ndarray, dict] | None
    clinical_metadata: dict | None


def scan_export(controller) -> ScanExport:
    """Snapshot what the loaded scan's HDF5 export writes. Main thread only."""
    roi_ctrl = controller.roi_ctrl
    roi_ctrl.sync_records_from_shapes()
    seg_layer = controller.segmentation_ctrl.seg_layer
    return ScanExport(
        pa_data=controller.pa_data,
        path=controller.path,
        rois=copy.deepcopy(
            [r for r in roi_ctrl.roi_records if r.source.startswith("OPTARI")]
        ),
        replace_stored_rois=roi_ctrl.stored_rois_restored,
        fov=controller.scan_ctrl.get_fov(),
        derived=dict(controller.derived_patato_objects),
        segmentation=(
            None
            if seg_layer is None
            else (
                np.asarray(seg_layer.data)[:, 0].astype(MASK_DTYPE),
                dict(seg_layer.metadata),
            )
        ),
        clinical_metadata=controller.clinical_metadata_edits,
    )


def export_scan_to_hdf5(
    export: ScanExport, destination: Path
) -> Generator[None, None, None]:
    """Write the scan and OPTARI's additions to a new HDF5 file. A background step.

    Raises FileExistsError rather than replace a file, and a failed or cancelled
    export leaves no file behind.
    """
    destination = _hdf5_destination(destination)
    with atomic_destination(destination) as temporary:
        export.pa_data.save_hdf5(str(temporary))
        _write_file_origin(temporary)
        yield
        exported = pat.PAData.from_hdf5(str(temporary), mode="r+")
        try:
            _write_rois(export, exported)
            yield
            _write_derived_data(export, exported)
        finally:
            # Closed before the move, which Windows refuses for an open file.
            exported.close()
    logger.info("exported scan to %s", destination)


def can_save_into_scan(controller) -> bool:
    """Whether the loaded scan is an HDF5 file OPTARI wrote, the only kind it writes into."""
    if controller.scan_info.kind != "hdf5":
        return False
    origin = controller.pa_data.get_file_origin()
    return origin is not None and origin.get("tool") == "OPTARI"


def save_scan_into_source(export: ScanExport) -> Generator[None, None, None]:
    """Write the session's ROIs and new layers into the scan file itself. A background step.

    The session's read handle on the file must be closed first
    (``ScanController.reset_scan_state``), since HDF5 refuses a second, writing one.
    Stored images stay as they are and only the session's layers are written, each
    replacing a stored one of the same name. A stored layer removed from the viewer
    stays in the file. Unlike export this is not atomic.
    """
    scan = pat.PAData.from_hdf5(str(export.path), mode="r+")
    try:
        _write_rois(export, scan)
        yield
        _write_derived_data(export, scan)
    finally:
        scan.close()
    logger.info("saved into %s", export.path)


def export_scan_to_ipasc(
    pa_data: pat.PAData, destination: Path
) -> Generator[None, None, None]:
    """Export the raw time series as a native IPASC file. A background step.

    Raises FileExistsError rather than replace a file. Atomic, since a partial file
    would make the next attempt refuse to overwrite it.
    """
    destination = _hdf5_destination(destination)
    # PATATO's writer reports no progress, so this is the only point a cancel acts on
    yield
    with atomic_destination(destination) as temporary:
        pat.write_ipasc(pa_data.scan_reader, str(temporary))
    logger.info("exported raw time series to %s", destination)


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


def _hdf5_destination(destination: Path) -> Path:
    """*destination* with an .hdf5 suffix. Raises FileExistsError if a file is there."""
    destination = Path(destination)
    if destination.suffix.lower() not in {".hdf5", ".h5"}:
        destination = destination.with_suffix(".hdf5")
    if destination.exists():
        raise FileExistsError(
            f"Not exported, {destination.name} already exists"
        )
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


def _write_rois(export: ScanExport, destination_pa_data) -> None:
    """Replace OPTARI's ROI groups in the file with the session's own records.

    Annotations from other tools (vendor software, PATATO) are kept as stored.
    An edited one became OPTARI's in the session and is written next to the original.
    """
    if export.replace_stored_rois:
        stored = destination_pa_data.get_rois()
        for name_position in {
            name
            for (name, _), roi in stored.items()
            if roi.roi_class.startswith("OPTARI")
        }:
            destination_pa_data.delete_rois(name_position=name_position)

    records = export.rois
    if not records:
        return

    fov = export.fov
    if fov is None:
        raise ValueError(
            "the scan has no field of view (no ultrasound or reconstruction), "
            "so its ROIs cannot be placed"
        )
    fov_x_m, fov_y_m = fov
    # Read from the destination, which holds the same arrays: when saving into the
    # scan file, the session's own handle is already closed.
    reader = destination_pa_data.scan_reader
    z_values = reader.get_scanner_z_position()
    run_values = reader.get_run_numbers()
    rep_values = reader.get_repetition_numbers()

    for record in records:
        frame_idx = int(record.frame_id)
        # A frame outside the scan is a corrupt record. Writing it with made-up
        # acquisition coordinates would hide that.
        if not 0 <= frame_idx < z_values.shape[0]:
            raise ValueError(
                f"ROI {record.roi_id} is on frame {frame_idx}, but the scan has "
                f"{z_values.shape[0]} frames"
            )
        roi = patato_roi_from_geometry(
            RoiGeometry.from_record(record, fov_x_m, fov_y_m),
            fov_x_m,
            fov_y_m,
            # Position, run and repetition belong to the frame; every wavelength shares them.
            z=z_values[frame_idx, 0],
            run=run_values[frame_idx, 0],
            rep=rep_values[frame_idx, 0],
            frame_idx=frame_idx,
            roi_id=record.roi_id,
            track_id=record.track_id,
            roi_group_uid=record.roi_group_uid,
        )
        destination_pa_data.add_roi(roi, generated=True)

    logger.info("saved %s OPTARI ROI(s)", len(records))


def _delete_stored_layer(file: h5py.File, group: str, layer_name: str) -> None:
    """Delete every dataset in *group* stored under *layer_name*.

    HDF5 does not reclaim the space, so saving in place grows the file; an export is
    compact.
    """
    for subgroup in file.get(group, {}).values():
        for name, dataset in list(subgroup.items()):
            if dataset.attrs.get(LAYER_NAME_ATTR) == layer_name:
                del subgroup[name]
                logger.info("replacing stored layer '%s'", layer_name)


def _write_derived_data(export: ScanExport, destination_pa_data) -> None:
    """Write runtime-only OPTARI additions: derived PA images, the segmentation mask, and clinical metadata.

    replaces any existing derived data, segmentation mask, and clinical metadata in the export.
    Each new image carries its own origin, since a file saved into several times holds
    layers from different sessions while the file-level origin records only its creation.
    """
    origin = json.dumps(file_origin())
    writer = destination_pa_data.scan_writer
    for layer_name, image in export.derived.items():
        # Same layer name means same result (a different one needs a suffix), so a
        # re-run replaces what an earlier save stored under that name.
        _delete_stored_layer(
            writer.file, image.get_hdf5_group_name(), layer_name
        )
        image.attributes[HDF5Tags.FILE_ORIGIN] = origin
        writer.add_image(image)
    if export.derived:
        logger.info("saved %s derived image dataset(s)", len(export.derived))

    if export.segmentation is not None:
        mask, layer_meta = export.segmentation
        if HDF5Tags.SEGMENTATION in writer.file:
            del writer.file[HDF5Tags.SEGMENTATION]
        writer.set_segmentation(mask)
        meta = {
            "source_model_id": layer_meta.get("source_model_id", ""),
            "frame_mode": layer_meta.get("frame_mode", "all"),
            "frames": [int(f) for f in layer_meta.get("frames", [])],
            "class_names": {
                str(k): v for k, v in layer_meta.get("class_names", {}).items()
            },
        }
        writer.file[HDF5Tags.SEGMENTATION].attrs["optari_meta"] = json.dumps(
            meta
        )
        logger.info(
            "saved segmentation mask (model '%s')", meta["source_model_id"]
        )

    if export.clinical_metadata is not None:
        writer.set_clinical_metadata(export.clinical_metadata)
        logger.info(
            "saved clinical metadata (%s field(s))",
            len(export.clinical_metadata),
        )
