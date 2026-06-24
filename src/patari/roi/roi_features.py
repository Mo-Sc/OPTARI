from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class ROIContext:
    roi_index: int
    src_layers: dict[str, str]
    roi_type: str
    study: str
    scan: str
    frame: int
    channel: object
    scan_ts: str
    roi_ts: str
    roi_centroid: tuple[float, float]
    filepath: str
    vals_raw: np.ndarray
    vals: np.ndarray
    sy: float
    sx: float


@dataclass(frozen=True)
class FeatureSpec:
    dtype: type
    fn: Callable[[ROIContext], object]

    def compute(self, ctx: ROIContext) -> object:
        return self.fn(ctx)


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


FEATURE_REGISTRY: dict[str, FeatureSpec] = {
    "roi_index": FeatureSpec(int, lambda c: int(c.roi_index)),
    "mean": FeatureSpec(float, lambda c: _nan_stat(c.vals, np.nanmean)),
    "median": FeatureSpec(float, lambda c: _nan_stat(c.vals, np.nanmedian)),
    "std": FeatureSpec(float, lambda c: _nan_stat(c.vals, np.nanstd)),
    "p10": FeatureSpec(float, lambda c: _nan_stat(c.vals, lambda v: np.nanpercentile(v, 10))),
    "p90": FeatureSpec(float, lambda c: _nan_stat(c.vals, lambda v: np.nanpercentile(v, 90))),
    "iqr": FeatureSpec(float, lambda c: _nan_stat(c.vals, _iqr)),
    "min": FeatureSpec(float, lambda c: _nan_stat(c.vals, np.nanmin)),
    "max": FeatureSpec(float, lambda c: _nan_stat(c.vals, np.nanmax)),
    "snr": FeatureSpec(float, lambda c: _nan_stat(c.vals, _snr)),
    "n_pixels": FeatureSpec(int, lambda c: int(c.vals.size)),
    "area_mm2": FeatureSpec(float, lambda c: float(c.vals.size * c.sy * c.sx)),
    "src_layers": FeatureSpec(object, lambda c: c.src_layers),
    "roi_type": FeatureSpec(str, lambda c: str(c.roi_type)),
    "study": FeatureSpec(str, lambda c: str(c.study)),
    "scan": FeatureSpec(str, lambda c: str(c.scan)),
    "frame": FeatureSpec(int, lambda c: int(c.frame)),
    "channel": FeatureSpec(object, lambda c: c.channel),
    "roi_ts": FeatureSpec(str, lambda c: str(c.roi_ts)),
    "scan_ts": FeatureSpec(str, lambda c: str(c.scan_ts)),
    "roi_centroid": FeatureSpec(tuple, lambda c: c.roi_centroid),
    "filepath": FeatureSpec(str, lambda c: str(c.filepath)),
}

ALL_FEATURE_COLUMNS: list[str] = list(FEATURE_REGISTRY.keys())

# Fixed set of columns that are always included in the saved table (and export xlsx), regardless of user settings to identify the origin of the ROI
SAVED_FIXED_SOURCE_COLUMNS: list[str] = [
    "study",
    "scan",
    "frame",
    "channel",
    "src_layers",
    "roi_ts",
    "roi_type",
    "scan_ts",
    "filepath",
]
