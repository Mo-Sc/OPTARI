"""patato_bridge: functions to convert between PATATO and napari data structures"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

import numpy as np

from patato.io.attribute_tags import HDF5Tags  # type: ignore[import]
import patato as pat  # type: ignore[import]


from optari.config import settings
from optari.roi.roi_geometry import RoiGeometry
from optari.roi.roi_records import ROIRecord, new_roi_group_uid
from optari.segmentation.segmenter import MASK_DTYPE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FOV-derived scales
# ---------------------------------------------------------------------------


def _fov_m(obj) -> tuple[float, float] | None:
    """``(fov_x_m, fov_y_m)`` a PATATO object records, or None if it records none.

    Each axis is stored either as an extent or as a ``(start, end)`` pair.
    """
    if obj.fov is None or None in obj.fov:
        return None
    return tuple(
        (
            abs(float(axis[1]) - float(axis[0]))
            if isinstance(axis, (tuple, list, np.ndarray))
            else float(axis)
        )
        for axis in obj.fov[:2]
    )


def scale_from_patato_obj(obj, fallback: tuple) -> tuple:
    """Derive a ``(t, y, x)`` napari scale in mm/pixel from a PATATO object.

    Reads the object's ``fov`` (``(fov_x_m, fov_y_m)`` in metres) and
    ``shape_2d`` (``(ny, nx)`` in pixels).  Returns *fallback* if either
    value is absent or zero.
    """
    fov = _fov_m(obj)
    if fov is None:
        return fallback
    fov_x_m, fov_y_m = fov
    ny, nx = obj.shape_2d[-2:]  # pixels
    if not (ny and nx and fov_x_m and fov_y_m):
        logger.warning(
            "no usable FOV on %s, using fallback scale %s", obj, fallback
        )
        return fallback
    return (fallback[0], fov_y_m / ny * 1000, fov_x_m / nx * 1000)


# ---------------------------------------------------------------------------
# Acquisition time
# ---------------------------------------------------------------------------

YEAR_ONE = datetime(1, 1, 1)


def acquisition_start(pa_data: "pat.PAData") -> datetime | None:
    """Wall-clock time of the first frame, or None if the scan cannot be dated.

    PATATO's iThera and IPASC readers count timestamps in seconds since 0001-01-01, but
    an HDF5 file from another tool may use any epoch. So the timestamps are only read as
    wall-clock times when they match the date PATATO reads from the scan itself. A day of
    tolerance absorbs time zones: iThera records local time, IPASC UTC.
    """
    scan_date = pa_data.get_scan_datetime()
    # NaN when the file records no date
    if not isinstance(scan_date, datetime):
        return None
    first_s = float(np.asarray(pa_data.get_timestamps())[0, 0])
    scan_date_s = (scan_date.replace(tzinfo=None) - YEAR_ONE).total_seconds()
    if not abs(first_s - scan_date_s) <= 24 * 3600:
        logger.warning(
            "scan timestamps do not match its date %s, frame times stay relative",
            scan_date,
        )
        return None
    return YEAR_ONE + timedelta(seconds=first_s)


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------


def display_data_from_patato_obj(image_sequence) -> np.ndarray:
    """Convert PATATO image data to napari's display orientation."""
    return np.flip(np.array(image_sequence.da[:, :, :, 0, :]), axis=-2)


def expand_to_acquisition_frames(
    data: np.ndarray, frames: list[int], n_acq_frames: int
) -> np.ndarray:
    """Place per-output-frame *data* at its *frames* on the acquisition frame axis.

    Frames that were not processed stay zero, so every PA layer shares the frame slider
    with the ultrasound. Data that already spans the acquisition is returned unchanged.
    """
    if data.shape[0] == n_acq_frames:
        return data
    # A frame list that does not match the data would put images on the wrong frames.
    if len(frames) != data.shape[0] or not all(
        0 <= f < n_acq_frames for f in frames
    ):
        raise ValueError(
            f"frame indices {frames} do not match {data.shape[0]} image frame(s) "
            f"within {n_acq_frames} acquisition frame(s)"
        )
    expanded = np.zeros((n_acq_frames, *data.shape[1:]), dtype=data.dtype)
    expanded[frames] = data
    return expanded


