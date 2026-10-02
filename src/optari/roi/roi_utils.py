"""Functions that measure ROIs against reconstructed image data.

``iter_roi_masks`` turns world-space ROIs into pixel indices, ``IntensityClamp``
filters outlier values before a statistic is computed, and ``compute_roi_stats``
builds an ``ROIContext`` per ROI and evaluates the requested ``FEATURE_REGISTRY``
entries.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from skimage.draw import ellipse, polygon
from optari.config import settings
from optari.roi.roi_geometry import RoiGeometry
from optari.roi.roi_features import (
    ALL_FEATURE_COLUMNS,
    FEATURE_REGISTRY,
    ROIContext,
    SAVED_FIXED_SOURCE_COLUMNS,
)
from optari.roi.roi_records import ROIRecord

logger = logging.getLogger(__name__)


def visible_feature_columns() -> list[str]:
    """Feature columns the user has enabled in settings, determines the live table's columns."""
    return [
        c
        for c in ALL_FEATURE_COLUMNS
        if int(settings.annotation.roi_features.get(c, 0)) == 1
    ]


def _saved_columns(extras: list[str]) -> list[str]:
    """Origin columns, which always identify the ROI, followed by the given features."""
    return SAVED_FIXED_SOURCE_COLUMNS + [
        c for c in extras if c not in SAVED_FIXED_SOURCE_COLUMNS
    ]


def saved_table_columns() -> list[str]:
    """Columns shown in the saved table: origin columns plus the enabled features."""
    return _saved_columns(visible_feature_columns())


def saved_export_columns() -> list[str]:
    """Columns stored and exported: origin columns plus every feature"""
    return _saved_columns(ALL_FEATURE_COLUMNS)


@dataclass(frozen=True)
class MeasureScope:
    """How wide a save reaches: which layers, frames and channels get measured.

    The annotation dock builds one from its checkboxes; batch mode builds one from
    its plan. Keeping it a value rather than reading widgets inside the measurement
    loop is what lets both drive the identical code.
    """

    all_layers: bool = False
    all_frames: bool = False
    all_channels: bool = False
    # Only meaningful with all_frames: use each frame's own record from the ROI's
    # track instead of reusing the selected outline everywhere.
    follow_track: bool = False


def _scale_sy_sx(active_recon_layer) -> tuple[float, float]:
    scale = active_recon_layer.scale
    return float(scale[-2]), float(scale[-1])


def _is_reconstructed_frame(active_recon_layer, frame_idx: int) -> bool:
    frames = active_recon_layer.metadata.get("frames")
    return frames is None or frame_idx in frames


def _channel_value(active_recon_layer, channel_idx: int) -> object:
    """The channel's label: a wavelength (nm) or a chromophore/parameter name."""
    label = active_recon_layer.metadata["axis1_labels"][channel_idx]
    # numpy scalars would land in the table as e.g. "np.int64(700)"
    return label.item() if isinstance(label, np.generic) else label


def slice_datetime(layer, frame_idx: int, channel_idx: int) -> str:
    """Wall-clock acquisition time of one slice, or "N/A" if the scan cannot be dated.

    See ``patato_bridge.acquisition_start`` for when a scan counts as datable.
    """
    start = layer.metadata.get("acquisition_start")
    if start is None:
        return "N/A"
    ts = layer.metadata["timestamps"]
    elapsed = float(ts[frame_idx, channel_idx] - ts[0, 0])
    return str(start + timedelta(seconds=elapsed))


def _iter_rois(records: list[ROIRecord]) -> list[ROIRecord]:
    """Filter out any degenerate (non 2D) ROI geometry."""
    return [r for r in records if r.verts.ndim == 2]


# Rasterizing is most expensive when calculating ROI statistics. the live table
# recomputes every ROI on every drag while only one of them has actually moved.
# The key covers everything a mask depends on, so a moved or resized ROI misses
# and every untouched one hits.
@lru_cache(maxsize=64)
def _rasterize(
    verts_bytes: bytes,
    n_verts: int,
    kind: str,
    sy: float,
    sx: float,
    image_shape: tuple,
) -> np.ndarray:
    verts_pixels = np.frombuffer(verts_bytes, dtype=float).reshape(
        n_verts, 2
    ) / np.array([sy, sx])
    mask = (
        ellipse_mask(verts_pixels, image_shape)
        if kind == "ellipse"
        else polygon_mask(verts_pixels, image_shape)
    )
    mask.flags.writeable = (
        False  # shared between callers; must never be mutated
    )
    return mask


