"""Utility functions for image export and rendering."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import imageio.v3 as iio
from napari.layers import Image
from napari.viewer import Viewer

from optari import __version__


@contextmanager
def export_overlays(viewer: Viewer, include_colorbars: bool):
    """Temporarily set the canvas up for an exported image or video: colorbars of all
    images on or off, and the OPTARI version stamped bottom left.
    """
    image_layers = [
        layer for layer in viewer.layers if isinstance(layer, Image)
    ]
    previous = [(layer, layer.colorbar.visible) for layer in image_layers]
    for layer, _ in previous:
        layer.colorbar.visible = include_colorbars
    watermark = viewer.canvas.overlays.text
    previous_watermark = watermark.model_dump()
    watermark.update(
        {
            "text": f"Created by OPTARI v{__version__}",
            "position": "bottom_left",
            "visible": True,
        }
    )
    try:
        yield
    finally:
        for layer, was_visible in previous:
            layer.colorbar.visible = was_visible
        watermark.update(previous_watermark)


def save_viewer_screenshot(
    viewer: Viewer, destination: Path, *, include_colorbars: bool = True
) -> None:
    """Write the current canvas to *destination* as PNG/TIFF.

    Shared by the Export View dialog and batch mode so an overlay saved by a batch
    run is the same image the user would have exported by hand.
    """
    with export_overlays(viewer, include_colorbars):
        image = viewer.screenshot(canvas_only=True)[..., :3]
    # Not cv2.imwrite, which returns False instead of raising and has a history of
    # failing on non-ASCII paths on Windows (user folders with umlauts).
    iio.imwrite(destination, image)
