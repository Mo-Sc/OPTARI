"""patato_bridge: functions to convert between PATATO and napari data structures"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

import numpy as np
import patato as pat  # type: ignore[import]
from napari.layers import Image
from patato.io.attribute_tags import HDF5Tags  # type: ignore[import]
from patato.utils.rois.roi_type import ROI as PatatoROI  # type: ignore[import]

from optari.config import settings
from optari.roi.roi_geometry import RoiGeometry
from optari.roi.roi_records import RoiRecord, new_roi_group_uid
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


def layer_translate(
    scale: tuple, ndim: int, edge_mm=(0.0, 0.0)
) -> tuple[float, ...]:
    """napari translate for an image whose top-left outer pixel edge sits at *edge_mm*.

    Every image OPTARI shows has its field of view spanning the outer pixel edges:
    iThera's vendor recons and ultrasound, DeepMB, and PATATO's own reconstructions
    since the fork's 2026-11-17 grid change. napari puts pixel centres at
    ``translate + index * scale``, so the first centre sits half a pixel inside the edge.
    """
    return (0.0,) * (ndim - 2) + tuple(
        float(e + s / 2) for e, s in zip(edge_mm, scale[-2:])
    )


# ---------------------------------------------------------------------------
# Acquisition time
# ---------------------------------------------------------------------------

YEAR_ONE = datetime(1, 1, 1)


def acquisition_start(pa_data: pat.PAData) -> datetime | None:
    """Wall-clock time of the first frame, time-zone aware, or None if the scan cannot be dated.

    PATATO's iThera and IPASC readers count timestamps in seconds since 0001-01-01, but
    an HDF5 file from another tool may use any epoch. So the timestamps are only read as
    wall-clock times when they match the date PATATO reads from the scan itself. A day of
    tolerance absorbs time zones: iThera records local time, IPASC UTC.
    """
    scan_date = pa_data.get_scan_datetime()
    # NaN when the file records no date
    if not isinstance(scan_date, datetime):
        return None
    # The frame times are wall-clock times in the date's zone. Without an offset they
    # cannot be written as UTC
    if scan_date.tzinfo is None:
        logger.warning(
            "scan date %s has no time zone, frame times stay relative",
            scan_date,
        )
        return None
    first_s = float(np.asarray(pa_data.get_timestamps())[0, 0])
    scan_date_s = (scan_date.replace(tzinfo=None) - YEAR_ONE).total_seconds()
    if not abs(first_s - scan_date_s) <= 24 * 3600:
        logger.warning(
            "scan timestamps do not match its date %s, frame times stay relative",
            scan_date,
        )
        return None
    return (YEAR_ONE + timedelta(seconds=first_s)).replace(
        tzinfo=scan_date.tzinfo
    )


def sweep_start_timestamps(
    timestamps: np.ndarray, n_channels: int
) -> np.ndarray:
    """Timestamps for a layer whose channels are chromophores or parameters.

    The scan's timestamps are ``(frames, wavelengths)``. Indexed by an unmixed layer's
    channel they would date Hb with the first wavelength and HbO2 with the second.
    A value estimated from the whole sweep is dated by its start, on every channel.
    """
    return np.repeat(np.asarray(timestamps)[:, :1], n_channels, axis=1)


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------


def display_data_from_patato_obj(image_sequence) -> np.ndarray:
    """Convert PATATO image data to napari's display orientation."""
    return np.flip(np.array(image_sequence.da[:, :, :, 0, :]), axis=-2)


