from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SegmentationResult:
    """Result of segmenting a single 2D US frame.

    seg:
        (H, W) integer class id map.
    class_names:
        Mapping of class id -> display name.
    """

    seg: np.ndarray
    class_names: dict[int, str]


class DummySegmenter:
    """Minimal placeholder segmenter.

    This is intentionally deterministic and dependency-free.
    Replace `predict` with your pretrained model inference later.
    """

    def __init__(self) -> None:
        self.class_names: dict[int, str] = {
            1: "skin",
            2: "fat",
            3: "muscle",
        }

    def predict(self, us_2d: np.ndarray) -> SegmentationResult:
        us_2d = np.asarray(us_2d)
        if us_2d.ndim != 2:
            raise ValueError(f"Expected 2D US frame, got shape {us_2d.shape}")

        h, w = us_2d.shape
        seg = np.zeros((h, w), dtype=np.int32)

        # Simple horizontal bands by depth as a stand-in segmentation.
        class_ids = sorted(int(k) for k in self.class_names.keys())
        n = len(class_ids)
        if n == 0:
            return SegmentationResult(seg=seg, class_names={})

        for band_index, class_id in enumerate(class_ids):
            y_start = int(round(h * (band_index / n)))
            y_end = int(round(h * ((band_index + 1) / n)))
            seg[y_start:y_end, :] = int(class_id)

        return SegmentationResult(seg=seg, class_names=dict(self.class_names))
