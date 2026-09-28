"""ROI geometry, shared by the viewer, presets, the saved analysis
table and HDF5 export.

Described a shape, not a uniqe measurement

Every persisted form of an ROI uses PATATO coordinates. napari millimetres exist
only inside the viewer, where they are relative to the field of view corner and
therefore inconsistent once the FOV changes.

So we have 3 coordinate systems in OPTARI:

``world mm``
    What ``ROIRecord.verts`` always holds. The Shapes layer is never translated, so
    world millimetres are the shared physical frame every layer is registered into.
    Scan-loaded layers sit at translate 0, which makes world mm *identical* to the
    scan frame.
``PATATO metres``
    What this module stores. Scan-anchored, like PATATO. origin at the image centre,
    derived from world mm and the scan's field of view.
``layer pixels``
    Indices into a layer's array. A runtime-derived layer may sit at a nonzero
    ``translate`` (like deepmb) to register it against the others,
    so converting world mm to *that* layer's pixels means subtracting its
    translate first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from optari import OPTARI_SOURCE_TAG
from optari.roi.roi_records import ROIRecord


def patato_to_napari(
    pts_m: np.ndarray, fov_x_m: float, fov_y_m: float
) -> np.ndarray:
    """Convert PATATO ``(x_m, y_m)`` polygon vertices to napari ``(y_mm, x_mm)``.

    PATATO: origin at image centre, x→right, y→up, metres.
    napari:  origin at top-left,   y→down, mm.
    """
    x_m = pts_m[:, 0]
    y_m = pts_m[:, 1]
    return np.stack(
        [
            (fov_y_m / 2.0 - y_m) * 1000.0,  # y_mm  (y-axis flipped)
            (x_m + fov_x_m / 2.0) * 1000.0,  # x_mm  (origin shifted)
        ],
        axis=1,
    )


def napari_to_patato(
    verts_yx_mm: np.ndarray, fov_x_m: float, fov_y_m: float
) -> np.ndarray:
    """Inverse of :func:`patato_to_napari`."""
    y_mm = verts_yx_mm[:, 0]
    x_mm = verts_yx_mm[:, 1]
    return np.stack(
        [
            x_mm / 1000.0 - fov_x_m / 2.0,  # patato x (m)
            fov_y_m / 2.0 - y_mm / 1000.0,  # patato y (m)
        ],
        axis=1,
    )


@dataclass
class RoiGeometry:
    """An ROI shape in PATATO coordinates: metres, origin at the image centre.

    FOV-independent, so the same geometry restores to the same
    physical location on any reconstruction whatever its field of view or pixel
    grid.
    """

    verts_m: np.ndarray  # (N, 2) as (x_m, y_m)
    kind: str = "polygon"
    tissue_class: str = "undefined"
    source: str = OPTARI_SOURCE_TAG

    def __post_init__(self) -> None:
        """Coerce *verts_m* to an (N, 2) array and the other fields to their types. Rejects an empty geometry."""
        self.verts_m = np.asarray(self.verts_m, dtype=float).reshape(-1, 2)
        if self.verts_m.size == 0:
            raise ValueError("ROI geometry must contain vertices")
        self.kind = str(self.kind)
        self.tissue_class = str(self.tissue_class or "undefined")
        self.source = str(self.source or OPTARI_SOURCE_TAG)

    @classmethod
    def from_record(
        cls, record: ROIRecord, fov_x_m: float, fov_y_m: float
    ) -> "RoiGeometry":
        """Build from a record's world-space vertices."""
        return cls(
            verts_m=napari_to_patato(
                np.asarray(record.verts, dtype=float)[:, -2:], fov_x_m, fov_y_m
            ),
            kind=record.kind,
            tissue_class=record.tissue_class,
            source=record.source,
        )

    def verts_mm(self, fov_x_m: float, fov_y_m: float) -> np.ndarray:
        """Vertices as napari ``(y_mm, x_mm)`` for a target field of view."""
        return patato_to_napari(self.verts_m, fov_x_m, fov_y_m)

    def to_record(
        self,
        *,
        roi_id: int,
        track_id: int,
        frame_id: int,
        fov_x_m: float,
        fov_y_m: float,
        roi_group_uid: str = "",
    ) -> ROIRecord:
        """Rebuild a record. An empty *roi_group_uid* mints a new group identity."""
        return ROIRecord(
            roi_id=roi_id,
            track_id=track_id,
            frame_id=frame_id,
            roi_group_uid=roi_group_uid,
            verts=self.verts_mm(fov_x_m, fov_y_m),
            kind=self.kind,
            source=self.source,
            tissue_class=self.tissue_class,
        )

    def repositioned(
        self, source_fov: tuple[float, float], target_fov: tuple[float, float]
    ) -> "RoiGeometry":
        """Move the ROI to the same relative spot in a different FOV, keeping its size."""
        scale = np.asarray(target_fov, dtype=float) / np.asarray(
            source_fov, dtype=float
        )
        centre = self.verts_m.mean(axis=0)
        return RoiGeometry(
            verts_m=self.verts_m + (centre * scale - centre),
            kind=self.kind,
            tissue_class=self.tissue_class,
            source=self.source,
        )

    def to_dict(self) -> dict:
        """Serialize to a plain dict of JSON-safe values."""
        return {
            "verts_m": self.verts_m.round(9).tolist(),
            "kind": self.kind,
            "tissue_class": self.tissue_class,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RoiGeometry":
        """Rebuild from :meth:`to_dict`'s output, defaulting any missing key."""
        return cls(
            verts_m=data.get("verts_m", []),
            kind=data.get("kind", "polygon"),
            tissue_class=data.get("tissue_class", "undefined"),
            source=data.get("source", OPTARI_SOURCE_TAG),
        )

    def to_json(self) -> str:
        """Serialize to the JSON blob stored in the ``roi_geometry`` table column."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "RoiGeometry":
        """Inverse of :meth:`to_json`."""
        return cls.from_dict(json.loads(text))
