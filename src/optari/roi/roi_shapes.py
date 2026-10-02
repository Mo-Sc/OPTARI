"""ROI shapes generated from a segmentation class mask, used by the segmentation dock.

``roi_verts_from_mask`` derives a new shape's geometry from the mask (largest-component
isolation, centre-column anchoring, depth offset, contour extraction). It does not
participate in persistence, unlike ``RoiGeometry``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import cv2


@dataclass(frozen=True)
class ROIPlacementConfig:
    """ROI placement configuration in mm."""

    width_mm: float | None
    height_mm: float | None
    depth_mm: float | None


def largest_component(mask: np.ndarray) -> np.ndarray:
    """Boolean mask of *mask*'s largest connected component."""
    mask_u8 = mask.astype(np.uint8)
    if mask_u8.max() == 1:
        mask_u8 *= 255  # cv2's connectivity analysis expects a 0/255 image
    if mask_u8.shape[0] == 0 or mask_u8.shape[1] == 0:
        raise ValueError("Empty mask")

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask_u8, connectivity=8
    )
    if num_labels < 2:
        raise ValueError("Selected class is empty or not found.")

    largest_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    return labels == largest_label


def _top_at_center_column(largest_mask: np.ndarray) -> tuple[int, int]:
    """Row and column of *largest_mask*'s topmost pixel at its own horizontal centre."""
    center_col = largest_mask.shape[1] // 2
    hit_rows = np.where(largest_mask[:, center_col])[0]
    if hit_rows.size == 0:
        raise ValueError("Class not present at image center")
    return int(hit_rows[0]), center_col


def class_top_at_center_column(mask: np.ndarray) -> tuple[int, int]:
    """Row and column of the topmost pixel of *mask*'s largest component, at the
    image's horizontal centre.

    used below by the box-shaped ROI generators, and by ROI preset auto-placement
    (``RoiController._place_roi_preset_auto``) to align a saved preset the same way.
    """
    return _top_at_center_column(largest_component(mask))


def roi_verts_from_mask(
    shape_type: str,
    class_mask: np.ndarray,
    config: ROIPlacementConfig,
    *,
    sy: float,
    sx: float,
    ty: float = 0.0,
    tx: float = 0.0,
) -> np.ndarray:
    """World-mm vertices of a *shape_type* ROI placed in *class_mask*'s largest component.

    ``rectangle`` and ``ellipse`` are boxes anchored to the class's top at the centre
    column; ``polygon`` follows the class outline, trimmed to the configured bounds.
    *sy*/*sx* is the mask's pixel size and *ty*/*tx* its layer's translate, in mm.
    Raises ValueError when the shape does not fit the class.
    """
    if shape_type == "polygon":
        verts_px = _polygon_verts_px(class_mask, config, sy, sx)
    else:
        verts_px = _box_verts_px(class_mask, config, sy, sx)
    return verts_px * (sy, sx) + (ty, tx)


def _pixel_bounds(
    mask: np.ndarray,
    config: ROIPlacementConfig,
    sy: float,
    sx: float,
    use_center_anchor: bool,
) -> tuple[int, int, int, int, np.ndarray]:
    """
    Shared geometry logic to calculate the pixel bounding box for any ROI.

    sy, sx: Scale factors for Y and X dimensions.
    use_center_anchor:
        If True (Box shapes), anchors Y to the top of the class at the image center.
        If False (Polygon), anchors Y to the absolute highest point of the component.

    Returns: (x0, x1, y0, y1, largest_component_mask)
    """
    if sy <= 0 or sx <= 0:
        raise ValueError("Invalid scale")

    # 1. Isolate the largest connected component
    largest_mask = largest_component(mask)
    h, w = largest_mask.shape

    # 2. Establish Reference Points based on conventions
    center_x = w // 2

    if use_center_anchor:
        # Anchor Y to the top of the class at the horizontal center
        top_y, _ = _top_at_center_column(largest_mask)
    else:
        # Anchor Y to the absolute highest point of the component
        top_y = int(np.where(largest_mask.any(axis=1))[0][0])

    largest_mask = largest_mask.astype(
        np.uint8
    )  # cv2.findContours needs this downstream

    # 3. Calculate Trim Boundaries
    # Width: Symmetric around the scan center
    if config.width_mm is not None:
        width_px = max(1, int(round(float(config.width_mm) / float(sx))))
        x0 = max(0, center_x - width_px // 2)
        x1 = min(w, center_x - width_px // 2 + width_px)
    else:
        x0, x1 = 0, w

    # Height: Extending downwards from the established Y-anchor
    depth_mm = float(config.depth_mm or 0.0)
    depth_px = max(0, int(round(depth_mm / float(sy))))
    y0 = min(h, top_y + depth_px)

    if config.height_mm is not None:
        height_px = max(1, int(round(float(config.height_mm) / float(sy))))
        # Not clipped to the image: a box must keep its requested height or be
        # refused, and slicing past the edge is harmless for the polygon.
        y1 = y0 + height_px
    else:
        y1 = h

    return x0, x1, y0, y1, largest_mask


def _box_verts_px(
    class_mask: np.ndarray, config: ROIPlacementConfig, sy: float, sx: float
) -> np.ndarray:
    """Rectangle/ellipse corners (pixels) anchored to the class's top at the centre column.

    Raises if top margin plus height reach below the class at that column.
    """
    x0, x1, y0, y1, largest_mask = _pixel_bounds(
        class_mask, config, sy, sx, use_center_anchor=True
    )

    # The box must not reach below the class at the centre column (non-empty: the
    # anchor above was found there). The top margin counts against the depth too.
    hit_rows = np.flatnonzero(largest_mask[:, largest_mask.shape[1] // 2])
    class_depth = hit_rows[-1] - hit_rows[0] + 1
    needed_depth = y1 - hit_rows[0]
    if needed_depth > class_depth:
        raise ValueError(
            f"ROI top margin plus height ({needed_depth}px) exceeds class depth "
            f"({class_depth}px)."
        )
    return np.asarray([[y0, x0], [y0, x1], [y1, x1], [y1, x0]], dtype=float)


def _polygon_verts_px(
    class_mask: np.ndarray, config: ROIPlacementConfig, sy: float, sx: float
) -> np.ndarray:
    """Polygon (pixels) from the class's outline, trimmed to the configured bounds and
    anchored to the component's absolute top.

    TODO: holes in the mask are currently ignored. Find a good way of handling them if needed.
    """
    x0, x1, y0, y1, largest_mask = _pixel_bounds(
        class_mask, config, sy, sx, use_center_anchor=False
    )

    # Trim the mask down to the calculated boundaries
    trimmed_mask = np.zeros_like(largest_mask)
    trimmed_mask[y0:y1, x0:x1] = largest_mask[y0:y1, x0:x1]

    # Extract the outermost contour
    contours, _ = cv2.findContours(
        trimmed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        raise ValueError(
            "No polygon found after trimming. Check sizes and depth."
        )

    # cv2 returns (x, y) points; a single-point contour squeezes to 1-D
    largest_contour = max(contours, key=cv2.contourArea).reshape(-1, 2)
    return largest_contour[:, ::-1].astype(float)
