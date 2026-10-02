"""Feature registry: computes every saved and live ROI statistic from a shared context.

``FEATURE_REGISTRY`` maps a column name to a ``FeatureSpec``, so adding a measurement
is a one-line registry entry rather than a change to the measurement loop itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import numpy as np

if TYPE_CHECKING:
    from optari.roi.roi_utils import IntensityClamp


@dataclass(frozen=True)
class ROIContext:
    """Everything one measurement needs: identifiers, provenance, the geometry blob
    and the pixel values a ``FeatureSpec`` reads.

    Provenance covers ``scan_name``, ``frame``, ``channel``, ``src_layer``, timestamps
    and the intensity filter. Pixel values are ``vals_raw`` and the filtered ``vals``,
    alongside the pixel scale and the ROI's vertices.
    """

    roi_id: int
    track_id: int
    roi_group_uid: str
    src_layer: str
    kind: str
    study_folder: str
    scan_folder: str
    scan_name: str
    frame: int
    channel: object
    scan_ts: str
    roi_centroid: tuple[float, float]
    roi_geometry: str
    filepath: str
    vals_raw: np.ndarray
    vals: np.ndarray
    clamp: IntensityClamp
    sy: float
    sx: float
    verts: np.ndarray


@dataclass(frozen=True)
class FeatureSpec:
    """Pairs a dtype with a function from an :class:`ROIContext` to the column's value."""

    dtype: type
    fn: Callable[[ROIContext], object]


def _nan_stat(values: np.ndarray, fn: Callable[[np.ndarray], float]) -> float:
    """
    handles empty arrays and returns NaN instead of raising an error
    """
    if values.size == 0:
        return float("nan")
    return float(fn(values))


def _iqr(values: np.ndarray) -> float:
    """
    Interquartile range (IQR) is the difference between the 75th and 25th percentiles of the data.
    """
    return float(np.nanpercentile(values, 75) - np.nanpercentile(values, 25))


def _snr(values: np.ndarray) -> float:
    """
    Signal-to-noise ratio (SNR) is defined as the mean of the signal divided by its standard deviation.
    """
    std = float(np.nanstd(values))
    if std == 0.0:
        return float("nan")
    return float(np.nanmean(values) / std)


def _bound(value: float | None) -> float:
    return float("nan") if value is None else float(value)


def _size_mm(ctx: ROIContext) -> float:
    """
    returns the size of the ROI in mm^2 (for 2D ROIs) or length in mm (for line ROIs).
    """
    if ctx.kind == "line":
        return float(np.linalg.norm(np.diff(ctx.verts, axis=0), axis=1).sum())
    return float(ctx.vals.size * ctx.sy * ctx.sx)


FEATURE_REGISTRY: dict[str, FeatureSpec] = {
    "roi_id": FeatureSpec(int, lambda c: int(c.roi_id)),
    "track_id": FeatureSpec(int, lambda c: int(c.track_id)),
    "roi_group_uid": FeatureSpec(str, lambda c: str(c.roi_group_uid)),
    "mean": FeatureSpec(float, lambda c: _nan_stat(c.vals, np.nanmean)),
    "median": FeatureSpec(float, lambda c: _nan_stat(c.vals, np.nanmedian)),
    "std": FeatureSpec(float, lambda c: _nan_stat(c.vals, np.nanstd)),
    "p10": FeatureSpec(
        float, lambda c: _nan_stat(c.vals, lambda v: np.nanpercentile(v, 10))
    ),
    "p90": FeatureSpec(
        float, lambda c: _nan_stat(c.vals, lambda v: np.nanpercentile(v, 90))
    ),
    "iqr": FeatureSpec(float, lambda c: _nan_stat(c.vals, _iqr)),
    "min": FeatureSpec(float, lambda c: _nan_stat(c.vals, np.nanmin)),
    "max": FeatureSpec(float, lambda c: _nan_stat(c.vals, np.nanmax)),
    "snr": FeatureSpec(float, lambda c: _nan_stat(c.vals, _snr)),
    "n_pixels": FeatureSpec(int, lambda c: int(c.vals.size)),
    "size_mm": FeatureSpec(float, _size_mm),
    # How vals was filtered, so a saved number can be traced to its filter setting.
    "intensity_filter": FeatureSpec(str, lambda c: c.clamp.label),
    "filter_min": FeatureSpec(float, lambda c: _bound(c.clamp.minimum)),
    "filter_max": FeatureSpec(float, lambda c: _bound(c.clamp.maximum)),
    "src_layer": FeatureSpec(str, lambda c: str(c.src_layer)),
    "kind": FeatureSpec(str, lambda c: str(c.kind)),  # "shape_type" in napari
    "study_folder": FeatureSpec(str, lambda c: str(c.study_folder)),
    "scan_folder": FeatureSpec(str, lambda c: str(c.scan_folder)),
    "scan_name": FeatureSpec(str, lambda c: str(c.scan_name)),
    "frame": FeatureSpec(int, lambda c: int(c.frame)),
    "channel": FeatureSpec(object, lambda c: c.channel),
    # Stamped once per save by SavedRoiTable.add_measurements, empty until then.
    "roi_ts": FeatureSpec(str, lambda c: ""),
    "scan_ts": FeatureSpec(str, lambda c: str(c.scan_ts)),
    "roi_centroid": FeatureSpec(tuple, lambda c: c.roi_centroid),
    "roi_geometry": FeatureSpec(
        str, lambda c: c.roi_geometry
    ),  # JSON blob of vertices in PATATO coordinates, kind, tissue_class and source
    "filepath": FeatureSpec(str, lambda c: str(c.filepath)),
}

ALL_FEATURE_COLUMNS: list[str] = list(FEATURE_REGISTRY.keys())


def numeric_feature_ids() -> list[str]:
    """IDs of the features whose dtype is ``int`` or ``float``."""
    return [
        fid
        for fid in ALL_FEATURE_COLUMNS
        if FEATURE_REGISTRY[fid].dtype in (int, float)
    ]


# Fixed set of columns that are always included in the saved table, regardless of user settings to identify the origin of the ROI
SAVED_FIXED_SOURCE_COLUMNS: list[str] = [
    "roi_id",
    "track_id",
    "roi_group_uid",
    "study_folder",
    "scan_folder",
    "scan_name",
    "frame",
    "channel",
    "src_layer",
    "roi_ts",
    "kind",
    "scan_ts",
    "filepath",
]
