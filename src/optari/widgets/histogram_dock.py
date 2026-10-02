from __future__ import annotations

from .dock_helpers import RoiPlotsDock


class HistogramDock(RoiPlotsDock):
    """Per-ROI intensity histograms for the current layer, frame and channel."""


def create_histogram_dock() -> HistogramDock:
    return HistogramDock.create(
        status_text="Click 'Refresh' to compute ROI histograms.",
        refresh_tooltip=(
            "Recompute intensity histograms for the active ROI(s) on the current layer, "
            "frame, and channel"
        ),
    )
