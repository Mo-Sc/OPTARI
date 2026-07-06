"""Image rendering utilities for layer export."""

from __future__ import annotations

import matplotlib.cm
import numpy as np
from matplotlib.colors import Normalize


def render_layer_to_image(
    data: np.ndarray,
    colormap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    include_colorbar: bool = False,
    transparent_background: bool = False,
) -> np.ndarray:
    """
    Render a layer to an RGB or RGBA image with colormap.
    
    Args:
        data: 2D numpy array (grayscale layer data)
        colormap: matplotlib colormap name
        vmin: minimum value for contrast
        vmax: maximum value for contrast
        include_colorbar: if True, add colorbar to right side
        transparent_background: if True, return RGBA with transparent background (data==0)
    
    Returns:
        RGB image as uint8 numpy array (H, W, 3), or
        RGBA image as uint8 numpy array (H, W, 4) if transparent_background=True
    """
    if data.ndim != 2:
        raise ValueError(f"Expected 2D data, got {data.ndim}D")
    
    # Auto-contrast if not specified
    if vmin is None:
        vmin = float(np.nanmin(data))
    if vmax is None:
        vmax = float(np.nanmax(data))
    
    # Normalize to [0, 1]
    norm = Normalize(vmin=vmin, vmax=vmax)
    normalized = norm(data)
    
    # Handle NaNs: set to 0 (will be transparent-ish or white depending on colormap)
    normalized = np.nan_to_num(normalized, nan=0.0)
    
    # Apply colormap
    cmap = matplotlib.cm.get_cmap(colormap)
    rgba = cmap(normalized)
    
    # Convert to uint8 RGB (drop alpha)
    rgb = (rgba[:, :, :3] * 255).astype(np.uint8)
    
    if transparent_background:
        # Return RGBA with transparent background where data == 0
        alpha = np.where(data == 0, 0, 255).astype(np.uint8)
        rgb = np.dstack([rgb, alpha])
    
    if include_colorbar:
        rgb = _add_colorbar_to_image(rgb, cmap)
    
    return rgb


def _add_colorbar_to_image(rgb: np.ndarray, cmap) -> np.ndarray:
    """Add a vertical gradient colorbar (bottom=vmin) to the right side of an image.

    Works for both RGB (H, W, 3) and RGBA (H, W, 4) input.
    """
    h, _, channels = rgb.shape
    cb_width = 30

    cbar_norm = np.linspace(1, 0, h)[:, np.newaxis].repeat(cb_width, axis=1)
    cbar = (cmap(cbar_norm)[:, :, :3] * 255).astype(np.uint8)
    if channels == 4:
        cbar = np.dstack([cbar, np.full((h, cb_width, 1), 255, dtype=np.uint8)])

    separator = np.full((h, 5, channels), 255, dtype=np.uint8)
    return np.hstack([rgb, separator, cbar])
