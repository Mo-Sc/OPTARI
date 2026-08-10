from __future__ import annotations

import math
from collections.abc import Mapping


SUPPORTED_ROI_SHAPES = frozenset({"ellipse", "rectangle", "polygon"})


def _optional_dimension(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number or null.")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative.")
    return value


def validate_segmentation_settings(
    settings: dict,
    class_names: Mapping[int, str] | None = None,
) -> dict:
    """Validate segmentation preset settings and normalize"""
    model_id = settings.get("model_id")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("Segmentation preset requires a model_id.")

    selected_class_ids = settings.get("selected_class_ids")
    if not isinstance(selected_class_ids, list) or not selected_class_ids:
        raise ValueError("Segmentation preset requires selected class IDs.")
    if any(
        isinstance(class_id, bool) or not isinstance(class_id, int)
        for class_id in selected_class_ids
    ):
        raise ValueError("Selected class IDs must be integers.")
    if len(selected_class_ids) != len(set(selected_class_ids)):
        raise ValueError("Selected class IDs must be unique.")

    roi_class_id = settings.get("roi_class_id")
    if roi_class_id is not None and (
        isinstance(roi_class_id, bool) or not isinstance(roi_class_id, int)
    ):
        raise ValueError("ROI class ID must be an integer or null.")

    roi_shape = settings.get("roi_shape", "ellipse")
    if not isinstance(roi_shape, str) or roi_shape not in SUPPORTED_ROI_SHAPES:
        raise ValueError(f"Unsupported ROI shape: {roi_shape}")

    roi_width_mm = _optional_dimension(settings.get("roi_width_mm"), "ROI width")
    roi_height_mm = _optional_dimension(settings.get("roi_height_mm"), "ROI height")
    if roi_class_id is not None and roi_shape in {"ellipse", "rectangle"} and (
        roi_width_mm is None
        or roi_height_mm is None
        or roi_width_mm <= 0
        or roi_height_mm <= 0
    ):
        raise ValueError(
            "Ellipse and rectangle presets require positive width and height."
        )

    if class_names is not None:
        available_ids = set(class_names)
        unknown_ids = set(selected_class_ids) - available_ids
        if unknown_ids:
            raise ValueError(
                f"Preset contains unknown class IDs: {sorted(unknown_ids)}"
            )
        if roi_class_id is not None:
            if roi_class_id not in available_ids:
                raise ValueError(
                    f"Preset contains unknown ROI class ID: {roi_class_id}"
                )
            if roi_class_id not in selected_class_ids:
                raise ValueError("ROI class ID must be one of the selected classes.")

    return {
        "model_id": model_id,
        "selected_class_ids": list(selected_class_ids),
        "roi_class_id": roi_class_id,
        "roi_shape": roi_shape,
        "roi_width_mm": roi_width_mm,
        "roi_height_mm": roi_height_mm,
        "roi_top_margin_mm": _optional_dimension(
            settings.get("roi_top_margin_mm"), "ROI top margin"
        ),
    }