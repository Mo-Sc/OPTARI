"""Napari viewer utilities."""

from contextlib import contextmanager

import numpy as np
from napari.viewer import Viewer
from qtpy.QtWidgets import QWidget


@contextmanager
def viewer_busy(viewer: Viewer, window: QWidget | None = None):
    """
    Show progress UI and disable the napari window during a task.
    _toggle_activity_dock is deprecated private API access, however currently only way to force the activity dock to open
    https://github.com/napari/napari/issues/4598
    """
    qt_window = viewer.window._qt_window if window is None else window
    was_enabled = qt_window.isEnabled()
    viewer.window._status_bar._toggle_activity_dock(True)
    try:
        qt_window.setEnabled(False)
        yield
    finally:
        viewer.window._status_bar._toggle_activity_dock(False)
        qt_window.setEnabled(was_enabled)


def selected_frame_idx(viewer: Viewer, n_frames: int) -> int:
    """Return the currently selected frames index, clamped to valid range.
    TODO: make sure this is used everywhere
    Also implement for channel
    """
    return int(np.clip(round(viewer.dims.point[0]), 0, n_frames - 1))
