from __future__ import annotations

from abc import ABC, abstractmethod
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
    """Boolean mask of *mask*'s largest connected component.
    """
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


class ROIShape(ABC):
    """Base class for ROI shapes.
    TODO: Should we unify this with ROIGeometry?
    """

    def __init__(self, config: ROIPlacementConfig):
        self.config = config

    @property
    @abstractmethod
    def shape_type(self) -> str:
        raise NotImplementedError

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
        """Convert the shape into Napari world coordinate vertices."""
        pass

    def _get_pixel_bounds(
        self, mask: np.ndarray, sy: float, sx: float, use_center_anchor: bool = False
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

        largest_mask = largest_mask.astype(np.uint8)  # cv2.findContours needs this downstream

        # 3. Calculate Trim Boundaries
        # Width: Symmetric around the scan center
        if self.config.width_mm is not None:
            width_px = max(1, int(round(float(self.config.width_mm) / float(sx))))
            half_w = width_px // 2
            x0 = max(0, center_x - half_w)
            x1 = min(w, center_x + half_w)
        else:
            x0, x1 = 0, w

        # Height: Extending downwards from the established Y-anchor
        depth_mm = float(self.config.depth_mm or 0.0)
        depth_px = max(0, int(round(depth_mm / float(sy))))
        y0 = min(h, top_y + depth_px)
        
        if self.config.height_mm is not None:
            height_px = max(1, int(round(float(self.config.height_mm) / float(sy))))
            y1 = min(h, y0 + height_px)
        else:
            y1 = h

        return x0, x1, y0, y1, largest_mask

class BoxShape(ROIShape):
    """Intermediate base class for shapes using the center-column reference."""

    def to_napari_verts_world(
        self,
        *,
        class_mask: np.ndarray,
        sy: float,
        sx: float,
        ty: float = 0.0,
        tx: float = 0.0,
    ) -> np.ndarray:
        # Get standardized bounds
        x0, x1, y0, y1, largest_mask = self._get_pixel_bounds(class_mask, sy, sx, use_center_anchor=True)

        # check for overextensions
        # Find the actual vertical extent of the largest component in the center column
        center_x = largest_mask.shape[1] // 2
        hit_rows = np.where(largest_mask[:, center_x])[0]
        if hit_rows.size > 0:
            available_depth = hit_rows[-1] - hit_rows[0] + 1
            requested_height = y1 - y0
            if requested_height > available_depth:
                raise ValueError(
                    f"Error: ROI height ({requested_height}px) exceeds class depth ({available_depth}px)."
                    )

        # Alternative: strict pixel-level check for any overextension outside the class mask
        # roi_region = np.zeros_like(largest_mask)
        # roi_region[y0:y1, x0:x1] = 1
        # # Check if any pixel in the ROI region is NOT in the class mask
        # overextension = cv2.bitwise_and(roi_region, cv2.bitwise_not(largest_mask))
        # if cv2.countNonZero(overextension) > 0:
        #     raise ValueError("Error: ROI extends outside the selected segmentation class.")


        y0w = float(ty) + float(y0) * float(sy)
        y1w = float(ty) + float(y1) * float(sy)
        x0w = float(tx) + float(x0) * float(sx)
        x1w = float(tx) + float(x1) * float(sx)

        return np.asarray(
            [[y0w, x0w], [y0w, x1w], [y1w, x1w], [y1w, x0w]],
            dtype=float,
        )


class Rectangle(BoxShape):
    """Rectangular ROI shape."""
    @property
    def shape_type(self) -> str:
        return "rectangle"


class Ellipse(BoxShape):
    """Elliptical ROI shape."""
    @property
    def shape_type(self) -> str:
        return "ellipse"


class Polygon(ROIShape):
    """
    Polygonal ROI shape.
    TODO: holes in the mask are currently ignored. Find a good way of handling them if needed.

    Conventions:
    - Reference X: Horizontal center of the scan.
    - Reference Y: Absolute highest point of the largest class component.
    """

    @property
    def shape_type(self) -> str:
        return "polygon"

    def to_napari_verts_world(
        self,
        *,
        class_mask: np.ndarray,
        sy: float,
        sx: float,
        ty: float = 0.0,
        tx: float = 0.0,
    ) -> np.ndarray:
        # Use absolute-top anchor
        x0, x1, y0, y1, largest_mask = self._get_pixel_bounds(class_mask, sy, sx, use_center_anchor=False)

        # Trim the mask down to the calculated boundaries
        trimmed_mask = np.zeros_like(largest_mask)
        trimmed_mask[y0:y1, x0:x1] = largest_mask[y0:y1, x0:x1]

        # Extract the outermost contour
        contours, _ = cv2.findContours(
            trimmed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            raise ValueError("No polygon found after trimming. Check sizes and depth.")

        largest_contour = max(contours, key=cv2.contourArea).squeeze()
        if largest_contour.ndim == 1:
            largest_contour = largest_contour[np.newaxis, :]  

        # Convert to Napari world coordinates
        y_world = float(ty) + largest_contour[:, 1] * float(sy)
        x_world = float(tx) + largest_contour[:, 0] * float(sx)

        return np.column_stack((y_world, x_world))