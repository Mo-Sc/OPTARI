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

    def predict(self, us_2d: np.ndarray) -> SegmentationResult:
        """Dummy segmentation from a fixed NIfTI mask."""
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
