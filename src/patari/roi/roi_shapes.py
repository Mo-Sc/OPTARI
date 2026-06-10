from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ROIPlacementConfig:
    """ROI placement configuration in mm."""

    width_mm: float
    height_mm: float
    depth_mm: float


class ROIShape(ABC):
    """Base class for ROI shapes."""

    def __init__(self, config: ROIPlacementConfig):
        self.config = config

    @property
    @abstractmethod
    def shape_type(self) -> str:
        raise NotImplementedError

    def to_napari_verts_world(
        self,
        *,
        class_mask: np.ndarray,
        sy: float,
        sx: float,
        ty: float = 0.0,
        tx: float = 0.0,
    ) -> np.ndarray:
        """Compute 4-corner box vertices anchored to the center column of a segmentation mask.
        
        Validates mask geometry, converts dimensions from mm to pixels, finds the vertical
        extent of the selected class at the image center, and positions the ROI box within
        that region accounting for depth offset.
        
        Returns napari vertices in world coords: [[y0, x0], [y0, x1], [y1, x1], [y1, x0]].
        """
        mask = np.asarray(class_mask, dtype=bool)
        if mask.ndim != 2:
            raise ValueError(f"Expected 2D class mask, got shape {mask.shape}")

        h, w = mask.shape
        if h == 0 or w == 0:
            raise ValueError("Empty mask")
        if sy <= 0 or sx <= 0:
            raise ValueError("Invalid scale")

        # Convert ROI dimensions from mm to pixels
        width_px = max(1, int(round(float(self.config.width_mm) / float(sx))))
        height_px = max(1, int(round(float(self.config.height_mm) / float(sy))))
        depth_px = max(0, int(round(float(self.config.depth_mm) / float(sy))))

        width_px = min(width_px, w)
        height_px = min(height_px, h)

        # Anchor to center column; find vertical extent of selected class
        center_x = int(w // 2)
        rows = np.where(mask[:, center_x])[0]
        if rows.size == 0:
            raise ValueError("Selected class not present at image center")

        top_class = int(rows[0])
        bottom_class = int(rows[-1])
        available = bottom_class - top_class + 1
        if height_px > available:
            raise ValueError("ROI height exceeds available class depth")

        # Position box with depth offset from top of class region
        y_start = top_class + depth_px
        y_end = y_start + height_px
        if y_end > bottom_class + 1:
            raise ValueError("ROI depth/height exceeds available class region")

        # Center box horizontally; clip to image bounds
        half_w = width_px / 2.0
        x0 = int(round(center_x - half_w))
        x1 = x0 + width_px
        if x0 < 0:
            x0 = 0
            x1 = width_px
        if x1 > w:
            x1 = w
            x0 = max(0, w - width_px)

        # Convert pixel coords to world coords (mm)
        y0 = float(ty) + float(y_start) * float(sy)
        y1 = float(ty) + float(y_end) * float(sy)
        x0w = float(tx) + float(x0) * float(sx)
        x1w = float(tx) + float(x1) * float(sx)

        return np.asarray(
            [[y0, x0w], [y0, x1w], [y1, x1w], [y1, x0w]],
            dtype=float,
        )


class Rectangle(ROIShape):
    """Rectangular ROI shape."""

    @property
    def shape_type(self) -> str:
        return "rectangle"


class Ellipse(ROIShape):
    """Elliptical ROI shape."""

    @property
    def shape_type(self) -> str:
        return "ellipse"