class PaddedFrames:
    """*data* held for some acquisition *frames*, read as an array over all of them.

    PA layers span every acquisition frame so they share the frame slider with the
    ultrasound. Here only the computed frames are kept and the others read as zeros. napari, the
    measurement code and ``np.asarray`` see an ordinary (frames, channels, y, x) array.
    """

    def __init__(self, data: np.ndarray, frames: list[int], n_frames: int):
        self.held = data
        self.shape = (n_frames, *data.shape[1:])
        self.dtype = data.dtype
        self.ndim = data.ndim
        self.size = int(np.prod(self.shape))
        self._position = np.full(n_frames, -1)
        self._position[list(frames)] = np.arange(len(frames))

    def __len__(self) -> int:
        return self.shape[0]

    def __getitem__(self, key):
        key = key if isinstance(key, tuple) else (key,)
        if key[0] is Ellipsis:
            return np.asarray(self)[key]
        frame_key, rest = key[0], key[1:]
        if isinstance(frame_key, (int, np.integer)):
            position = self._position[frame_key]
            if position < 0:
                # a read-only view of one zero, no allocation for a missing frame
                return np.broadcast_to(
                    np.zeros((), self.dtype), self.shape[1:]
                )[rest]
            return self.held[position][rest]
        # Frame by frame with the rest of the key applied first: napari asks for one
        # plane through a frame slice, which must not cost a whole frame of channels.
        frames = np.arange(self.shape[0])[frame_key]
        parts = [self[(int(f), *rest)] for f in frames]
        if not parts:  # an empty selection, which numpy allows
            return np.zeros((0, *self[(0, *rest)].shape), self.dtype)
        return np.stack(parts)

    def __array__(self, dtype=None, copy=None) -> np.ndarray:
        out = self[:]
        return out if dtype is None else out.astype(dtype)