# ---------------------------------------------------------------------------
# Layer building
# ---------------------------------------------------------------------------


# Used for any image group that LAYER_COLOR_MAPS in config.json does not name.
DEFAULT_COLORMAPS = {
    HDF5Tags.ULTRASOUND: "gray",
    HDF5Tags.RECONSTRUCTION: "viridis",
    HDF5Tags.UNMIXED: "magma",
    HDF5Tags.SO2: "twilight_shifted",
    HDF5Tags.THB: "inferno",
}


def layer_colormap(group: str) -> str:
    """Colormap for an HDF5 image *group*, whether loaded from the scan or computed."""
    return settings.general.LAYER_COLOR_MAPS.get(
        group, DEFAULT_COLORMAPS[group]
    )


def build_napari_layers(pa_data: "pat.PAData") -> tuple[list[tuple], dict]:
    """Build napari image layers from an open *pa_data* handle.

    Returns
    -------
    layers : list of ``(data, kwargs)`` tuples
        Ready to pass to ``viewer.add_image``. Everything a scan holds is an image.
        annotations and segmentations are layers OPTARI creates, not loads.
    patato_objects : dict
        Maps napari layer name → PATATO ``ImageSequence`` for later use
        (e.g. FOV queries, scale derivation).
    """
    _us_fallback = settings.general.US_FALLBACK_SCALE
    _pa_fallback = settings.general.PA_FALLBACK_SCALE

    patato_objects: dict = {}
    layers: list = []

    timestamps = np.array(pa_data.get_timestamps())
    start = acquisition_start(pa_data)
    wavelengths = [int(w) for w in pa_data.get_wavelengths()]

    # --- ultrasound ---
    # IPASC scans have no ultrasound. The acquisition frame count then comes from the time series instead.
    us_obj = pa_data.get_ultrasound()
    if hasattr(us_obj, "da"):
        us_img = display_data_from_patato_obj(us_obj)
        n_acq_frames = us_img.shape[0]
        patato_objects["US"] = us_obj

        layers.append(
            (
                us_img,
                {
                    "colormap": layer_colormap(HDF5Tags.ULTRASOUND),
                    "name": "US",
                    "scale": scale_from_patato_obj(us_obj, _us_fallback),
                    "opacity": 1.0,
                    "metadata": {
                        "type": "us",
                        "timestamps": timestamps,
                    },
                },
            )
        )
    else:
        n_acq_frames = pa_data.shape[0]

    def _frame_list(image_sequence, n_frames: int) -> list[int]:
        frames_info = image_sequence.da.attrs.get(
            "frames", image_sequence.da.attrs.get("frame")
        )
        if frames_info is None:
            return list(range(n_frames))
        # atleast_1d covers a scalar of any numpy/Python int type as well as lists and
        # arrays. anything int() rejects is a corrupt attribute and should fail
        return [int(f) for f in np.atleast_1d(frames_info)]

    # --- reconstructions ---
    for (recon_name, idx), recon in pa_data.get_scan_reconstructions().items():
        recon_raw = display_data_from_patato_obj(recon)
        recon_frame_list = _frame_list(recon, recon_raw.shape[0])
        recon_img = expand_to_acquisition_frames(
            recon_raw, recon_frame_list, n_acq_frames
        )

        layer_name = f"Recon: {recon_name}_{idx}"
        patato_objects[layer_name] = recon
        layers.append(
            (
                recon_img,
                {
                    "colormap": layer_colormap(HDF5Tags.RECONSTRUCTION),
                    "name": layer_name,
                    "scale": scale_from_patato_obj(recon, _pa_fallback),
                    "opacity": 1.0,
                    "blending": "multiplicative",
                    "auto_contrast": True,
                    "metadata": {
                        "type": "pa",
                        "pa_kind": "recon",
                        "wavelengths": wavelengths,
                        "axis1_name": "Channel",
                        "axis1_labels": wavelengths,
                        "timestamps": timestamps,
                        "acquisition_start": start,
                        "frames": recon_frame_list,
                    },
                },
            )
        )

    # --- derived PA image groups that may already exist in HDF5 ---
    derived_specs = [
        (HDF5Tags.UNMIXED, "Unmixed", "unmixed", None),
        (HDF5Tags.THB, "THb", "unmixed_param", "thb"),
        (HDF5Tags.SO2, "sO2", "unmixed_param", "so2"),
    ]
    for group_name, prefix, pa_kind, parameter in derived_specs:
        for (dataset_name, idx), image in pa_data.get_scan_images(
            group_name, ignore_default=True
        ).items():
            raw = display_data_from_patato_obj(image)
            frame_list = _frame_list(image, raw.shape[0])
            data = expand_to_acquisition_frames(raw, frame_list, n_acq_frames)

            axis1_labels = list(
                map(str, np.asarray(image.ax_1_labels).tolist())
            )
            source_layer = image.da.attrs.get("source_layer")
            if source_layer is None:
                source_layer = f"Recon: {dataset_name}_{idx}"
            metadata = {
                "type": "pa",
                "pa_kind": pa_kind,
                "source_layer": str(source_layer),
                "frames": frame_list,
                "axis1_name": "Channel",
                "axis1_labels": axis1_labels,
                "timestamps": timestamps,
                "acquisition_start": start,
            }
            if pa_kind == "unmixed":
                metadata["chromophores"] = axis1_labels
            if parameter is not None:
                metadata["parameter"] = parameter

            layers.append(
                (
                    data,
                    {
                        "colormap": layer_colormap(group_name),
                        "name": f"{prefix}: {dataset_name}_{idx}",
                        "scale": scale_from_patato_obj(image, _pa_fallback),
                        "opacity": 1.0,
                        "blending": "multiplicative",
                        "auto_contrast": True,
                        "metadata": metadata,
                    },
                )
            )

    return layers, patato_objects


