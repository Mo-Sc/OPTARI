from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np

from optari import OPTARI_SOURCE_TAG


def new_roi_group_uid() -> str:
    """Create a stable identity for one ROI group.

    ``track_id`` is just a session-specific counter. ``roi_group_uid`` persists through
    export, import and a move to another machine, so rows measured from the same
    ROI stay groupable wherever they end up.
    Created with a timestamp and 48 random bits to avoid collisions when multiple ROIs are created at the same time.
    """
    return f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:12]}"


@dataclass
class ROIRecord:
    """One ROI shape on one frame.

    Has 3 identifiers, for 3 scopes:

    ``roi_id``
        This shape on this frame. A session-local counter, shown on the shape in
        the viewer and used for display ordering.
    ``track_id``
        Which tracked group the shape belongs to, i.e. the same ROI followed across
        frames. Session-local, used for analysis plots across frames, and for coloring shapes in the viewer.
    ``roi_group_uid``
        The group's unique id. Persists through export, import and other
        machines. Shared by all shapes in the same ROI group, so they can be grouped together even if the session-local ids change.
    """

    roi_id: int
    track_id: int
    frame_id: int
    verts: np.ndarray
    kind: str
    source: str = OPTARI_SOURCE_TAG
    tissue_class: str = "undefined"
    roi_group_uid: str = field(default_factory=new_roi_group_uid)

    def __post_init__(self) -> None:
        self.roi_id = int(self.roi_id)
        self.track_id = int(self.track_id)
        self.roi_group_uid = str(self.roi_group_uid or "") or new_roi_group_uid()
        self.frame_id = int(self.frame_id)
        self.verts = np.asarray(self.verts, dtype=float).copy()
        self.kind = str(self.kind)
        self.source = str(self.source or OPTARI_SOURCE_TAG)
        self.tissue_class = str(self.tissue_class or "undefined")
