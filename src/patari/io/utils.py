"""Utility functions for image export and rendering."""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from napari.layers import Image
from napari.viewer import Viewer


def _format_limit(value: float) -> str:
    """Format contrast limit with up to 3 significant digits."""
    return f"{value:.3g}"


def add_colorbars_to_image(
    rgb: np.ndarray,
    viewer: Viewer,
    bar_width: int = 100,
    font_size: int = 10,
) -> np.ndarray:
    """Append labeled colorbars for all visible Image layers to the right of an image."""
    image_layers = [layer for layer in viewer.layers if isinstance(layer, Image) and layer.visible]
    if not image_layers:
        return rgb

    h = rgb.shape[0]
    n_bars = len(image_layers)
    total_width = bar_width * n_bars

    fig = Figure(figsize=(total_width / 100, h / 100), dpi=100)
    fig.patch.set_alpha(0)
    canvas = FigureCanvasAgg(fig)
    axes = fig.subplots(1, n_bars)
    if n_bars == 1:
        axes = [axes]

    for ax, layer in zip(axes, image_layers):
        cmap = layer.colormap.name
        vmin, vmax = layer.contrast_limits
        gradient = np.linspace(1, 0, h).reshape(-1, 1)
        ax.imshow(gradient, aspect="auto", cmap=cmap, vmin=0, vmax=1)
        ax.set_xticks([])
        ax.set_yticks([0, h - 1])
        ax.set_yticklabels([f"{vmax:.3g}", f"{vmin:.3g}"], fontsize=font_size)
        bar_title = layer.name.split(":", 1)[0] if ":" in layer.name else layer.name
        ax.set_title(bar_title, fontsize=font_size, rotation=90, pad=10)
        for spine in ax.spines.values():
            spine.set_visible(False)

    fig.tight_layout(pad=0.2)
    canvas.draw()
    colorbar_strip = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8).reshape(h, total_width, 4)[..., :3]

    separator = np.full((h, 5, 3), 255, dtype=np.uint8)
    return np.hstack([rgb, separator, colorbar_strip])


def pad_image(img: np.ndarray, padding: int = 10, fill: int = 255) -> np.ndarray:
    """Add padding around image. Background is white."""
    h, w = img.shape[:2]
    padded = np.full((h + 2 * padding, w + 2 * padding, 3), fill, dtype=img.dtype)
    padded[padding:padding + h, padding:padding + w] = img
    return padded