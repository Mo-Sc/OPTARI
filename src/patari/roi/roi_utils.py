from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from skimage.draw import polygon
from patari.config import settings
from patari.roi.roi_features import (
    ALL_FEATURE_COLUMNS,
    FEATURE_REGISTRY,
    ROIContext,
    SAVED_FIXED_SOURCE_COLUMNS,
)

logger = logging.getLogger(__name__)


def full_feature_columns() -> list[str]:
    return list(ALL_FEATURE_COLUMNS)


def visible_feature_columns() -> list[str]:
    """
    Checks the user settings for which ROI features are enabled and returns a list of those feature names.
    """
    valid = [
        c for c in ALL_FEATURE_COLUMNS
        if c in FEATURE_REGISTRY and int(settings.annotation.roi_features.get(c, 0)) == 1
    ]
    return valid


def live_table_columns() -> list[str]:
    """
    columns to show in the live table
    includes only the features that are enabled in the user settings
    """
    return visible_feature_columns()


def saved_table_columns() -> list[str]:
    """ 
    columns to show in the saved table
    Includes the visible features that are enabled in the user settings and a fixed set of columns that identify the origin of the ROI
    """
    visible = [
        c for c in visible_feature_columns()
        if c not in SAVED_FIXED_SOURCE_COLUMNS and c != "roi_index"
    ]
    return list(SAVED_FIXED_SOURCE_COLUMNS) + visible


def saved_export_columns() -> list[str]:
    """
    columns to export to xlsx.
    Includes all available statistical and roi source features
    """
    stats = [
        c for c in full_feature_columns()
        if c not in SAVED_FIXED_SOURCE_COLUMNS and c != "roi_index"
    ]
    return list(SAVED_FIXED_SOURCE_COLUMNS) + stats

@dataclass
class ROI:
    index: int
    kind: str
    verts: np.ndarray  # (N, 2) in layer coordinates (mm)


def _scale_sy_sx(active_recon_layer) -> tuple[float, float]:
    scale = getattr(active_recon_layer, "scale", (1.0, 1.0, 1.0))
    return float(scale[-2]), float(scale[-1])


def _clamp_channel_idx(active_recon_layer, channel_idx: int) -> int:
    data = np.asarray(active_recon_layer.data)
    if data.ndim < 2:
        return 0
    n_channels = int(data.shape[1])
    return int(np.clip(int(channel_idx), 0, max(0, n_channels - 1)))


def _is_reconstructed_frame(active_recon_layer, frame_idx: int) -> bool:
    frames = getattr(active_recon_layer, "metadata", {}).get("frames")
    return frames is None or frame_idx in frames


def _channel_value(active_recon_layer, channel_idx: int) -> object:
    axis1_labels = active_recon_layer.metadata.get("axis1_labels")
    if isinstance(axis1_labels, (list, tuple)) and 0 <= channel_idx < len(
        axis1_labels
    ):
        channel_value = axis1_labels[channel_idx]
    else:
        wavelengths = active_recon_layer.metadata.get("wavelengths", None)
        if isinstance(
            wavelengths, (list, tuple)
        ) and 0 <= channel_idx < len(wavelengths):
            channel_value = wavelengths[channel_idx]
        else:
            channel_value = channel_idx

    if isinstance(channel_value, np.generic):
        channel_value = channel_value.item()
    if isinstance(channel_value, (bytes, bytearray)):
        channel_value = channel_value.decode("utf-8")
    if isinstance(channel_value, float) and channel_value.is_integer():
        channel_value = int(channel_value)
    if isinstance(channel_value, str):
        try:
            channel_value = int(channel_value)
        except ValueError:
            pass
    return channel_value


def _timestamp_str(active_recon_layer, frame_idx: int, channel_idx: int) -> str:
    timestamps = getattr(active_recon_layer, "metadata", {}).get("timestamps")
    try:
        from datetime import datetime, timedelta

        return str(
            datetime(1, 1, 1)
            + timedelta(seconds=float(timestamps[frame_idx, channel_idx]))
        )
    except Exception:
        logger.info(
            "could not parse timestamp for frame %s channel %s",
            frame_idx,
            channel_idx,
        )
        return "N/A"


def _roi_source(shapes_layer, roi_index: int) -> str:
    props = dict(getattr(shapes_layer, "properties", {}) or {})
    sources = list(props.get("roi_source", []))
    if roi_index < len(sources):
        source = str(sources[roi_index] or "").strip()
        if source:
            return source
    return "PATARI"


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


