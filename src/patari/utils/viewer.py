"""Napari viewer utilities."""

import numpy as np
from napari.viewer import Viewer


def show_activity_dock(viewer: Viewer, visible: bool) -> None:
    """
    Force the activity dock (progress bars, cancel buttons) open or closed.
    _toggle_activity_dock is deprecated private API access, however currently only way to force the activity dock to open
    https://github.com/napari/napari/issues/4598
    """
    viewer.window._status_bar._toggle_activity_dock(visible)


def selected_frame_idx(viewer: Viewer, n_frames: int) -> int:
    """Return the currently selected frame index, clamped to valid range."""
    return int(np.clip(round(viewer.dims.point[0]), 0, n_frames - 1))


def selected_frame_and_channel(viewer: Viewer) -> tuple[int, int] | None:
    """Current ``(frame, channel)`` from the viewer dims.
    ``None`` when the viewer has no channel axis.
    """
    point = list(viewer.dims.point)
    if len(point) < 2:
        return None
    return int(round(point[0])), int(round(point[1]))