# ---------------------------------------------------------------------------
# FOV helpers
# ---------------------------------------------------------------------------


def fov_from_objects(patato_objects: dict) -> "tuple[float, float] | None":
    """Return ``(fov_x_m, fov_y_m)`` from the first object with valid FOV.

    Returns ``None`` if no object exposes usable FOV metadata.
    """
    for obj in patato_objects.values():
        fov = _fov_m(obj)
        if fov is not None and min(fov) > 0:
            return fov
    return None


# ---------------------------------------------------------------------------
# Segmentation I/O
# ---------------------------------------------------------------------------


def segmentation_from_scan(pa_data: "pat.PAData") -> dict | None:
    """Load a previously exported segmentation mask and its class metadata.

    Returns ``None`` when the scan has no segmentation, or one that has not optari compatible metadata
    """
    seg = pa_data.get_segmentation()
    if seg is None:
        return None
    dataset = pa_data.scan_reader.file[HDF5Tags.SEGMENTATION]
    if "optari_meta" not in dataset.attrs:
        logger.info(
            "scan has a segmentation dataset OPTARI did not write, ignoring it"
        )
        return None
    meta = json.loads(dataset.attrs["optari_meta"])
    meta["mask"] = np.asarray(seg, dtype=MASK_DTYPE)  # (n_frames, H, W)
    meta["class_names"] = {int(k): v for k, v in meta["class_names"].items()}
    return meta


# ---------------------------------------------------------------------------
# ROI I/O
# ---------------------------------------------------------------------------