def _roi_centroid_mm(roi: ROI) -> tuple[float, float]:
    if roi.verts.size == 0:
        return (float("nan"), float("nan"))
    yx = np.asarray(roi.verts, dtype=float).mean(axis=0)
    return round(float(yx[0]), 2), round(float(yx[1]), 2)


def _resolve_feature_ids(feature_ids: list[str] | None) -> list[str]:
    if feature_ids is None:
        return full_feature_columns()
    return [feature_id for feature_id in feature_ids if feature_id in FEATURE_REGISTRY]


def _apply_clamp(
    vals: np.ndarray,
    clamp_min: float | None,
    clamp_max: float | None,
    *,
    mode: str = "clip",
) -> np.ndarray:
    if vals.size == 0:
        return vals
    if clamp_min is None and clamp_max is None:
        return vals

    lo = float(clamp_min) if clamp_min is not None else None
    hi = float(clamp_max) if clamp_max is not None else None

    if mode == "exclude":
        mask = np.ones(vals.shape, dtype=bool)
        if lo is not None:
            mask &= vals >= lo
        if hi is not None:
            mask &= vals <= hi
        return vals[mask]

    # default: clip
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
    active_recon_layer,
    frame_idx: int,
    channel_idx: int,
    *,
    clamp_min: float | None = None,
    clamp_max: float | None = None,
    clamp_mode: str = "clip",
    feature_ids: list[str] | None = None,
):
    """Compute ROI statistics for all shapes for a specific frame/channel."""

    selected_feature_ids = _resolve_feature_ids(feature_ids)
    empty = pd.DataFrame(columns=selected_feature_ids)
    if active_recon_layer is None:
        return empty

    frame_idx = int(frame_idx)
    if not _is_reconstructed_frame(active_recon_layer, frame_idx):
        # this frame was zero-padded → return empty stats
        return empty

    channel_idx = _clamp_channel_idx(active_recon_layer, channel_idx)
    data = np.asarray(active_recon_layer.data)
    img2d = data[frame_idx, channel_idx]

    scan_ts = _timestamp_str(active_recon_layer, frame_idx, channel_idx)

    sy, sx = _scale_sy_sx(active_recon_layer)
    channel_value = _channel_value(active_recon_layer, channel_idx)
    filepath = str(active_recon_layer.metadata.get("filepath", "") or "")
    scan = Path(filepath).stem if filepath else ""
    study = Path(filepath).parent.name if filepath else ""

    rows = []
    for roi in _iter_rois(shapes_layer):
        mask = _roi_mask(roi, sy=sy, sx=sx, image_shape=img2d.shape)
        if mask is None:
            continue

        vals_raw = img2d[mask]
        vals = _apply_clamp(
            vals_raw,
            clamp_min,
            clamp_max,
            mode=str(clamp_mode or "clip"),
        )

        ctx = ROIContext(
            roi_index=roi.index,
            src_layers={
                "data": str(active_recon_layer.name),
                "mask": _roi_source(shapes_layer, roi.index),
            },
            roi_type=roi.kind,
            study=study,
            scan=scan,
            frame=int(frame_idx),
            channel=channel_value,
            scan_ts=scan_ts,
            roi_ts="",
            roi_centroid=_roi_centroid_mm(roi),
            filepath=filepath,
            vals_raw=vals_raw,
            vals=vals,
            sy=sy,
            sx=sx,
        )
        rows.append(
            {
                feature_id: FEATURE_REGISTRY[feature_id].compute(ctx)
                for feature_id in selected_feature_ids
            }
        )

    df = pd.DataFrame(rows, columns=selected_feature_ids)
    if not df.empty and "roi_index" in df.columns:
        df["roi_index"] = pd.to_numeric(df["roi_index"], errors="coerce").astype(int)
    return df


