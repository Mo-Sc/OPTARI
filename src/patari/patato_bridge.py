"""patato_bridge — pure helpers bridging PATATO ↔ napari/PATARI.

No napari viewer or Qt state here; all functions are pure and can be
tested independently of the plugin runtime.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import patato as pat


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
        return fallback


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------


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
    _us_fallback = (1, 0.19, 0.19)
    _recon_fallback = (1, 0.1, 0.1)

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
    us_img = np.flip(np.array(us_obj.da[:, :, :, 0, :]), axis=-2)
    n_acq_frames = us_img.shape[0]
    patato_objects["US"] = us_obj
    layers.append(
        (
            us_img,
            {
                "colormap": "gray",
                "name": "US",
                "scale": scale_from_patato_obj(us_obj, _us_fallback),
                "metadata": {"type": "us", "timestamps": timestamps},
            },
            "image",
        )
    )

    # --- reconstructions ---
    for (recon_name, idx), recon in pa_data.get_scan_reconstructions().items():
        recon_raw = np.flip(np.array(recon.da[:, :, :, 0, :]), axis=-2)

        frames_info = recon.da.attrs.get("frame", None)
        if frames_info is None:
            recon_frame_list = list(range(recon_raw.shape[0]))
        elif isinstance(frames_info, (np.int64, float, int)):
            recon_frame_list = [int(frames_info)]
        elif isinstance(frames_info, (list, np.ndarray)):
            recon_frame_list = [int(f) for f in frames_info]
        else:
            raise ValueError(
                "Reconstruction 'frame' attribute has unsupported type."
            )

        recon_img = np.zeros(
            (n_acq_frames, *recon_raw.shape[1:]), dtype=recon_raw.dtype
        )
        for i, acq_frame in enumerate(recon_frame_list):
            if not (0 <= acq_frame < n_acq_frames):
                raise IndexError(
                    f"Reconstruction frame {acq_frame} out of bounds "
                    f"(0, {n_acq_frames - 1})"
                )
            recon_img[acq_frame] = recon_raw[i]

        layer_name = f"Recon: {recon_name}_{idx}"
        patato_objects[layer_name] = recon
        layers.append(
            (
                recon_img,
                {
                    "colormap": "viridis",
                    "name": layer_name,
                    "scale": scale_from_patato_obj(recon, _recon_fallback),
                    "metadata": {
                        "type": "pa",
                        "wavelengths": wavelengths,
                        "timestamps": timestamps,
                        "frames": recon_frame_list,
                    },
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
            if fov is not None and len(fov) >= 2 and None not in fov:
                return float(fov[0]), float(fov[1])
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# ROI I/O
# ---------------------------------------------------------------------------


def napari_shapes_from_scan_rois(
    pa_data: "pat.PAData",
    fov_x_m: float,
    fov_y_m: float,
) -> list[tuple[np.ndarray, str]]:
    """Load ROI polygons from *pa_data* as napari ``(y_mm, x_mm)`` vertices.

    Silently skips individual ROIs that cannot be converted.
    Returns an empty list when no ROIs exist or loading fails.
    """
    try:
        rois = pa_data.get_rois()
    except Exception:
        logger.exception("could not load ROIs")
        return []

    shapes = []
    for (_name, _number), roi in rois.items():
        try:
            pts = np.asarray(roi.points, dtype=float)  # (N, 2): (x_m, y_m)
            shapes.append(
                (
                    patato_to_napari(pts, fov_x_m, fov_y_m),
                    getattr(roi, "shape_type", "polygon"),
                )
            )
        except Exception:
            logger.exception("skipped ROI %s/%s", _name, _number)
    return shapes


def napari_shapes_to_patato_rois(
    shapes: list[np.ndarray],
    shape_types: list[str],
    fov_x_m: float,
    fov_y_m: float,
    z: float = 0.0,
    run: float = 0.0,
    rep: float = 0.0,
    frame_idx: int = 0,
) -> list[object]:
    """Convert napari ROI shapes into PATATO ROI objects.

    The returned objects can be persisted with PATATO's native writer API.
    """
    from patato.utils.rois.roi_type import ROI as PatatoROI  # type: ignore[import]

    rois: list[object] = []
    for i, (verts, stype) in enumerate(zip(shapes, shape_types)):
        verts_yx = np.asarray(verts, dtype=float)[..., -2:]
        rois.append(
            PatatoROI.from_polygon_mm(
                verts_yx_mm=verts_yx,
                fov=(fov_x_m, fov_y_m),
                z_position=z,
                run=run,
                repetition=rep,
                ax0_index=np.array([frame_idx]),
                roi_class="PATARI",
                position=str(i),
                generated=True,
                shape_type=stype,
            )
        )
    return rois
