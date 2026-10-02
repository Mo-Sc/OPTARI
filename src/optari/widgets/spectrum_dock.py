from __future__ import annotations

from .dock_helpers import RoiPlotsDock


class SpectrumDock(RoiPlotsDock):
    """Per-ROI mean-intensity spectra across the channels of the current frame."""


def create_spectrum_dock() -> SpectrumDock:
    return SpectrumDock.create(
        status_text="Click 'Refresh' to compute ROI spectra.",
        refresh_tooltip=(
            "Recompute per-ROI mean-intensity spectra across channels for the current frame"
        ),
    )
