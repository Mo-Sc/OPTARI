"""patato_bridge: functions to convert between PATATO and napari data structures
"""

from __future__ import annotations

import logging

import numpy as np

from patato.io.attribute_tags import HDF5Tags # type: ignore[import]
import patato as pat  # type: ignore[import]

from patari.utils.motion import k_motion_scores_optimized

from patari.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FOV-derived scales
# ---------------------------------------------------------------------------


def scale_from_patato_obj(obj, fallback: tuple) -> tuple:
    """Derive a ``(t, y, x)`` napari scale in mm/pixel from a PATATO object.

    Reads the object's ``fov`` (``(fov_x_m, fov_y_m)`` in metres) and
    ``shape_2d`` (``(ny, nx)`` in pixels).  Returns *fallback* if either
    value is absent or zero.
    """
    try:
        fov = obj.fov  # (fov_x_m, fov_y_m) metres
        shape = obj.shape_2d  # (ny, nx) pixels
        if fov is None or None in fov or len(shape) < 2:
            return fallback
        fov_x_m, fov_y_m = float(fov[0]), float(fov[1])
        ny, nx = int(shape[-2]), int(shape[-1])
        if ny == 0 or nx == 0 or fov_x_m == 0 or fov_y_m == 0:
            return fallback
        return (fallback[0], fov_y_m / ny * 1000, fov_x_m / nx * 1000)
    except Exception:
        logger.warning(
            f"could not derive scale from object {obj}, using fallback {fallback}",
            exc_info=True,
        )
        return fallback


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------


def display_data_from_patato_obj(image_sequence) -> np.ndarray:
    """Convert PATATO image data to napari's display orientation."""
    return np.flip(np.array(image_sequence.da[:, :, :, 0, :]), axis=-2)


def patato_to_napari(
    pts_m: np.ndarray, fov_x_m: float, fov_y_m: float
) -> np.ndarray:
    """Convert PATATO ``(x_m, y_m)`` polygon vertices to napari ``(y_mm, x_mm)``.

    PATATO: origin at image centre, x→right, y→up, metres.
    napari:  origin at top-left,   y→down, mm.
    """
    x_m = pts_m[:, 0]
    y_m = pts_m[:, 1]
    return np.stack(
        [
            (fov_y_m / 2.0 - y_m) * 1000.0,  # y_mm  (y-axis flipped)
            (x_m + fov_x_m / 2.0) * 1000.0,  # x_mm  (origin shifted)
        ],
        axis=1,
    )


def napari_to_patato(
    verts_yx_mm: np.ndarray, fov_x_m: float, fov_y_m: float
) -> np.ndarray:
    """Inverse of :func:`patato_to_napari`."""
    y_mm = verts_yx_mm[:, 0]
    x_mm = verts_yx_mm[:, 1]
    return np.stack(
        [
            x_mm / 1000.0 - fov_x_m / 2.0,  # patato x (m)
            fov_y_m / 2.0 - y_mm / 1000.0,  # patato y (m)
        ],
        axis=1,
    )


# ---------------------------------------------------------------------------
# Layer building
# ---------------------------------------------------------------------------