def clear_mask_cache() -> None:
    """Drop cached masks, e.g. when a scan is closed."""
    _rasterize.cache_clear()


def _roi_mask(
    roi: ROIRecord,
    *,
    sy: float,
    sx: float,
    ty: float = 0.0,
    tx: float = 0.0,
    image_shape,
) -> np.ndarray | None:
    """Rasterize *roi* onto a layer with the given scale and world-space translate.

    ``roi.verts`` are world mm (the Shapes layer is untranslated). ``ty``/``tx`` is
    the *target* layer's ``translate``, subtracted here so the mask lands on the
    same pixels the ROI visually overlaps, not shifted by the layer's own offset.
    """
    verts = np.ascontiguousarray(roi.verts, dtype=float) - (ty, tx)
    try:
        return _rasterize(
            verts.tobytes(),
            len(verts),
            roi.kind,
            float(sy),
            float(sx),
            tuple(image_shape),
        )
    except (IndexError, ValueError):
        logger.warning(
            "skipping invalid ROI geometry for ROI %s",
            roi.roi_id,
            exc_info=True,
        )
        return None


def layer_fov_m(active_recon_layer, image_shape) -> tuple[float, float]:
    """Return the layer's ``(fov_x_m, fov_y_m)``, derived from its own grid.

    ``scale_from_patato_obj`` sets the scale to ``fov / n_pixels``, so the napari
    extent ``shape * scale`` is the FOV. Deriving it here rather
    than reading scan metadata also covers layers reconstructed or unmixed at
    runtime, and layers that fell back to a configured default scale.
    """
    sy, sx = _scale_sy_sx(active_recon_layer)
    return image_shape[1] * sx / 1000.0, image_shape[0] * sy / 1000.0


def _layer_translate(active_recon_layer) -> tuple[float, float]:
    """A layer is placed at ``translate`` to align reconstructions that use
    different coordinate conventions (like DeepMB)."""
    translate = active_recon_layer.translate
    return float(translate[-2]), float(translate[-1])


def records_by_track_and_frame(
    records: Iterable[ROIRecord], track_id: int
) -> dict[int, ROIRecord]:
    """One track's records, indexed by the frame each was measured on."""
    return {r.frame_id: r for r in records if r.track_id == track_id}


def iter_roi_masks(
    records: list[ROIRecord], active_recon_layer, image_shape
) -> Iterator[tuple[ROIRecord, np.ndarray]]:
    """Yield each usable ROI with its boolean mask over *image_shape*.

    Only place to trasnform world-space ROI to pixel indices.
    skips broken geometry and any ROI that fails to rasterize, so the four
    measurement functions below all agree on which ROIs are measurable.
    """
    sy, sx = _scale_sy_sx(active_recon_layer)
    ty, tx = _layer_translate(active_recon_layer)

    for roi in _iter_rois(records):
        mask = _roi_mask(
            roi, sy=sy, sx=sx, ty=ty, tx=tx, image_shape=image_shape
        )
        if mask is not None:
            yield roi, mask


@dataclass(frozen=True)
class _LayerInfo:
    """Per-layer info required for ROIContexts, resolved once instead of per ROI."""

    name: str
    filepath: str
    study_folder: str
    scan_folder: str
    scan_name: str
    channel_value: object
    sy: float
    sx: float
    fov_x_m: float
    fov_y_m: float

    @classmethod
    def resolve(cls, layer, channel_idx: int, image_shape) -> "_LayerInfo":
        """Resolve *layer*'s per-call constants once, from its metadata and scale."""
        filepath = str(layer.metadata.get("filepath", "") or "")
        sy, sx = _scale_sy_sx(layer)
        fov_x_m, fov_y_m = layer_fov_m(layer, image_shape)
        return cls(
            name=str(layer.name),
            filepath=filepath,
            study_folder=Path(filepath).parent.name if filepath else "",
            scan_folder=Path(filepath).stem if filepath else "",
            scan_name=str(layer.metadata.get("scan_name", "") or ""),
            channel_value=_channel_value(layer, channel_idx),
            sy=sy,
            sx=sx,
            fov_x_m=fov_x_m,
            fov_y_m=fov_y_m,
        )


