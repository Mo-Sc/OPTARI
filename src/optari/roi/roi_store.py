"""``RoiStore``: every ROI record of the loaded scan, and which of them the Shapes layer
shows.

Qt- and napari-free. ``RoiController`` reads the Shapes layer and hands its data in, so
the sync between the layer and the records can be tested on plain arrays.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from optari import OPTARI_SOURCE_TAG
from optari.roi.roi_records import RoiRecord


def layer_holds(record: RoiRecord, verts: np.ndarray, kind: str) -> bool:
    """Whether the Shapes layer still shows *record* unedited"""
    return record.kind == kind and np.array_equal(
        record.verts.astype(verts.dtype), verts
    )


class RoiStore:
    """Frame-owned ROI records, keyed by ``roi_id``, plus the projection of one frame.

    ``projection_ids`` are the ids of the records the Shapes layer shows, in its shape
    order: shape *i* is record ``projection_ids[i]``.
    """

    def __init__(self) -> None:
        self.records: dict[int, RoiRecord] = {}
        self.projection_ids: list[int] = []
        self._next_roi_id = 0
        self._next_track_id = 0

    def new_roi_id(self) -> int:
        self._next_roi_id += 1
        return self._next_roi_id - 1

    def new_track_id(self) -> int:
        self._next_track_id += 1
        return self._next_track_id - 1

    def restore(self, records: list[RoiRecord]) -> None:
        """Replace every record, resuming the id counters above their highest values."""
        self.records = {record.roi_id: record for record in records}
        self.projection_ids = []
        self._next_roi_id = max((r.roi_id for r in records), default=-1) + 1
        self._next_track_id = max((r.track_id for r in records), default=-1) + 1

    def clear(self) -> None:
        self.records.clear()
        self.projection_ids = []

    def projected(self) -> list[RoiRecord]:
        """The records the Shapes layer shows, in shape order."""
        return [self.records[roi_id] for roi_id in self.projection_ids]

    def project(self, frame_id: int) -> list[RoiRecord]:
        """Make *frame_id*'s records the projection, by ``roi_id``, and return them."""
        visible = sorted(
            (r for r in self.records.values() if r.frame_id == frame_id),
            key=lambda r: r.roi_id,
        )
        self.projection_ids = [r.roi_id for r in visible]
        return visible

    def _match_ids_after_removal(self, data, kinds: list[str]) -> list[int | None]:
        """Match surviving shapes to their prior ids.

        Removal preserves relative order.
        """
        old_records = self.projected()
        matched: list[int | None] = []
        j = 0
        for verts, kind in zip(data, kinds):
            while j < len(old_records) and not layer_holds(old_records[j], verts, kind):
                j += 1
            matched.append(old_records[j].roi_id if j < len(old_records) else None)
            j += 1
        return matched

    def sync(self, data: list, kinds: list[str], frame_id: int) -> bool:
        """Fold the Shapes layer's *data* and *kinds* into the records of *frame_id*.

        Same/grown shape count: ids are kept positionally (napari always
        appends new shapes at the end. in-place edits keep their position).
        Smaller shape count: removal preserves the relative order of remaining shapes,
        so ids are recovered by matching remaining geometry to the old records.

        Returns whether anything actually changed, so callers can skip the
        refresh when the layer already agrees with the records.
        """
        old_ids = self.projection_ids
        if len(data) < len(old_ids):
            new_ids = self._match_ids_after_removal(data, kinds)
        else:
            new_ids = old_ids + [None] * (len(data) - len(old_ids))

        changed = len(data) != len(old_ids)
        for i, (verts, kind) in enumerate(zip(data, kinds)):
            if new_ids[i] is None:
                # A copy: napari owns the layer's float32 arrays
                record = RoiRecord(
                    roi_id=self.new_roi_id(),
                    track_id=self.new_track_id(),
                    frame_id=frame_id,
                    verts=np.array(verts, dtype=float),
                    kind=kind,
                )
                new_ids[i] = record.roi_id
                self.records[record.roi_id] = record
                changed = True
                continue
            record = self.records[new_ids[i]]
            if layer_holds(record, verts, kind):
                continue
            record.verts = np.array(verts, dtype=float)
            record.kind = kind
            # An edited annotation is OPTARI's, but also the stored original stays as it
            # was.
            record.source = OPTARI_SOURCE_TAG
            changed = True

        for stale_id in set(old_ids) - set(new_ids):
            del self.records[stale_id]
            changed = True
        self.projection_ids = new_ids
        return changed

    def expand_last_to_all_frames(
        self,
        n_frames: int,
        verts_for_frame: Callable[[int, np.ndarray], np.ndarray | None] | None = None,
    ) -> None:
        """Duplicate the last projected ROI onto every other frame, as one group.

        `verts_for_frame(frame_id, source_verts)` lets a caller resolve each
        frame's own geometry instead of reusing `source_verts` unchanged e.g.
        auto-placement re-anchoring to that frame's own segmentation mask.
        Returning None skips that frame entirely
        """
        if not self.projection_ids:
            return
        source = self.records[self.projection_ids[-1]]
        resolve = verts_for_frame or (lambda frame_id, verts: verts)
        for frame_id in range(n_frames):
            if frame_id == source.frame_id:
                continue
            verts = resolve(frame_id, source.verts)
            if verts is None:
                continue
            record = RoiRecord(
                roi_id=self.new_roi_id(),
                track_id=source.track_id,
                frame_id=frame_id,
                verts=np.array(verts, dtype=float),
                kind=source.kind,
                source=source.source,
                tissue_class=source.tissue_class,
                roi_group_uid=source.roi_group_uid,
            )
            self.records[record.roi_id] = record