def roi_records_from_scan_rois(
    pa_data: "pat.PAData", fov_x_m: float, fov_y_m: float
) -> list[ROIRecord]:
    """Load PATATO ROIs as one frame-owned record per valid frame."""
    try:
        rois = pa_data.get_rois()
        n_frames = int(pa_data.shape[0])
    except Exception as exc:
        raise ValueError("could not read stored ROI annotations") from exc

    records: list[ROIRecord] = []
    used_ids: set[int] = set()
    next_id = 0
    next_track = 0
    frameless = []
    for key, roi in rois.items():
        try:
            verts_m = np.asarray(roi.points, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"stored ROI {key!r} has invalid geometry"
            ) from exc
        geometry = RoiGeometry(
            verts_m=verts_m,
            kind=roi.shape_type,
            source=roi.roi_class,
            tissue_class=roi.position,
        )
        frames = np.unique(roi.ax0_index)
        # A frame this scan does not have means the ROI was drawn on another acquisition.
        if np.any((frames < 0) | (frames >= n_frames)):
            raise ValueError(
                f"stored ROI {key!r} references frame(s) {frames.tolist()}, "
                f"but the scan has {n_frames}"
            )
        if not frames.size:
            # No frame recorded at all (e.g. iLabs .iROI files): the ROI covers the whole acquisition.
            frames = np.arange(n_frames, dtype=int)
            frameless.append(key)

        # PATATO calls this "roi_group_id", in OPTARI it is `track_id`.
        track_id = (
            next_track if roi.roi_group_id is None else int(roi.roi_group_id)
        )
        next_track = max(next_track, track_id + 1)
        persisted_id = None if roi.roi_id is None else int(roi.roi_id)

        # Every frame copy of one ROI shares the group's identity. a scan written
        # before uids existed gets a fresh one for the whole group, not per frame.
        group_uid = str(roi.roi_group_uid or new_roi_group_uid())
        for frame_id in frames:
            roi_id = persisted_id if len(frames) == 1 else None
            if roi_id is None or roi_id in used_ids:
                while next_id in used_ids:
                    next_id += 1
                roi_id = next_id
            used_ids.add(roi_id)
            next_id = max(next_id, roi_id + 1)
            records.append(
                geometry.to_record(
                    roi_id=roi_id,
                    track_id=track_id,
                    frame_id=int(frame_id),
                    roi_group_uid=group_uid,
                    fov_x_m=fov_x_m,
                    fov_y_m=fov_y_m,
                )
            )
    if frameless:
        logger.warning(
            "%d stored ROI(s) have no frame assigned and are shown on all %d frames: %s",
            len(frameless),
            n_frames,
            ", ".join(f"{name} #{number}" for name, number in frameless),
        )
    return records


def patato_roi_from_geometry(
    geometry: RoiGeometry,
    fov_x_m: float,
    fov_y_m: float,
    *,
    z: float = 0.0,
    run: float = 0.0,
    rep: float = 0.0,
    frame_idx: int = 0,
    roi_id: int | None = None,
    track_id: int | None = None,
    roi_group_uid: str | None = None,
) -> object:
    """Convert an ROI geometry into a PATATO ROI object for the native writer.

    The geometry's ``source`` becomes PATATO's ``roi_class``, so provenance survives export.
    """
    from patato.utils.rois.roi_type import ROI as PatatoROI  # type: ignore[import]

    roi = PatatoROI.from_polygon_mm(
        verts_yx_mm=geometry.verts_mm(fov_x_m, fov_y_m),
        fov=(fov_x_m, fov_y_m),
        z_position=z,
        run=run,
        repetition=rep,
        ax0_index=np.array([frame_idx]),
        roi_class=geometry.source,
        position=geometry.tissue_class,  # PATATO's own kwarg name
        generated=True,
        shape_type=geometry.kind,
    )
    if roi_id is not None:
        roi.roi_id = int(roi_id)
    if track_id is not None:
        roi.roi_group_id = int(track_id)  # PATATO's own attribute name
    if roi_group_uid is not None:
        roi.roi_group_uid = str(roi_group_uid)
    return roi
