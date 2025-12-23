from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from skimage.draw import polygon

from patari.config import dtype_map


@dataclass
class ROI:
    index: int
    kind: str
    verts: np.ndarray  # (N, 2) in layer coordinates (mm)


def _scale_sy_sx(active_layer) -> tuple[float, float]:
    scale = getattr(active_layer, "scale", (1.0, 1.0, 1.0))
    return float(scale[-2]), float(scale[-1])


def _clamp_wav_idx(active_layer, wav_idx: int) -> int:
    data = np.asarray(active_layer.data)
    if data.ndim < 2:
        return 0
    n_wavs = int(data.shape[1])
    return int(np.clip(int(wav_idx), 0, max(0, n_wavs - 1)))


def _is_reconstructed_frame(active_layer, frame_idx: int) -> bool:
    frames = getattr(active_layer, "metadata", {}).get("frames")
    return frames is None or frame_idx in frames


def _iter_rois(shapes_layer) -> list[ROI]:
    rois: list[ROI] = []
    for i, verts in enumerate(getattr(shapes_layer, "data", [])):
        verts_arr = np.asarray(verts)
        if verts_arr.ndim != 2:
            continue
        kind = (
            shapes_layer.shape_type[i]
            if hasattr(shapes_layer, "shape_type")
            else "polygon"
        )
        rois.append(ROI(index=int(i), kind=str(kind), verts=verts_arr))
    return rois


def _roi_mask(
    roi: ROI, *, sy: float, sx: float, image_shape
) -> np.ndarray | None:
    # convert mm→px (y,x)
    verts_pixels = roi.verts / np.array([sy, sx])
    try:
        if roi.kind == "ellipse":
            return ellipse_mask(verts_pixels, image_shape)
        return polygon_mask(verts_pixels, image_shape)
    except Exception:
        return None


def _apply_clamp(
    vals: np.ndarray, clamp_min: float | None, clamp_max: float | None
) -> np.ndarray:
    if vals.size == 0:
        return vals
    if clamp_min is None and clamp_max is None:
        return vals
    lo = float(clamp_min) if clamp_min is not None else None
    hi = float(clamp_max) if clamp_max is not None else None
    return np.clip(vals, a_min=lo, a_max=hi)


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
    """Compute ROI statistics for all shapes for a specific frame/wavelength."""

    empty = pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)
    if active_layer is None:
        return empty

    frame_idx = int(frame_idx)
    if not _is_reconstructed_frame(active_layer, frame_idx):
        # this frame was zero-padded → return empty stats
        return empty

    wav_idx = _clamp_wav_idx(active_layer, wav_idx)
    data = np.asarray(active_layer.data)
    img2d = data[frame_idx, wav_idx]

    sy, sx = _scale_sy_sx(active_layer)

    rows = []
    for roi in _iter_rois(shapes_layer):
        mask = _roi_mask(roi, sy=sy, sx=sx, image_shape=img2d.shape)
        if mask is None:
            continue

        vals = img2d[mask]
        vals_stats = _apply_clamp(vals, clamp_min, clamp_max)
        if vals.size == 0:
            stats = dict(
                roi_index=roi.index,
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
                roi_index=roi.index,
                n_pixels=int(vals.size),
                area_mm2=float(vals.size * sy * sx),
                mean=float(np.nanmean(vals_stats)),
                median=float(np.nanmedian(vals_stats)),
                std=float(np.nanstd(vals_stats)),
                min=float(np.nanmin(vals_stats)),
                max=float(np.nanmax(vals_stats)),
            )

        wavelengths = active_layer.metadata.get("wavelengths", None)
        if isinstance(wavelengths, (list, tuple)) and 0 <= wav_idx < len(
            wavelengths
        ):
            wav_val = wavelengths[wav_idx]
        else:
            wav_val = wav_idx

        filepath = active_layer.metadata.get("filepath", "")
        scan_id = Path(filepath).stem.split("_")[1] if filepath else ""
        stats["source_layer"] = active_layer.name
        stats["roi_type"] = roi.kind
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
    """Compute per-ROI mean intensity over time for a fixed wavelength."""

    if active_layer is None:
        return np.asarray([]), {}

    data = np.asarray(active_layer.data)
    if data.ndim < 3:
        return np.asarray([]), {}

    n_frames = data.shape[0]
    wav_idx = _clamp_wav_idx(active_layer, wav_idx)

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

    sy, sx = _scale_sy_sx(active_layer)
    img_shape = data.shape[-2:]

    series: dict[int, np.ndarray] = {}
    for roi in _iter_rois(shapes_layer):
        mask = _roi_mask(roi, sy=sy, sx=sx, image_shape=img_shape)
        if mask is None:
            continue

        y = []
        for frame_idx in frames:
            if not _is_reconstructed_frame(active_layer, int(frame_idx)):
                continue
            img2d = data[int(frame_idx), wav_idx]
            vals = img2d[mask]
            vals = _apply_clamp(vals, clamp_min, clamp_max)
            y.append(float(np.nanmean(vals)) if vals.size else np.nan)
        series[int(roi.index)] = np.asarray(y, dtype=float)

    return np.asarray(x, dtype=float), series


def extract_roi_pixels_for_slice(
    shapes_layer,
    active_layer,
    frame_idx: int,
    wav_idx: int,
    *,
    clamp_min: float | None = None,
    clamp_max: float | None = None,
):
    """Extract pixel values per ROI for the given frame/wavelength."""

    if active_layer is None:
        return {}

    frame_idx = int(frame_idx)
    if not _is_reconstructed_frame(active_layer, frame_idx):
        return {}

    wav_idx = _clamp_wav_idx(active_layer, wav_idx)
    data = np.asarray(active_layer.data)
    img2d = data[frame_idx, wav_idx]
    sy, sx = _scale_sy_sx(active_layer)

    out: dict[int, np.ndarray] = {}
    for roi in _iter_rois(shapes_layer):
        mask = _roi_mask(roi, sy=sy, sx=sx, image_shape=img2d.shape)
        if mask is None:
            continue
        vals = img2d[mask]
        out[int(roi.index)] = _apply_clamp(vals, clamp_min, clamp_max)
    return out
