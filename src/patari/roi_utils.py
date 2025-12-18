# roi_utils.py
import numpy as np
from skimage.draw import polygon
import cv2
import pandas as pd
from patari.config import dtype_map
from pathlib import Path


def polygon_mask(verts_px, image_shape):
    """Rasterize a polygon (verts in pixel coords) to a boolean mask."""
    ys = np.round(verts_px[:, 0]).astype(int)
    xs = np.round(verts_px[:, 1]).astype(int)
    rr, cc = polygon(ys, xs, image_shape)
    mask = np.zeros(image_shape, dtype=bool)
    mask[rr, cc] = True
    return mask


def ellipse_mask(verts_px, image_shape):
    """Rasterize a 4-point ellipse vertex representation to a boolean mask."""
    p0, p1, p2, p3 = verts_px
    cx, cy = verts_px.mean(axis=0)[::-1]  # (x,y)

    v01 = p1 - p0
    v12 = p2 - p1
    width = np.linalg.norm(v01)
    height = np.linalg.norm(v12)

    rx, ry = width / 2.0, height / 2.0
    angle = np.degrees(np.arctan2(v01[0], v01[1]))

    # OpenCV ellipse mask
    mask = np.zeros(image_shape, dtype=np.uint8)
    cv2.ellipse(
        mask,
        center=(int(cx), int(cy)),
        axes=(int(rx), int(ry)),
        angle=angle,
        startAngle=0,
        endAngle=360,
        color=1,
        thickness=-1,
    )
    return mask.astype(bool)


def compute_roi_stats(
    shapes_layer,
    active_layer,
    frame_idx: int,
    wav_idx: int,
    *,
    clamp_min: float | None = None,
    clamp_max: float | None = None,
):
    """
    Compute ROI statistics for all shapes in shapes_layer
    for the given active_layer and specific frame/wavelength.

    Returns a DataFrame with correct dtype. Skips zero-padded frames.
    """

    if active_layer is None:
        return pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)

    # check for reconstructed frames
    frames = active_layer.metadata.get("frames", None)
    if frames is not None and frame_idx not in frames:
        # this frame was zero-padded → return empty stats
        return pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)

    # clamp wavelength to valid range
    W = np.asarray(active_layer.data).shape[1]
    wav_idx = min(max(0, wav_idx), W - 1)

    # extract slice
    img2d = np.asarray(active_layer.data)[frame_idx, wav_idx]

    # scale from metadata (.scale)
    scale = active_layer.scale
    sy, sx = scale[-2], scale[-1]

    rows = []
    for i, verts in enumerate(shapes_layer.data):
        verts_arr = np.asarray(verts)
        if verts_arr.ndim != 2:
            continue

        # convert mm→px
        verts_pixels = verts_arr / np.array([sy, sx])

        shape_type = (
            shapes_layer.shape_type[i]
            if hasattr(shapes_layer, "shape_type")
            else "polygon"
        )

        # rasterize
        try:
            if shape_type == "ellipse":
                mask = ellipse_mask(verts_pixels, img2d.shape)
            else:
                mask = polygon_mask(verts_pixels, img2d.shape)
        except Exception:
            continue

        vals = img2d[mask]
        vals_stats = vals
        if vals_stats.size and (
            clamp_min is not None or clamp_max is not None
        ):
            # apply clamping for stats computation
            lo = float(clamp_min) if clamp_min is not None else None
            hi = float(clamp_max) if clamp_max is not None else None
            vals_stats = np.clip(
                vals_stats,
                a_min=lo,
                a_max=hi,
            )
        if vals.size == 0:
            # empty ROI
            stats = dict(
                roi_index=i,
                n_pixels=0,
                area_mm2=np.nan,
                mean=np.nan,
                median=np.nan,
                std=np.nan,
                min=np.nan,
                max=np.nan,
            )
        else:
            stats = dict(
                roi_index=i,
                n_pixels=int(vals.size),
                area_mm2=float(vals.size * sy * sx),
                mean=float(np.nanmean(vals_stats)),
                median=float(np.nanmedian(vals_stats)),
                std=float(np.nanstd(vals_stats)),
                min=float(np.nanmin(vals_stats)),
                max=float(np.nanmax(vals_stats)),
            )

        # wavelength metadata
        wavelengths = active_layer.metadata.get("wavelengths", None)
        if isinstance(wavelengths, (list, tuple)) and 0 <= wav_idx < len(
            wavelengths
        ):
            wav_val = wavelengths[wav_idx]
        else:
            wav_val = wav_idx

        filepath = active_layer.metadata.get("filepath", "")
        scan_id = Path(filepath).stem.split("_")[0] if filepath else ""
        stats["source_layer"] = active_layer.name
        stats["roi_type"] = shape_type
        stats["scan_id"] = scan_id
        stats["frame"] = frame_idx
        stats["wavelength"] = wav_val
        stats["filepath"] = filepath

        rows.append(stats)

    df = pd.DataFrame(rows, columns=list(dtype_map.keys()))
    try:
        df = df.astype(dtype_map)
    except Exception:
        pass
    return df


