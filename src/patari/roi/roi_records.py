from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ROIRecord:
    """Frame-owned ROI geometry"""

    roi_id: int
    roi_group_id: int
    frame_id: int
    verts: np.ndarray
    kind: str
    source: str = "PATARI"
    position: str = "undefined"

    def __post_init__(self) -> None:
        self.roi_id = int(self.roi_id)
        self.roi_group_id = int(self.roi_group_id)
        self.frame_id = int(self.frame_id)
        self.verts = np.asarray(self.verts, dtype=float).copy()
        self.kind = str(self.kind)
        self.source = str(self.source or "PATARI")
        self.position = str(self.position or "undefined")
