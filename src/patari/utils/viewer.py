"""Napari viewer utilities."""

import numpy as np
from napari.viewer import Viewer


def current_frame_idx(viewer: Viewer, n_frames: int) -> int:
    """Return the current frame index, clamped to valid range.
    TODO: make sure this is used everywhere
    Also implement for channel
    """
    return int(np.clip(round(viewer.dims.point[0]), 0, n_frames - 1))
