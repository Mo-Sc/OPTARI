"""Functions that measure ROIs against reconstructed image data.

``iter_roi_masks`` turns world-space ROIs into pixel indices, ``IntensityClamp``
filters outlier values before a statistic is computed, and ``roi_stat_rows`` builds an
``ROIContext`` per ROI and evaluates the requested ``FEATURE_REGISTRY`` entries.
``measure_rois`` runs that over every layer, frame and channel a save reaches.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from skimage.draw import ellipse, line, polygon
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
    # ISO 8601 in UTC, like every timestamp OPTARI writes
    return (
        (start + timedelta(seconds=elapsed))
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
    )


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
    if kind == "ellipse":
        mask = ellipse_mask(verts_pixels, image_shape)
    elif kind in ("line", "path"):
        mask = path_mask(verts_pixels, image_shape)
    else:
        mask = polygon_mask(verts_pixels, image_shape)
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


def _layer_translate(active_recon_layer) -> tuple[float, float]:
    """Where the layer's pixel 0 centre sits in world mm: half a pixel inside its FOV
    edge, plus any placement offset (like DeepMB's)."""
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

    Only place to transform world-space ROIs to pixel indices.
    skips broken geometry and any ROI that fails to rasterize, so the four
    measurement functions below all agree on which ROIs are measurable.
    """
    sy, sx = _scale_sy_sx(active_recon_layer)
    ty, tx = _layer_translate(active_recon_layer)

    for roi in records:
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

    @classmethod
    def resolve(cls, layer, channel_idx: int) -> "_LayerInfo":
        """Resolve *layer*'s per-call constants once, from its metadata and scale."""
        filepath = str(layer.metadata.get("filepath", "") or "")
        sy, sx = _scale_sy_sx(layer)
        return cls(
            name=str(layer.name),
            filepath=filepath,
            study_folder=Path(filepath).parent.name if filepath else "",
            scan_folder=Path(filepath).stem if filepath else "",
            scan_name=str(layer.metadata.get("scan_name", "") or ""),
            channel_value=_channel_value(layer, channel_idx),
            sy=sy,
            sx=sx,
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
        roi_source=roi.source,
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
    yx = roi.verts.mean(axis=0)
    return round(float(yx[0]), 2), round(float(yx[1]), 2)


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
    rr, cc = polygon(verts_px[:, 0], verts_px[:, 1], image_shape)
    mask = np.zeros(image_shape, dtype=bool)
    mask[rr, cc] = True
    return mask


def path_mask(verts_px, image_shape):
    """Rasterize an open line or path (verts in pixel coords) to the pixels it crosses.

    Not ``polygon``: it returns only the two end points of a line, and fills a path
    as if it were closed.
    """
    mask = np.zeros(image_shape, dtype=bool)
    points = np.rint(verts_px).astype(int)
    for (r0, c0), (r1, c1) in zip(points[:-1], points[1:]):
        rr, cc = line(r0, c0, r1, c1)
        inside = (
            (rr >= 0)
            & (rr < image_shape[0])
            & (cc >= 0)
            & (cc < image_shape[1])
        )
        mask[rr[inside], cc[inside]] = True
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


def roi_stat_rows(
    records: list[ROIRecord],
    layer,
    frame_idx: int,
    channel_idx: int,
    *,
    scan_fov_m: tuple[float, float],
    clamp: IntensityClamp = NO_CLAMP,
    feature_ids: list[str] = ALL_FEATURE_COLUMNS,
) -> Iterator[dict]:
    """One row of *feature_ids* per measurable ROI on one frame and channel of *layer*.

    Nothing on a frame the layer does not hold (zero padding). ``roi_geometry`` is
    converted with *scan_fov_m*, never the measured layer's own extent: ROI vertices
    are in the scan frame, and a layer with another FOV or a translate (DeepMB) would
    otherwise store the same ROI at a different position.
    """
    frame_idx = int(frame_idx)
    if not _is_reconstructed_frame(layer, frame_idx):
        return
    # Serializing geometry is the expensive context field, and the live table
    # refreshes on every drag -> only compute the caller wants the column
    needs_geometry = "roi_geometry" in feature_ids
    img2d = layer.data[frame_idx, channel_idx]
    layer_info = _LayerInfo.resolve(layer, channel_idx)
    scan_ts = slice_datetime(layer, frame_idx, channel_idx)
    for roi, mask in iter_roi_masks(records, layer, img2d.shape):
        ctx = _roi_context(
            roi,
            layer_info,
            frame_idx=frame_idx,
            scan_ts=scan_ts,
            vals_raw=img2d[mask],
            clamp=clamp,
            roi_geometry=(
                RoiGeometry.from_record(roi, *scan_fov_m).to_json()
                if needs_geometry
                else ""
            ),
        )
        yield {fid: FEATURE_REGISTRY[fid].fn(ctx) for fid in feature_ids}


def compute_roi_stats(
    records: list[ROIRecord],
    layer,
    frame_idx: int,
    channel_idx: int,
    *,
    scan_fov_m: tuple[float, float],
    clamp: IntensityClamp = NO_CLAMP,
    feature_ids: list[str] = ALL_FEATURE_COLUMNS,
) -> pd.DataFrame:
    """``roi_stat_rows`` as a table with exactly the *feature_ids* columns."""
    return pd.DataFrame(
        roi_stat_rows(
            records,
            layer,
            frame_idx,
            channel_idx,
            scan_fov_m=scan_fov_m,
            clamp=clamp,
            feature_ids=feature_ids,
        ),
        columns=feature_ids,
    )


def measure_rois(
    selected: list[ROIRecord],
    all_records: Iterable[ROIRecord],
    layers: list,
    frame_idx: int,
    channel_idx: int,
    scope: MeasureScope,
    *,
    scan_fov_m: tuple[float, float],
    clamp: IntensityClamp = NO_CLAMP,
) -> pd.DataFrame:
    """Measure the *selected* records on every layer, frame and channel *scope* reaches.

    *frame_idx* and *channel_idx* are the viewer's, used when the scope does not
    include every frame or channel. With ``follow_track`` each frame is measured on
    the selected ROI's tracked record there (from *all_records*) and a frame the track
    has no record on is left out; otherwise the selected outline is reused everywhere.
    Empty, without columns, when nothing was measured.
    """
    follow_track = scope.all_frames and scope.follow_track
    # Built once per save, not per frame, since a save may span every frame
    tracks = {
        record.track_id: (
            record,
            records_by_track_and_frame(all_records, record.track_id),
        )
        for record in selected
    }

    def records_at(frame: int) -> list[ROIRecord]:
        if not follow_track:
            return [fallback for fallback, _ in tracks.values()]
        return [track[frame] for _, track in tracks.values() if frame in track]

    rows: list[dict] = []
    for layer in layers:
        frames = (
            [int(f) for f in layer.metadata["frames"]]
            if scope.all_frames
            else [frame_idx]
        )
        # The viewer's channel index is a wavelength of the reconstruction. On a derived
        # layer (unmixed, sO2, THb) it would pick an arbitrary chromophore, so those are
        # always measured on every channel.
        every_channel = (
            scope.all_layers
            or scope.all_channels
            or layer.metadata["pa_kind"] != "recon"
        )
        channels = (
            range(layer.data.shape[1]) if every_channel else [channel_idx]
        )
        for frame in frames:
            records_here = records_at(frame)
            for channel in channels:
                rows.extend(
                    roi_stat_rows(
                        records_here,
                        layer,
                        frame,
                        channel,
                        scan_fov_m=scan_fov_m,
                        clamp=clamp,
                    )
                )
    return (
        pd.DataFrame(rows, columns=ALL_FEATURE_COLUMNS)
        if rows
        else pd.DataFrame()
    )


def time_axis(
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


def _feature_series(
    layer,
    channel_idx: int,
    frames: np.ndarray,
    feature_id: str,
    clamp: IntensityClamp,
    record_and_mask_at: Callable[[int], tuple[ROIRecord, np.ndarray] | None],
) -> np.ndarray:
    """One *feature_id* value per frame in *frames*.

    ``record_and_mask_at(frame_idx)`` resolves what to measure on that frame:
    a fixed record for the "Selected ROI" scope, that frame's own tracked record
    for "Track ID". Returning None (nothing tracked there), like a frame the layer
    does not hold, leaves a gap (``NaN``).
    """
    layer_info = _LayerInfo.resolve(layer, channel_idx)
    feature = FEATURE_REGISTRY[feature_id].fn
    y = np.full(len(frames), np.nan)
    for i, frame_idx in enumerate(map(int, frames)):
        if not _is_reconstructed_frame(layer, frame_idx):
            continue
        resolved = record_and_mask_at(frame_idx)
        if resolved is None:
            continue
        record, mask = resolved
        ctx = _roi_context(
            record,
            layer_info,
            frame_idx=frame_idx,
            # Only numeric features are plotted, none of which reads the time stamp
            scan_ts="",
            vals_raw=layer.data[frame_idx, channel_idx][mask],
            clamp=clamp,
        )
        y[i] = float(feature(ctx))
    return y


def compute_roi_time_series(
    records: list[ROIRecord],
    layer,
    channel_idx: int,
    feature_id: str,
    *,
    clamp: IntensityClamp = NO_CLAMP,
) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """Each ROI's *feature_id* over time on one channel, keyed by ``roi_id``.

    Each of *records* is measured with **the same fixed shape on every frame**.
    Used for the "Selected ROI" scope: whatever a shape looks like right now is used
    for the whole sequence.
    """
    frames, x = time_axis(layer, channel_idx)
    # One mask per ROI, reused across every frame: geometry is fixed here, only the
    # pixel values underneath it change.
    return x, {
        roi.roi_id: _feature_series(
            layer,
            channel_idx,
            frames,
            feature_id,
            clamp,
            lambda frame_idx, roi=roi, mask=mask: (roi, mask),
        )
        for roi, mask in iter_roi_masks(records, layer, layer.data.shape[-2:])
    }


def compute_roi_track_time_series(
    track_id: int,
    records: list[ROIRecord],
    layer,
    channel_idx: int,
    feature_id: str,
    *,
    clamp: IntensityClamp = NO_CLAMP,
) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """One tracked ROI's *feature_id* over time, keyed by *track_id*.

    Unlike ``compute_roi_time_series``, each frame is measured on **its own record**.
    Used for the "Track ID" scope. E.g. for a shape that was moved or restored frame by
    frame to follow anatomy. A frame the track has no record on is left as a gap (``NaN``)
    """
    frames, x = time_axis(layer, channel_idx)
    records_by_frame = records_by_track_and_frame(records, track_id)
    if not records_by_frame:
        return x, {}
    sy, sx = _scale_sy_sx(layer)
    ty, tx = _layer_translate(layer)
    image_shape = layer.data.shape[-2:]

    def record_and_mask_at(frame_idx: int):
        record = records_by_frame.get(frame_idx)
        if record is None:
            return None
        mask = _roi_mask(
            record, sy=sy, sx=sx, ty=ty, tx=tx, image_shape=image_shape
        )
        return None if mask is None else (record, mask)

    return x, {
        track_id: _feature_series(
            layer, channel_idx, frames, feature_id, clamp, record_and_mask_at
        )
    }


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
    # A categorical axis: one evenly spaced tick per channel, labelled with its
    # wavelength or chromophore, whatever the spacing of the wavelengths.
    x = np.arange(n_channels, dtype=float)
    x_tick_labels = [
        str(label) for label in active_recon_layer.metadata["axis1_labels"]
    ]

    frame = np.asarray(data[frame_idx])
    series: dict[int, np.ndarray] = {}
    # One mask per ROI, reused across every channel (see iter_roi_masks).
    for roi, mask in iter_roi_masks(
        records, active_recon_layer, frame.shape[-2:]
    ):
        means = []
        for values in frame[:, mask]:
            values = clamp.apply(values)
            means.append(float(np.nanmean(values)) if values.size else np.nan)
        series[roi.roi_id] = np.asarray(means, dtype=float)

    return x, series, x_tick_labels
