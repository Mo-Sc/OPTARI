from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EllipseConfig:
    """Ellipse ROI placement configuration in mm."""

    width_mm: float
    height_mm: float
    depth_mm: float


class ShapeFactory:
    """Factory for ROI shape placers.

    Currently supports only: ellipse
    """

    @staticmethod
    def create_shape(roi_type: str, config: EllipseConfig) -> "ROIShape":
        if roi_type == "ellipse":
            return Ellipse(config)
        raise ValueError(f"Unknown shape type: {roi_type}")


class ROIShape(ABC):
    """Base class for ROI shapes."""

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def to_napari_verts_world(
        self,
        *,
        class_mask: np.ndarray,
        sy: float,
        sx: float,
        ty: float = 0.0,
        tx: float = 0.0,
    ) -> np.ndarray:
        """Return napari Shapes vertices in world coords (y,x).

        For ellipse: return the 4-point vertex representation used by napari.
        """


class Ellipse(ROIShape):
    """Place an ellipse ROI into a segmentation class mask.

    Behavior mirrors the approach in your `external/roi_shapes.py`:
    - horizontally centered
    - placed as high as possible in the class region along the center column
    - optional depth offset (mm) below the top border of the class region
    - trimmed by explicit width/height (mm)
    """

    def __init__(self, config: EllipseConfig):
        super().__init__(config)

    def to_napari_verts_world(
        self,
        *,
        class_mask: np.ndarray,
        sy: float,
        sx: float,
        ty: float = 0.0,
        tx: float = 0.0,
    ) -> np.ndarray:
        mask = np.asarray(class_mask, dtype=bool)
        if mask.ndim != 2:
            raise ValueError(f"Expected 2D class mask, got shape {mask.shape}")

        h, w = mask.shape
        if h == 0 or w == 0:
            raise ValueError("Empty mask")

        if sy <= 0 or sx <= 0:
            raise ValueError("Invalid scale")

        width_px = max(1, int(round(float(self.config.width_mm) / float(sx))))
        height_px = max(1, int(round(float(self.config.height_mm) / float(sy))))
        depth_px = max(0, int(round(float(self.config.depth_mm) / float(sy))))

        width_px = min(width_px, w)
        height_px = min(height_px, h)

        center_x = int(w // 2)
        col = mask[:, center_x]
        rows = np.where(col)[0]
        if rows.size == 0:
            raise ValueError("Selected class not present at image center")

        top_class = int(rows[0])
        bottom_class = int(rows[-1])
        available = bottom_class - top_class + 1
        if height_px > available:
            raise ValueError("ROI height exceeds available class depth")

        y_start = top_class + depth_px
        y_end = y_start + height_px
        if y_end > bottom_class + 1:
            # not enough space with the requested depth
            raise ValueError("ROI depth/height exceeds available class region")

        half_w = width_px / 2.0
        x0 = int(round(center_x - half_w))
        x1 = x0 + width_px
        if x0 < 0:
            x0 = 0
            x1 = width_px
        if x1 > w:
            x1 = w
            x0 = max(0, w - width_px)

        # Bounding box corners in pixel coordinates (y,x)
        y0_px = float(y_start)
        y1_px = float(y_end)
        x0_px = float(x0)
        x1_px = float(x1)

        # Convert to world coords (mm) and apply translate.
        y0 = float(ty) + y0_px * float(sy)
        y1 = float(ty) + y1_px * float(sy)
        x0w = float(tx) + x0_px * float(sx)
        x1w = float(tx) + x1_px * float(sx)

        # Napari ellipse representation: 4 vertices (rectangle corners) in (y,x).
        return np.asarray(
            [
                [y0, x0w],
                [y0, x1w],
                [y1, x1w],
                [y1, x0w],
            ],
            dtype=float,
        )
