"""Utility functions for image export and rendering."""

from __future__ import annotations

from contextlib import contextmanager
import re
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