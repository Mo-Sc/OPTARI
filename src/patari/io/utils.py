"""Utility functions for image export and rendering."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re

import cv2
from napari.layers import Image
from napari.viewer import Viewer

@contextmanager
def colorbars_visible(viewer: Viewer, visible: bool):
    """
    Temporarily set built-in napari colorbar visibility for all images.
    Useful for exporting images.
    """
    image_layers = [layer for layer in viewer.layers if isinstance(layer, Image)]
    previous = [(layer, layer.colorbar.visible) for layer in image_layers]
    for layer, _ in previous:
        layer.colorbar.visible = visible
    try:
        yield
    finally:
        for layer, was_visible in previous:
            layer.colorbar.visible = was_visible


def _filename_token(text: str) -> str:
    """Reduce free text to something safe to embed in a filename."""
    token = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-")
    return token or "unknown"


def save_viewer_screenshot(
    viewer: Viewer, destination: Path, *, include_colorbars: bool = True
) -> None:
    """Write the current canvas to *destination* as PNG/TIFF.

    Shared by the Export View dialog and batch mode so an overlay saved by a batch
    run is the same image the user would have exported by hand.
    """
    with colorbars_visible(viewer, include_colorbars):
        image = viewer.screenshot(canvas_only=True)[..., :3]
    cv2.imwrite(str(destination), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