def compute_roi_time_series(
    shapes_layer,
    active_layer,
    wav_idx: int,
    *,
    clamp_min: float | None = None,
    clamp_max: float | None = None,
):
    """Compute per-ROI mean intensity over time for a fixed wavelength.

    Returns (x, series) where:
    - x is either frame indices or timestamps (seconds since start)
    - series is a dict {roi_index: np.ndarray}

    This intentionally does not depend on napari classes; it only relies on the
    minimal attributes used below (data, scale, metadata, shapes_layer.data).
    """

    if active_layer is None:
        return np.asarray([]), {}

    data = np.asarray(active_layer.data)
    if data.ndim < 3:
        return np.asarray([]), {}

    n_frames = data.shape[0]
    n_wavs = data.shape[1]
    wav_idx = int(np.clip(int(wav_idx), 0, max(0, n_wavs - 1)))

    frames_meta = getattr(active_layer, "metadata", {}).get("frames")
    if frames_meta:
        frames = np.asarray(frames_meta, dtype=int)
    else:
        frames = np.arange(n_frames, dtype=int)

    ts = getattr(active_layer, "metadata", {}).get("timestamps")
    if ts is not None:
        try:
            ts = np.asarray(ts)
            x = ts[frames, wav_idx].astype(float)
            x = x - float(ts[0, wav_idx])
        except Exception:
            x = frames.astype(float)
    else:
        x = frames.astype(float)

    # ROI masks are stable across frames for a given (y,x) image shape.
    scale = getattr(active_layer, "scale", (1.0, 1.0, 1.0))
    sy, sx = float(scale[-2]), float(scale[-1])
    img_shape = data.shape[-2:]

    series: dict[int, np.ndarray] = {}
    for roi_index, verts in enumerate(getattr(shapes_layer, "data", [])):
        verts_arr = np.asarray(verts)
        if verts_arr.ndim != 2:
            continue

        verts_pixels = verts_arr / np.array([sy, sx])
        shape_type = (
            shapes_layer.shape_type[roi_index]
            if hasattr(shapes_layer, "shape_type")
            else "polygon"
        )

        try:
            if shape_type == "ellipse":
                mask = ellipse_mask(verts_pixels, img_shape)
            else:
                mask = polygon_mask(verts_pixels, img_shape)
        except Exception:
            continue

        flat_idx = np.flatnonzero(mask.ravel())
        if flat_idx.size == 0:
            series[roi_index] = np.full(frames.shape[0], np.nan, dtype=float)
            continue

        y = np.empty(frames.shape[0], dtype=float)
        for j, f in enumerate(frames):
            img2d = data[int(f), wav_idx]
            vals = img2d.ravel()[flat_idx]
            if vals.size and (clamp_min is not None or clamp_max is not None):
                # apply clamping
                lo = float(clamp_min) if clamp_min is not None else None
                hi = float(clamp_max) if clamp_max is not None else None
                vals = np.clip(vals, a_min=lo, a_max=hi)
            y[j] = float(np.nanmean(vals)) if vals.size else np.nan
        series[roi_index] = y

    return x, series


def extract_roi_pixels_for_slice(
    shapes_layer,
    active_layer,
    frame_idx: int,
    wav_idx: int,
    *,
    clamp_min: float | None = None,
    clamp_max: float | None = None,
) -> dict[int, np.ndarray]:
    """Return per-ROI pixel intensities for a single (frame, wavelength).

    Returns {roi_index: 1D np.ndarray}.
    Applies optional intensity clamping to the returned values.
    """

    if active_layer is None:
        return {}

    data = np.asarray(active_layer.data)
    if data.ndim < 3:
        return {}

    # Skip zero-padded frames if reconstruction is sparse.
    frames = getattr(active_layer, "metadata", {}).get("frames")
    if frames is not None and frame_idx not in frames:
        return {}

    # clamp wavelength to valid range
    W = data.shape[1]
    wav_idx = min(max(0, int(wav_idx)), W - 1)
    frame_idx = int(frame_idx)

    img2d = data[frame_idx, wav_idx]

    scale = getattr(active_layer, "scale", (1.0, 1.0, 1.0))
    sy, sx = float(scale[-2]), float(scale[-1])

    out: dict[int, np.ndarray] = {}
    for roi_index, verts in enumerate(getattr(shapes_layer, "data", [])):
        verts_arr = np.asarray(verts)
        if verts_arr.ndim != 2:
            continue

        verts_pixels = verts_arr / np.array([sy, sx])
        shape_type = (
            shapes_layer.shape_type[roi_index]
            if hasattr(shapes_layer, "shape_type")
            else "polygon"
        )

        try:
            if shape_type == "ellipse":
                mask = ellipse_mask(verts_pixels, img2d.shape)
            else:
                mask = polygon_mask(verts_pixels, img2d.shape)
        except Exception:
            continue

        vals = img2d[mask]
        if vals.size and (clamp_min is not None or clamp_max is not None):
            lo = float(clamp_min) if clamp_min is not None else None
            hi = float(clamp_max) if clamp_max is not None else None
            vals = np.clip(vals, a_min=lo, a_max=hi)

        out[roi_index] = np.asarray(vals).ravel()

    return out
