"""Placing a saved ROI preset on a scan: as drawn (static) or anchored to a segmented class (auto).

Plain geometry in world (y, x) mm. A mask's pixel *scale* and *translate* are the
segmentation layer's last two axes. Errors are ValueErrors with a message safe to show
the user; raising rather than reporting keeps placement usable from an unattended batch
run, where a modal dialog would block forever.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from optari.roi.roi_presets import RoiPreset
from optari.roi.roi_shapes import class_top_at_center_column


def class_anchor_mm(class_mask: np.ndarray, scale, translate) -> np.ndarray:
    """World (y, x) mm of *class_mask*'s top edge at the image's horizontal centre.

    Raises ValueError if the class isn't present in *class_mask* at all, or not at
    the image's horizontal centre.
    """
    if not np.any(class_mask):
        raise ValueError("not present in this frame")
    # isolate the largest connected component before anchoring
    # TODO: necessary? If we always do that as mask postprocessing anyways
    top_row, center_col = class_top_at_center_column(class_mask)
    return np.asarray(translate, dtype=float) + np.asarray(
        [top_row, center_col], dtype=float
    ) * np.asarray(scale, dtype=float)


def top_center(verts: np.ndarray) -> np.ndarray:
    """(y, x) of the top edge's midpoint of *verts*' bounding box."""
    return np.asarray(
        [verts[:, 0].min(), 0.5 * (verts[:, 1].min() + verts[:, 1].max())]
    )


def anchor_verts_to_mask(
    verts: np.ndarray,
    class_mask: np.ndarray,
    scale,
    translate,
    top_margin_mm: float = 0.0,
) -> np.ndarray:
    """Shift *verts* so their top-center sits *top_margin_mm* below *class_mask*'s top-center.

    Raises ValueError like `class_anchor_mm`.
    """
    return (
        verts
        + class_anchor_mm(class_mask, scale, translate)
        + [top_margin_mm, 0.0]
        - top_center(verts)
    )


def static_preset_verts(
    preset: RoiPreset, target_fov: tuple[float, float]
) -> np.ndarray:
    """The preset's vertices on a scan of *target_fov*, keeping its physical size."""
    geometry = preset.geometry.repositioned(preset.source_fov_m, target_fov)
    verts = geometry.verts_mm(*target_fov)
    if (
        np.any(verts[:, 0] < 0)
        or np.any(verts[:, 0] > target_fov[1] * 1000)
        or np.any(verts[:, 1] < 0)
        or np.any(verts[:, 1] > target_fov[0] * 1000)
    ):
        raise ValueError("ROI preset does not fit in the target FOV.")
    return verts


def auto_preset_verts(
    preset: RoiPreset,
    target_fov: tuple[float, float],
    seg: np.ndarray,
    class_names: dict[int, str],
    scale,
    translate,
) -> tuple[np.ndarray, int]:
    """The preset's vertices anchored to its tissue class in the 2D mask *seg*, and that class's id."""
    class_name_to_id = {
        str(name): int(class_id) for class_id, name in class_names.items()
    }
    target_class_name = preset.geometry.tissue_class.strip()
    if target_class_name not in class_name_to_id:
        raise ValueError(
            f"ROI tissue class '{target_class_name}' not found in segmentation classes."
        )
    class_id = class_name_to_id[target_class_name]
    try:
        verts = anchor_verts_to_mask(
            preset.geometry.verts_mm(*target_fov),
            seg == class_id,
            scale,
            translate,
            preset.top_margin_mm,
        )
    except ValueError as exc:
        raise ValueError(f"Class '{target_class_name}': {exc}") from exc
    return verts, class_id


def per_frame_auto_resolver(
    seg_data: np.ndarray,
    class_id: int,
    top_margin_mm: float,
    scale,
    translate,
) -> Callable[[int, np.ndarray], np.ndarray | None]:
    """Per-frame geometry for auto placement across all frames.

    Re-anchors onto each frame's own mask in *seg_data* (frames, 1, H, W), and returns
    None for a frame the class isn't present on.
    """

    def resolve(frame_id: int, source_verts: np.ndarray) -> np.ndarray | None:
        if frame_id >= seg_data.shape[0]:
            return None
        try:
            return anchor_verts_to_mask(
                source_verts,
                seg_data[frame_id, 0] == class_id,
                scale,
                translate,
                top_margin_mm,
            )
        except ValueError:
            return None

    return resolve