def build_napari_layers(pa_data: "pat.PAData") -> tuple[list[tuple], dict]:
    """Build napari LayerData tuples from an open *pa_data* handle.

    Returns
    -------
    layers : list of ``(data, kwargs, layer_type)`` tuples
        Ready to pass to ``viewer.add_image`` / ``viewer.add_labels``.
    patato_objects : dict
        Maps napari layer name → PATATO ``ImageSequence`` for later use
        (e.g. FOV queries, scale derivation).
    """
    _us_fallback = settings.general.US_FALLBACK_SCALE
    _pa_fallback = settings.general.PA_FALLBACK_SCALE

    _user_cmaps = settings.general.LAYER_COLOR_MAPS
    # fallback to hardcoded defaults if any of the configured cmaps are missing
    _default_cmaps = {
            HDF5Tags.ULTRASOUND: "gray",
            HDF5Tags.RECONSTRUCTION: "viridis",
            HDF5Tags.UNMIXED: "magma",
            HDF5Tags.SO2: "twilight_shifted",
            HDF5Tags.THB: "inferno",
        }  


    patato_objects: dict = {}
    layers: list = []

    try:
        timestamps = np.array(pa_data.get_timestamps())
    except Exception:
        timestamps = None
    try:
        wavelengths = [int(w) for w in pa_data.get_wavelengths()]
    except Exception:
        wavelengths = None

    # --- ultrasound ---
    us_obj = pa_data.get_ultrasound()
    us_img = display_data_from_patato_obj(us_obj)
    n_acq_frames = us_img.shape[0]
    patato_objects["US"] = us_obj

    # if motion-based frame selection is enabled, compute motion scores for each frame
    # TODO: or maybe always include
    if settings.general.DEFAULT_FRAME_INDEX == "motion":
        motion_scores = k_motion_scores_optimized(us_img)
    else:
        motion_scores = None

    layers.append(
        (
            us_img,
            {
                "colormap": _user_cmaps.get(HDF5Tags.ULTRASOUND, _default_cmaps[HDF5Tags.ULTRASOUND]),
                "name": "US",
                "scale": scale_from_patato_obj(us_obj, _us_fallback),
                "opacity": 1.0,
                "metadata": {"type": "us", "timestamps": timestamps, "motion_scores": motion_scores},
            },
            "image",
        )
    )

    def _frame_list(image_sequence, n_frames: int) -> list[int]:
        frames_info = image_sequence.da.attrs.get(
            "frames", image_sequence.da.attrs.get("frame")
        )
        if frames_info is None:
            return list(range(n_frames))
        if isinstance(frames_info, (np.int64, float, int, str)):
            return [int(frames_info)]
        if isinstance(frames_info, (list, np.ndarray)):
            return [int(f) for f in frames_info]
        return list(range(n_frames))

    def _expand_to_acquisition_frames(
        raw_data: np.ndarray, frame_list: list[int]
    ) -> np.ndarray:
        if (
            raw_data.shape[0] == n_acq_frames
            and len(frame_list) == n_acq_frames
        ):
            return raw_data

        expanded = np.zeros(
            (n_acq_frames, *raw_data.shape[1:]), dtype=raw_data.dtype
        )
        for i, frame in enumerate(frame_list):
            if 0 <= int(frame) < n_acq_frames and i < raw_data.shape[0]:
                expanded[int(frame)] = raw_data[i]
        return expanded

    # --- reconstructions ---
    for (recon_name, idx), recon in pa_data.get_scan_reconstructions().items():
        recon_raw = display_data_from_patato_obj(recon)
        recon_frame_list = _frame_list(recon, recon_raw.shape[0])
        recon_img = _expand_to_acquisition_frames(recon_raw, recon_frame_list)

        layer_name = f"Recon: {recon_name}_{idx}"
        patato_objects[layer_name] = recon
        layers.append(
            (
                recon_img,
                {
                    "colormap": _user_cmaps.get(HDF5Tags.RECONSTRUCTION, _default_cmaps[HDF5Tags.RECONSTRUCTION]),
                    "name": layer_name,
                    "scale": scale_from_patato_obj(recon, _pa_fallback),
                    "opacity": 1.0,
                    "metadata": {
                        "type": "pa",
                        "pa_kind": "recon",
                        "wavelengths": wavelengths,
                        "axis1_name": "Channel",
                        "axis1_labels": wavelengths,
                        "timestamps": timestamps,
                        "frames": recon_frame_list,
                    },
                },
                "image",
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
            data = _expand_to_acquisition_frames(raw, frame_list)

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
            }
            if pa_kind == "unmixed":
                metadata["chromophores"] = axis1_labels
            if parameter is not None:
                metadata["parameter"] = parameter

            layers.append(
                (
                    data,
                    {
                        "colormap": _user_cmaps.get(group_name, _default_cmaps.get(group_name, "viridis")),
                        "name": f"{prefix}: {dataset_name}_{idx}",
                        "scale": scale_from_patato_obj(image, _pa_fallback),
                        "opacity": 1.0,
                        "metadata": metadata,
                    },
                    "image",
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
        try:
            fov = obj.fov
            if fov is None or len(fov) < 2 or None in fov:
                continue
            fov_x_m, fov_y_m = float(fov[0]), float(fov[1])
            if fov_x_m > 0 and fov_y_m > 0:
                return fov_x_m, fov_y_m
        except Exception:
            logger.warning(
                f"could not derive FOV from object {obj}", exc_info=True
            )
            continue
    return None


# ---------------------------------------------------------------------------
# ROI I/O
# ---------------------------------------------------------------------------


def napari_shapes_from_scan_rois(
    pa_data: "pat.PAData",
    fov_x_m: float,
    fov_y_m: float,
) -> list[tuple[np.ndarray, str, str, str]]:
    """Load ROI polygons from *pa_data* as napari ``(y_mm, x_mm)`` vertices.

    Silently skips individual ROIs that cannot be converted.
    Limits ROIs to MAX_ROIS from config; logs warning if truncated.
    Returns an empty list when no ROIs exist or loading fails.
    """
    try:
        rois = pa_data.get_rois()
    except Exception:
        logger.exception("could not load ROIs")
        return []

    max_rois = settings.annotation.max_rois
    total_rois = len(rois)
    if total_rois > max_rois:
        logger.warning(
            "data contains %d ROI(s), but MAX_ROIS is %d; only loading first %d",
            total_rois,
            max_rois,
            max_rois,
        )

    shapes = []
    roi_items = list(rois.items())[: max_rois]
    for (_name, _number), roi in roi_items:
        try:
            pts = np.asarray(roi.points, dtype=float)  # (N, 2): (x_m, y_m)
            shapes.append(
                (
                    patato_to_napari(pts, fov_x_m, fov_y_m),
                    getattr(roi, "shape_type", "polygon"),
                    getattr(roi, "position", "undefined"),
                    str(_name),
                )
            )
        except Exception:
            logger.exception("skipped ROI %s/%s", _name, _number)
    return shapes


def napari_shapes_to_patato_rois(
    shapes: list[np.ndarray],
    shape_types: list[str],
    roi_positions: list[str],
    fov_x_m: float,
    fov_y_m: float,
    z: float = 0.0,
    run: float = 0.0,
    rep: float = 0.0,
    frame_idx: int = 0,
    roi_class: str = "PATARI",
) -> list[object]:
    """Convert napari ROI shapes into PATATO ROI objects.

    The returned objects can be persisted with PATATO's native writer API.
    """
    from patato.utils.rois.roi_type import ROI as PatatoROI  # type: ignore[import]

    rois: list[object] = []
    for i, (verts, stype, position) in enumerate(
        zip(shapes, shape_types, roi_positions)
    ):
        verts_yx = np.asarray(verts, dtype=float)[..., -2:]
        rois.append(
            PatatoROI.from_polygon_mm(
                verts_yx_mm=verts_yx,
                fov=(fov_x_m, fov_y_m),
                z_position=z,
                run=run,
                repetition=rep,
                ax0_index=np.array([frame_idx]),
                roi_class=str(roi_class),
                position=position,
                generated=True,
                shape_type=stype,
            )
        )
    return rois
