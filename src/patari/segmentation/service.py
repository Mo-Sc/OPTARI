from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import nibabel as nib


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
        # self.class_names: dict[int, str] = {
        #     1: "skin",
        #     2: "fat",
        #     3: "muscle",
        # }

        self.class_names: dict[int, str] = {
            0: "background",
            1: "Haut",
            2: "Faszie1",
            3: "Muskel1",
            4: "Muskel2",
            5: "Membran",
            6: "Faszie2",
            7: "Vorlaufstrecke",
            8: "SAT",
            9: "Gel",
        }

    # def predict(self, us_2d: np.ndarray) -> SegmentationResult:
    #     us_2d = np.asarray(us_2d)
    #     if us_2d.ndim != 2:
    #         raise ValueError(f"Expected 2D US frame, got shape {us_2d.shape}")

    #     h, w = us_2d.shape
    #     seg = np.zeros((h, w), dtype=np.int32)

    #     # Simple horizontal bands by depth as a stand-in segmentation.
    #     class_ids = sorted(int(k) for k in self.class_names.keys())
    #     n = len(class_ids)
    #     if n == 0:
    #         return SegmentationResult(seg=seg, class_names={})

    #     for band_index, class_id in enumerate(class_ids):
    #         y_start = int(round(h * (band_index / n)))
    #         y_end = int(round(h * ((band_index + 1) / n)))
    #         seg[y_start:y_end, :] = int(class_id)

    #     return SegmentationResult(seg=seg, class_names=dict(self.class_names))

    def predict(self, us_2d: np.ndarray) -> SegmentationResult:
        """
        as dummy, simply load and return the .nii segmentation mask from file
        """
        us_2d = np.asarray(us_2d)
        if us_2d.ndim != 2:
            raise ValueError(f"Expected 2D US frame, got shape {us_2d.shape}")

        # load dummy segmentation from file
        nii_img = nib.load(
            "/Users/moritzschillinger/Projects/PATARI/data/samples/demo_study19-08/MSOT-2-US-MulticlassLabels_019002.nii"
        )
        seg = nii_img.get_fdata()[:, :, 0].astype(np.int32)

        # rot90 ccw
        seg = np.rot90(seg, k=1)

        return SegmentationResult(seg=seg, class_names=dict(self.class_names))
