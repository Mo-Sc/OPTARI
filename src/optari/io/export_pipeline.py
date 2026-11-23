"""HDF5 and IPASC scan export.

export_scan_to_hdf5() writes the scan through PATATO's own save_hdf5(), then reopens
the file to rewrite the ROI and derived-data datasets (segmentation mask, derived PA
images, clinical metadata) so in-session OPTARI edits are captured, not just what was
already in the source file. save_scan_into_source() writes the same additions into an
OPTARI HDF5 in place, without copying what it already holds. Both, and the IPASC
export, are generators run as background steps, and headless: they take a ScanExport,
which ScanController.export_snapshot() copies from the session beforehand, on the main
thread. Only this module and patato_bridge.py write HDF5 attributes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import patato as pat
from patato.io.attribute_tags import HDF5Tags

from optari.io.discovery import ScanInfo
from optari.patato_bridge import LAYER_NAME_ATTR, patato_roi_from_geometry
from optari.provenance import file_origin
from optari.roi.roi_geometry import RoiGeometry
from optari.roi.roi_records import RoiRecord
from optari.utils.files import atomic_destination

logger = logging.getLogger(__name__)


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
    rois: list[RoiRecord]
    # False when stored OPTARI ROIs failed to restore: they are not in the session,
    # so they must be kept.
    replace_stored_rois: bool
    fov: tuple[float, float] | None
    derived: dict
    # The segmentation layer's mask (n_frames, H, W) and metadata
    segmentation: tuple[np.ndarray, dict] | None
    clinical_metadata: dict | None


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


def can_save_into_scan(scan_info: ScanInfo, pa_data: pat.PAData) -> bool:
    """Whether the scan is an HDF5 file OPTARI wrote, the only kind it writes into."""
    if scan_info.kind != "hdf5":
        return False
    origin = pa_data.get_file_origin()
    return origin is not None and origin.get("tool") == "OPTARI"


def save_scan_into_source(export: ScanExport) -> Generator[None, None, None]:
    """Write the session's ROIs and new layers into the scan file itself. A background
    step.

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
    # Imported here: pacfish takes about 0.4 s to load and only this report needs it.
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
        raise FileExistsError(f"Not exported, {destination.name} already exists")
    return destination


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
            # Position, run and repetition belong to the frame, which every wavelength
            # shares.
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
    """Write runtime-only OPTARI additions: derived PA images, the segmentation mask,
    and clinical metadata.

    replaces any existing derived data, segmentation mask, and clinical metadata in the
    export. Each new image carries its own origin, since a file saved into several times
    holds layers from different sessions while the file-level origin records only its
    creation.
    """
    origin = json.dumps(file_origin())
    writer = destination_pa_data.scan_writer
    for layer_name, image in export.derived.items():
        # Same layer name means same result (a different one needs a suffix), so a
        # re-run replaces what an earlier save stored under that name.
        _delete_stored_layer(writer.file, image.get_hdf5_group_name(), layer_name)
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
            "source_model_id": layer_meta["source_model_id"],
            "frame_mode": layer_meta["frame_mode"],
            "frames": [int(f) for f in layer_meta["frames"]],
            "class_names": {str(k): v for k, v in layer_meta["class_names"].items()},
        }
        writer.file[HDF5Tags.SEGMENTATION].attrs["optari_meta"] = json.dumps(meta)
        logger.info("saved segmentation mask (model '%s')", meta["source_model_id"])

    if export.clinical_metadata is not None:
        writer.set_clinical_metadata(export.clinical_metadata)
        logger.info(
            "saved clinical metadata (%s field(s))",
            len(export.clinical_metadata),
        )