def _roi_context(
    roi: ROIRecord,
    layer_info: _LayerInfo,
    *,
    frame_idx: int,
    scan_ts: str,
    vals_raw: np.ndarray,
    clamp: IntensityClamp,
    roi_geometry: str = "",
) -> ROIContext:
    """Assemble the data a FeatureSpec is evaluated against."""
    return ROIContext(
        roi_id=roi.roi_id,
        track_id=roi.track_id,
        roi_group_uid=roi.roi_group_uid,
        src_layer=layer_info.name,
        kind=roi.kind,
        study_folder=layer_info.study_folder,
        scan_folder=layer_info.scan_folder,
        scan_name=layer_info.scan_name,
        frame=int(frame_idx),
        channel=layer_info.channel_value,
        scan_ts=scan_ts,
        roi_centroid=_roi_centroid_mm(roi),
        roi_geometry=roi_geometry,
        filepath=layer_info.filepath,
        vals_raw=vals_raw,
        vals=clamp.apply(vals_raw),
        clamp=clamp,
        sy=layer_info.sy,
        sx=layer_info.sx,
        verts=roi.verts,
    )


def _roi_centroid_mm(roi: ROIRecord) -> tuple[float, float]:
    """Centroid in *world* mm, deliberately not layer-local.

    This is only display/informational column, so it is left in the same
    space the user draws in (napari viewer world coordinates)
    """
    if roi.verts.size == 0:
        return (float("nan"), float("nan"))
    yx = np.asarray(roi.verts, dtype=float).mean(axis=0)
    return round(float(yx[0]), 2), round(float(yx[1]), 2)


def _resolve_feature_ids(feature_ids: list[str] | None) -> list[str]:
    if feature_ids is None:
        return list(ALL_FEATURE_COLUMNS)
    return [
        feature_id
        for feature_id in feature_ids
        if feature_id in FEATURE_REGISTRY
    ]


@dataclass(frozen=True)
class IntensityClamp:
    """How ROI pixel values are filtered before any statistic is computed.

    ``clip`` bounds out-of-range values back into given range (keeping the pixel count).
    ``exclude`` drops them, which also changes ``n_pixels`` and ``size_mm``.
    The default instance is a no-op, so callers that do not filter pass nothing.
    """

    minimum: float | None = None
    maximum: float | None = None
    mode: str = "clip"

    @property
    def label(self) -> str:
        """What is recorded with each measurement: the mode, or ``none`` without bounds."""
        return (
            "none"
            if self.minimum is None and self.maximum is None
            else self.mode
        )

    def apply(self, values: np.ndarray) -> np.ndarray:
        """Apply the clip or exclude policy to *values*."""
        if values.size == 0 or self.label == "none":
            return values

        low = None if self.minimum is None else float(self.minimum)
        high = None if self.maximum is None else float(self.maximum)

        if self.mode == "exclude":
            keep = np.ones(values.shape, dtype=bool)
            if low is not None:
                keep &= values >= low
            if high is not None:
                keep &= values <= high
            return values[keep]

        return np.clip(values, a_min=low, a_max=high)


NO_CLAMP = IntensityClamp()


def polygon_mask(verts_px, image_shape):
    """Rasterize a polygon (verts in pixel coords) to a boolean mask."""
    ys = np.round(verts_px[:, 0]).astype(int)
    xs = np.round(verts_px[:, 1]).astype(int)
    rr, cc = polygon(ys, xs, image_shape)
    mask = np.zeros(image_shape, dtype=bool)
    mask[rr, cc] = True
    return mask


def ellipse_mask(verts_px, image_shape):
    """Rasterize napari's 4-corner ellipse box (may be rotated) to a boolean mask."""
    p0, p1, p2 = verts_px[:3]
    cy, cx = verts_px.mean(axis=0)
    rr, cc = ellipse(
        cy,
        cx,
        np.linalg.norm(p2 - p1) / 2,
        np.linalg.norm(p1 - p0) / 2,
        shape=image_shape,
        rotation=-np.arctan2(*(p1 - p0)),
    )
    mask = np.zeros(image_shape, dtype=bool)
    mask[rr, cc] = True
    return mask