def expand_to_acquisition_frames(
    data: np.ndarray, frames: list[int], n_acq_frames: int
) -> np.ndarray | PaddedFrames:
    """Place per-output-frame *data* at its *frames* on the acquisition frame axis.

    Frames that were not processed read as zero, so every PA layer shares the frame
    slider with the ultrasound. Data that already spans the acquisition is returned
    unchanged.
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
    return PaddedFrames(data, frames, n_acq_frames)


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


# What napari knows about a derived image but the PATATO data does not, stored with
# the image so an exported scan reopens as it was: the layer's napari translate (y, x in
# mm, pixel 0's centre, including e.g. DeepMB's offset), its session name, which
# derived layers link to, and the
# settings it was made with (JSON), shown in the metadata viewer.
TRANSLATE_ATTR = "optari_translate_mm"
LAYER_NAME_ATTR = "optari_layer_name"
SETTINGS_ATTR = "optari_settings"


def pa_layer_metadata(
    *,
    pa_kind: str,
    channel_labels: list,
    frames: list[int],
    scan_timestamps: np.ndarray,
    acquisition_start: datetime | None,
    settings: dict,
    filepath: str,
    scan_name: str | None,
    source_layer: str | None = None,
    parameter: str | None = None,
) -> dict:
    """The metadata of a PA image layer, loaded or computed.

    *pa_kind* is ``"recon"`` (channels are wavelengths), ``"unmixed"`` (chromophores)
    or ``"unmixed_param"`` (one *parameter*, thb or so2). *scan_timestamps* are the
    scan's ``(frames, wavelengths)`` times.
    """
    metadata = {
        "type": "pa",
        "pa_kind": pa_kind,
        "axis1_labels": channel_labels,
        "frames": frames,
        "timestamps": (
            scan_timestamps
            if pa_kind == "recon"
            else sweep_start_timestamps(scan_timestamps, len(channel_labels))
        ),
        "acquisition_start": acquisition_start,
        "settings": settings,
        # They belong to the whole scan, but a layer without them drops out of the
        # measurement table's scan columns
        "filepath": filepath,
        "scan_name": scan_name,
    }
    if pa_kind == "recon":
        metadata["wavelengths"] = channel_labels
    if pa_kind == "unmixed":
        metadata["chromophores"] = channel_labels
    if source_layer is not None:
        metadata["source_layer"] = source_layer
    if parameter is not None:
        metadata["parameter"] = parameter
    return metadata


def is_pa_layer(layer) -> bool:
    """True for a reconstruction or a layer derived from one."""
    return isinstance(layer, Image) and layer.metadata.get("type") == "pa"


def pa_layers(layers) -> list[Image]:
    """The PA image layers among *layers*, in layer order."""
    return [layer for layer in layers if is_pa_layer(layer)]


def build_napari_layers(
    pa_data: pat.PAData, filepath: str, scan_name: str | None
) -> tuple[list[tuple], dict]:
    """Build napari image layers from an open *pa_data* handle.

    *filepath* and *scan_name* (the vendor's internal name) are stamped on every layer.

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
    layers: dict[str, tuple] = {}

    def add_layer(data, kwargs: dict) -> None:
        name = kwargs["name"]
        if name in layers:
            logger.warning(
                "scan stores layer '%s' twice, showing the later copy. "
                "Export the scan to a new file to drop the older one.",
                name,
            )
        layers[name] = (data, kwargs)

    timestamps = np.array(pa_data.get_timestamps())
    start = acquisition_start(pa_data)

    # --- ultrasound ---
    # IPASC scans have no ultrasound, for which PATATO returns {} (a dict also for several
    # US images, which no supported scanner writes). The acquisition frame count then
    # comes from the time series instead.
    us_obj = pa_data.get_ultrasound()
    if not isinstance(us_obj, dict):
        us_img = display_data_from_patato_obj(us_obj)
        n_acq_frames = us_img.shape[0]
        patato_objects["US"] = us_obj
        us_scale = scale_from_patato_obj(us_obj, _us_fallback)

        add_layer(
            us_img,
            {
                "colormap": layer_colormap(HDF5Tags.ULTRASOUND),
                "name": "US",
                "scale": us_scale,
                "translate": layer_translate(us_scale, us_img.ndim),
                "opacity": 1.0,
                "metadata": {
                    "type": "us",
                    "timestamps": timestamps,
                    "filepath": filepath,
                    "scan_name": scan_name,
                },
            },
        )
    else:
        n_acq_frames = pa_data.shape[0]

    def _placement(image_sequence, ndim: int) -> dict:
        scale = scale_from_patato_obj(image_sequence, _pa_fallback)
        attrs = image_sequence.da.attrs
        if TRANSLATE_ATTR in attrs:  # made by OPTARI, placed as it was
            translate = (0.0,) * (ndim - 2) + tuple(attrs[TRANSLATE_ATTR])
        else:  # vendor recon: its FOV starts at the scan's top-left
            translate = layer_translate(scale, ndim)
        return {"scale": scale, "translate": translate}

    def _settings(image_sequence) -> dict:
        # what OPTARI made the layer with, else the file's own attributes (vendor recons)
        attrs = image_sequence.da.attrs
        if SETTINGS_ATTR in attrs:
            return json.loads(attrs[SETTINGS_ATTR])
        return dict(attrs)

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
    us_fov = _fov_m(us_obj) if "US" in patato_objects else None
    for (recon_name, idx), recon in pa_data.get_scan_reconstructions().items():
        recon_fov = _fov_m(recon)
        # A vendor reconstruction is drawn with its FOV edge at world 0, like the
        # ultrasound, and its
        # ROIs are stored in the ultrasound's frame. Both hold only when the two cover
        # the same field of view, true for every supported device. OPTARI's own
        # reconstructions (DeepMB: 40 x 33 mm) carry their placement and are exempt.
        if (
            us_fov is not None
            and recon_fov is not None
            and LAYER_NAME_ATTR not in recon.da.attrs
        ):
            pixel_m = (
                max(scale_from_patato_obj(recon, _pa_fallback)[1:]) / 1000
            )
            if not np.allclose(recon_fov, us_fov, rtol=0, atol=pixel_m):
                raise ValueError(
                    f"reconstruction '{recon_name}' covers "
                    f"{np.multiply(recon_fov, 1000).round(1).tolist()} mm, the "
                    f"ultrasound {np.multiply(us_fov, 1000).round(1).tolist()} mm. "
                    "OPTARI aligns both at the top-left corner, so it cannot "
                    "display this scan correctly."
                )
        recon_raw = display_data_from_patato_obj(recon)
        recon_frame_list = _frame_list(recon, recon_raw.shape[0])
        recon_img = expand_to_acquisition_frames(
            recon_raw, recon_frame_list, n_acq_frames
        )

        layer_name = recon.da.attrs.get(
            LAYER_NAME_ATTR, f"Recon: {recon_name}_{idx}"
        )
        # The recon's own labels, as in ReconstructionController.publish: it may
        # cover a subset of the scan's wavelengths.
        wavelengths = [int(w) for w in recon.ax_1_labels]
        patato_objects[layer_name] = recon
        add_layer(
            recon_img,
            {
                "colormap": layer_colormap(HDF5Tags.RECONSTRUCTION),
                "name": layer_name,
                **_placement(recon, recon_img.ndim),
                "opacity": 1.0,
                "blending": "multiplicative",
                "auto_contrast": True,
                "metadata": pa_layer_metadata(
                    pa_kind="recon",
                    channel_labels=wavelengths,
                    frames=recon_frame_list,
                    scan_timestamps=timestamps,
                    acquisition_start=start,
                    settings=_settings(recon),
                    filepath=filepath,
                    scan_name=scan_name,
                ),
            },
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

            source_layer = image.da.attrs.get(
                "source_layer", f"Recon: {dataset_name}_{idx}"
            )
            metadata = pa_layer_metadata(
                pa_kind=pa_kind,
                channel_labels=list(
                    map(str, np.asarray(image.ax_1_labels).tolist())
                ),
                frames=frame_list,
                scan_timestamps=timestamps,
                acquisition_start=start,
                settings=_settings(image),
                filepath=filepath,
                scan_name=scan_name,
                source_layer=str(source_layer),
                parameter=parameter,
            )
            add_layer(
                data,
                {
                    "colormap": layer_colormap(group_name),
                    "name": image.da.attrs.get(
                        LAYER_NAME_ATTR, f"{prefix}: {dataset_name}_{idx}"
                    ),
                    **_placement(image, data.ndim),
                    "opacity": 1.0,
                    "blending": "multiplicative",
                    "auto_contrast": True,
                    "metadata": metadata,
                },
            )

    return list(layers.values()), patato_objects


# ---------------------------------------------------------------------------
# FOV helpers
# ---------------------------------------------------------------------------


def fov_from_objects(patato_objects: dict) -> tuple[float, float] | None:
    """The scan's ``(fov_x_m, fov_y_m)``, the frame ROIs are stored in.

    The ultrasound's, which every vendor reconstruction matches (checked in
    ``build_napari_layers``). A scan without ultrasound (IPASC) falls back to the
    first object with a usable FOV. ``None`` if no object records one.
    """
    candidates = (
        [patato_objects["US"]]
        if "US" in patato_objects
        else patato_objects.values()
    )
    for obj in candidates:
        fov = _fov_m(obj)
        if fov is not None and min(fov) > 0:
            return fov
    return None


# ---------------------------------------------------------------------------
# Segmentation I/O
# ---------------------------------------------------------------------------


def segmentation_from_scan(pa_data: pat.PAData) -> dict | None:
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
    pa_data: pat.PAData, fov_x_m: float, fov_y_m: float
) -> list[RoiRecord]:
    """Load PATATO ROIs as one frame-owned record per valid frame."""
    try:
        rois = pa_data.get_rois()
        n_frames = int(pa_data.shape[0])
    except Exception as exc:
        raise ValueError("could not read stored ROI annotations") from exc

    records: list[RoiRecord] = []
    used_ids: set[int] = set()
    next_id = 0
    # Above every persisted group id, so an ROI without one never takes the number a
    # later ROI in the file carries.
    next_track = 1 + max(
        (
            int(r.roi_group_id)
            for r in rois.values()
            if r.roi_group_id is not None
        ),
        default=-1,
    )
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
        if roi.roi_group_id is None:
            track_id = next_track
            next_track += 1
        else:
            track_id = int(roi.roi_group_id)
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
