from __future__ import annotations

import logging
from typing import Any

import numpy as np
from napari.layers import Labels
from napari.viewer import Viewer


logger = logging.getLogger(__name__)


def ensure_segmentation_labels_layer(
    viewer: Viewer,
    *,
    name: str = "Segmentation",
) -> Labels:
    if name in viewer.layers and isinstance(viewer.layers[name], Labels):
        return viewer.layers[name]

    # Create an initially empty labels layer; data will be set on first run.
    layer = viewer.add_labels(
        np.zeros((1, 1), dtype=np.int32),
        name=name,
        opacity=0.35,
        metadata={"type": "segmentation"},
    )
    return layer


def set_segmentation_2d(
    labels_layer: Labels,
    seg: np.ndarray,
    *,
    class_names: dict[int, str] | None = None,
    reference_layer=None,
) -> None:
    seg = np.asarray(seg)
    if seg.ndim != 2:
        raise ValueError(f"Expected 2D seg, got shape {seg.shape}")

    labels_layer.data = seg.astype(np.int32, copy=False)

    # Match spatial calibration to the reference layer (usually the US Image).
    if reference_layer is not None:
        try:
            ref_scale = getattr(reference_layer, "scale", None)
            if ref_scale is not None:
                labels_layer.scale = tuple(ref_scale[-2:])
        except Exception:
            logger.debug(
                "failed to copy reference scale to segmentation", exc_info=True
            )
        try:
            ref_translate = getattr(reference_layer, "translate", None)
            if ref_translate is not None:
                labels_layer.translate = tuple(ref_translate[-2:])
        except Exception:
            logger.debug(
                "failed to copy reference translate to segmentation",
                exc_info=True,
            )

    # Store class names for later UX (optional).
    if class_names is not None:
        md: dict[str, Any] = dict(getattr(labels_layer, "metadata", {}) or {})
        md["class_names"] = dict(class_names)
        labels_layer.metadata = md