def compute_roi_stats(
    records: list[ROIRecord],
    active_recon_layer,
    frame_idx: int,
    channel_idx: int,
    *,
    clamp: IntensityClamp = NO_CLAMP,
    feature_ids: list[str] | None = None,
):
    """Compute ROI statistics for all shapes for a specific frame/channel."""

    selected_feature_ids = _resolve_feature_ids(feature_ids)
    # Serializing geometry is the expensive context field, and the live table
    # refreshes on every drag -> only compute the caller wants the column
    needs_geometry = "roi_geometry" in selected_feature_ids
    frame_idx = int(frame_idx)
    if not _is_reconstructed_frame(active_recon_layer, frame_idx):
        # this frame was zero-padded → return empty stats
        return pd.DataFrame(columns=selected_feature_ids)

    img2d = active_recon_layer.data[frame_idx, channel_idx]
    layer_info = _LayerInfo.resolve(
        active_recon_layer, channel_idx, img2d.shape
    )
    scan_ts = slice_datetime(active_recon_layer, frame_idx, channel_idx)

    rows = []
    for roi, mask in iter_roi_masks(records, active_recon_layer, img2d.shape):
        vals_raw = img2d[mask]
        ctx = _roi_context(
            roi,
            layer_info,
            frame_idx=frame_idx,
            scan_ts=scan_ts,
            vals_raw=vals_raw,
            clamp=clamp,
            roi_geometry=(
                RoiGeometry.from_record(
                    roi, layer_info.fov_x_m, layer_info.fov_y_m
                ).to_json()
                if needs_geometry
                else ""
            ),
        )
        rows.append(
            {
                feature_id: FEATURE_REGISTRY[feature_id].compute(ctx)
                for feature_id in selected_feature_ids
            }
        )

    return pd.DataFrame(rows, columns=selected_feature_ids)


def _time_axis(
    active_recon_layer, channel_idx: int
) -> tuple[np.ndarray, np.ndarray]:
    """Resolve the frame indices to plot and the x-axis value for each."""
    n_frames = active_recon_layer.data.shape[0]

    frames_meta = active_recon_layer.metadata.get("frames")
    frames = (
        np.asarray(frames_meta, dtype=int)
        if frames_meta
        else np.arange(n_frames, dtype=int)
    )

    # The plot labels its x-axis from the same metadata, see AnalysisController.
    ts = active_recon_layer.metadata.get("timestamps")
    if ts is None:
        return frames, frames.astype(float)
    # Per-channel timestamps for the plotted channel, referenced to the scan start
    ts = np.asarray(ts, dtype=float)
    return frames, ts[frames, channel_idx] - ts[0, 0]


def _time_series_setup(active_recon_layer, channel_idx: int):
    """Shared setup for both time-series scopes: the layer's data, the frames and
    x-axis values to plot, the image shape and the per-layer constants.
    """
    data = active_recon_layer.data
    frames, x = _time_axis(active_recon_layer, channel_idx)
    img_shape = data.shape[-2:]
    layer_info = _LayerInfo.resolve(active_recon_layer, channel_idx, img_shape)
    return data, frames, x, img_shape, layer_info


def _measure_series(
    active_recon_layer,
    data: np.ndarray,
    channel_idx: int,
    frames: np.ndarray,
    layer_info: "_LayerInfo",
    feature_id: str,
    clamp: IntensityClamp,
    record_and_mask_at: Callable[[int], tuple[ROIRecord, np.ndarray] | None],
) -> np.ndarray:
    """One feature value per frame in *frames*.

    ``record_and_mask_at(frame_idx)`` resolves what to measure on that frame:
    a fixed record for the "Selected ROI" scope, that frame's own tracked record
    for "Track ID". Returning None (frame not reconstructed, or nothing tracked
    there) leaves a gap (``NaN``)
    """
    y = []
    for frame_idx in frames:
        frame_idx = int(frame_idx)
        resolved = (
            record_and_mask_at(frame_idx)
            if _is_reconstructed_frame(active_recon_layer, frame_idx)
            else None
        )
        if resolved is None:
            y.append(np.nan)
            continue
        record, mask = resolved
        vals_raw = data[frame_idx, channel_idx][mask]
        ctx = _roi_context(
            record,
            layer_info,
            frame_idx=frame_idx,
            scan_ts=slice_datetime(active_recon_layer, frame_idx, channel_idx),
            vals_raw=vals_raw,
            clamp=clamp,
        )
        y.append(float(FEATURE_REGISTRY[feature_id].compute(ctx)))
    return np.asarray(y, dtype=float)


def compute_roi_time_series(
    records: list[ROIRecord],
    active_recon_layer,
    channel_idx: int,
    feature_id: str,
    *,
    clamp: IntensityClamp = NO_CLAMP,
):
    """Compute per-ROI feature over time for a fixed channel.

    Each of *records* is measured with **the same fixed shape on every frame**.
    Used for the "Selected ROI" scope: whatever a shape looks like right now is used
    for the whole sequence.
    """
    data, frames, x, img_shape, layer_info = _time_series_setup(
        active_recon_layer, channel_idx
    )

    series: dict[int, np.ndarray] = {}
    # One mask per ROI, reused across every frame: geometry is fixed here, only the
    # pixel values underneath it change.
    for roi, mask in iter_roi_masks(records, active_recon_layer, img_shape):
        series[roi.roi_id] = _measure_series(
            active_recon_layer,
            data,
            channel_idx,
            frames,
            layer_info,
            feature_id,
            clamp,
            lambda frame_idx, roi=roi, mask=mask: (roi, mask),
        )

    return np.asarray(x, dtype=float), series


