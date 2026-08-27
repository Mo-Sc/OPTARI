"""Napari viewer utilities."""

from contextlib import contextmanager

import numpy as np
from napari.viewer import Viewer
from qtpy.QtWidgets import QWidget


def show_activity_dock(viewer: Viewer, visible: bool) -> None:
    """
    Force the activity dock (progress bars, cancel buttons) open or closed.
    _toggle_activity_dock is deprecated private API access, however currently only way to force the activity dock to open
    https://github.com/napari/napari/issues/4598
    """
    viewer.window._status_bar._toggle_activity_dock(visible)


def selected_frame_idx(viewer: Viewer, n_frames: int) -> int:
    """Return the currently selected frames index, clamped to valid range.
    TODO: make sure this is used everywhere
    Also implement for channel
    """
    return int(np.clip(round(viewer.dims.point[0]), 0, n_frames - 1))