def compute_roi_time_series(
    shapes_layer,
    active_recon_layer,
    channel_idx: int,
    *,
    clamp_min: float | None = None,
    clamp_max: float | None = None,
    clamp_mode: str = "clip",
):
    """Compute per-ROI mean intensity over time for a fixed channel."""

    if active_recon_layer is None:
        return np.asarray([]), {}

    data = np.asarray(active_recon_layer.data)
    if data.ndim < 3:
        return np.asarray([]), {}

    n_frames = data.shape[0]
    channel_idx = _clamp_channel_idx(active_recon_layer, channel_idx)

    frames_meta = getattr(active_recon_layer, "metadata", {}).get("frames")
    if frames_meta:
        frames = np.asarray(frames_meta, dtype=int)
    else:
        frames = np.arange(n_frames, dtype=int)

    ts = getattr(active_recon_layer, "metadata", {}).get("timestamps")
    if ts is not None:
        try:
            ts = np.asarray(ts)
            # Use per-channel timestamps for the plotted channel,
            # but reference all values to scan start
            x = ts[frames, channel_idx].astype(float)
            x = x - float(ts[0, 0])
        except Exception:
            x = frames.astype(float)
    else:
        x = frames.astype(float)

    sy, sx = _scale_sy_sx(active_recon_layer)
    img_shape = data.shape[-2:]

    series: dict[int, np.ndarray] = {}
    for roi in _iter_rois(shapes_layer):
        mask = _roi_mask(roi, sy=sy, sx=sx, image_shape=img_shape)
        if mask is None:
            continue

        y = []
        for frame_idx in frames:
            if not _is_reconstructed_frame(active_recon_layer, int(frame_idx)):
                continue
            img2d = data[int(frame_idx), channel_idx]
            vals = img2d[mask]
            vals = _apply_clamp(
                vals,
                clamp_min,
                clamp_max,
                mode=str(clamp_mode or "clip"),
            )
            y.append(float(np.nanmean(vals)) if vals.size else np.nan)
        series[int(roi.index)] = np.asarray(y, dtype=float)

    return np.asarray(x, dtype=float), series


def extract_roi_pixels_for_slice(
    shapes_layer,
    active_recon_layer,
    frame_idx: int,
    channel_idx: int,
    *,
    clamp_min: float | None = None,
    clamp_max: float | None = None,
    clamp_mode: str = "clip",
):
    """Extract pixel values per ROI for the given frame/channel."""

    if active_recon_layer is None:
        return {}

    frame_idx = int(frame_idx)
    if not _is_reconstructed_frame(active_recon_layer, frame_idx):
        return {}

    channel_idx = _clamp_channel_idx(active_recon_layer, channel_idx)
    data = np.asarray(active_recon_layer.data)
    img2d = data[frame_idx, channel_idx]
    sy, sx = _scale_sy_sx(active_recon_layer)

    out: dict[int, np.ndarray] = {}
    for roi in _iter_rois(shapes_layer):
        mask = _roi_mask(roi, sy=sy, sx=sx, image_shape=img2d.shape)
        if mask is None:
            continue
        vals = img2d[mask]
        out[int(roi.index)] = _apply_clamp(
            vals,
            clamp_min,
            clamp_max,
            mode=str(clamp_mode or "clip"),
        )
    return out


def compute_roi_spectra(
    shapes_layer,
    active_recon_layer,
    frame_idx: int,
    *,
    clamp_min: float | None = None,
    clamp_max: float | None = None,
    clamp_mode: str = "clip",
):
    """Compute per-ROI mean intensity over channels for a fixed frame."""

    if active_recon_layer is None:
        return np.asarray([]), {}, None

    data = np.asarray(active_recon_layer.data)
    if data.ndim < 2:
        return np.asarray([]), {}, None

    frame_idx = int(frame_idx)
    if not _is_reconstructed_frame(active_recon_layer, frame_idx):
        return np.asarray([]), {}, None

    n_channels = data.shape[1]
    x = np.arange(n_channels, dtype=float)
    x_tick_labels: list[str] | None = None

    axis1_labels = getattr(active_recon_layer, "metadata", {}).get(
        "axis1_labels", None
    )
    if (
        isinstance(axis1_labels, (list, tuple))
        and len(axis1_labels) == n_channels
    ):
        x_tick_labels = [str(label) for label in axis1_labels]
    else:
        wavelengths = getattr(active_recon_layer, "metadata", {}).get(
            "wavelengths", None
        )
        if (
            isinstance(wavelengths, (list, tuple))
            and len(wavelengths) == n_channels
        ):
            x = np.asarray(wavelengths, dtype=float)

    sy, sx = _scale_sy_sx(active_recon_layer)
    img_shape = data.shape[-2:]

    series: dict[int, np.ndarray] = {}
    for roi in _iter_rois(shapes_layer):
        mask = _roi_mask(roi, sy=sy, sx=sx, image_shape=img_shape)
        if mask is None:
            continue
        y = []
        for channel in range(n_channels):
            vals = data[frame_idx, channel][mask]
            vals = _apply_clamp(
                vals, clamp_min, clamp_max, mode=str(clamp_mode or "clip")
            )
            y.append(float(np.nanmean(vals)) if vals.size else np.nan)
        series[int(roi.index)] = np.asarray(y, dtype=float)

    return x, series, x_tick_labels