def compute_roi_track_time_series(
    track_id: int,
    records: list[ROIRecord],
    active_recon_layer,
    channel_idx: int,
    feature_id: str,
    *,
    clamp: IntensityClamp = NO_CLAMP,
):
    """Compute one feature over time for a tracked ROI.

    Unlike ``compute_roi_time_series``, each frame is measured on **its own record**.
    Used fot the "Track ID" scope. E.g. for a shape that was moved or restored frame by frame to
    follow anatomy. A frame the track has no record on is left as a gap (``NaN``)

    Returns the same ``(x, {key: y})`` shape as ``compute_roi_time_series``, here
    with a single entry, keyed by *track_id*
    """
    data, frames, x, img_shape, layer_info = _time_series_setup(
        active_recon_layer, channel_idx
    )
    sy, sx = layer_info.sy, layer_info.sx
    ty, tx = _layer_translate(active_recon_layer)

    records_by_frame = records_by_track_and_frame(records, track_id)
    if not records_by_frame:
        return np.asarray(x, dtype=float), {}

    def record_and_mask_at(
        frame_idx: int,
    ) -> tuple[ROIRecord, np.ndarray] | None:
        """Track ID's resolver: *frame_idx*'s own tracked record and mask, or None if the track has none there."""
        record = records_by_frame.get(frame_idx)
        if record is None:
            return None
        mask = _roi_mask(
            record, sy=sy, sx=sx, ty=ty, tx=tx, image_shape=img_shape
        )
        return None if mask is None else (record, mask)

    y = _measure_series(
        active_recon_layer,
        data,
        channel_idx,
        frames,
        layer_info,
        feature_id,
        clamp,
        record_and_mask_at,
    )
    return np.asarray(x, dtype=float), {track_id: y}


def extract_roi_pixels_for_slice(
    records: list[ROIRecord],
    active_recon_layer,
    frame_idx: int,
    channel_idx: int,
    *,
    clamp: IntensityClamp = NO_CLAMP,
):
    """Extract pixel values per ROI for the given frame/channel."""

    frame_idx = int(frame_idx)
    if not _is_reconstructed_frame(active_recon_layer, frame_idx):
        return {}

    img2d = active_recon_layer.data[frame_idx, channel_idx]

    return {
        roi.roi_id: clamp.apply(img2d[mask])
        for roi, mask in iter_roi_masks(
            records, active_recon_layer, img2d.shape
        )
    }


def compute_roi_spectra(
    records: list[ROIRecord],
    active_recon_layer,
    frame_idx: int,
    *,
    clamp: IntensityClamp = NO_CLAMP,
):
    """Compute per-ROI mean intensity over channels for a fixed frame."""

    data = active_recon_layer.data
    frame_idx = int(frame_idx)
    if not _is_reconstructed_frame(active_recon_layer, frame_idx):
        return np.asarray([]), {}, None

    n_channels = data.shape[1]
    x = np.arange(n_channels, dtype=float)
    x_tick_labels: list[str] | None = None

    axis1_labels = active_recon_layer.metadata.get("axis1_labels")
    if (
        isinstance(axis1_labels, (list, tuple))
        and len(axis1_labels) == n_channels
    ):
        x_tick_labels = [str(label) for label in axis1_labels]
    else:
        wavelengths = active_recon_layer.metadata.get("wavelengths")
        if (
            isinstance(wavelengths, (list, tuple))
            and len(wavelengths) == n_channels
        ):
            x = np.asarray(wavelengths, dtype=float)

    img_shape = data.shape[-2:]

    series: dict[int, np.ndarray] = {}
    # One mask per ROI, reused across every channel (see iter_roi_masks).
    for roi, mask in iter_roi_masks(records, active_recon_layer, img_shape):
        y = []
        for channel in range(n_channels):
            vals = clamp.apply(data[frame_idx, channel][mask])
            y.append(float(np.nanmean(vals)) if vals.size else np.nan)
        series[roi.roi_id] = np.asarray(y, dtype=float)

    return x, series, x_tick_labels
