"""The Saved Analysis table, the ROI measurements saved in a session.

- **Saving never overwrites.** Re-measuring an ROI appends another set of rows under
  the same ``roi_group_uid``, told apart by ``roi_ts``. Earlier measurements stay, so
  the table records everything that was measured.
- **Every change writes to disk.** New rows are appended to a CSV, a delete rewrites it.
- **Re-importing the same file adds nothing.** Identical rows are skipped, so analysis
  sheets can be combined.

The Qt side lives in ``RoiController``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from optari.roi.roi_table_io import append_roi_table_csv, write_roi_table_csv
from optari.roi.roi_utils import saved_export_columns, saved_table_columns

logger = logging.getLogger(__name__)

# unique measurement key within the table
MEASUREMENT_KEY = ["roi_group_uid", "roi_ts", "src_layer", "frame", "channel"]


class SavedRoiTable:
    """Measured ROI rows, mirrored to *autosave_path* after every change.

    ``autosave_path`` may be ``None`` to disable the save (e.g. for test cases)
    """

    def __init__(self, autosave_path: Path | None = None):
        """Create an empty table that autosaves to *autosave_path*, if given."""
        self._rows = pd.DataFrame(columns=saved_export_columns())
        self._autosave_path = autosave_path

    # ============ reading ============
    def __len__(self) -> int:
        """Number of saved rows."""
        return len(self._rows)

    @property
    def is_empty(self) -> bool:
        """True if the table has no rows."""
        return self._rows.empty

    @property
    def rows(self) -> pd.DataFrame:
        """Every stored column, the full feature set regardless of visibility."""
        return self._rows

    def visible_rows(self) -> pd.DataFrame:
        """Only the columns the saved table displays, for the widget."""
        if self._rows.empty:
            return pd.DataFrame(columns=saved_table_columns())
        return self._rows.loc[:, saved_table_columns()]

    def rows_at(self, positions: list[int]) -> pd.DataFrame:
        """Rows by *view* position. The view is unsorted, so position maps 1:1."""
        return self._rows.iloc[positions]

    def _next_measurement_stamp(self) -> str:
        """A ``roi_ts`` for the next save, later than every stamp already in the table.

        ``roi_ts`` is part of the measurement key, so two saves must never share one.
        The wall clock alone can repeat or step back (clock sync), which would merge two
        measurements into one.
        """

        # UTC with offset, like every timestamp OPTARI writes. One offset for all
        # stamps also keeps the string comparison below chronological.
        now = pd.Timestamp.now(tz="UTC")
        if not self._rows.empty:
            latest = self._rows["roi_ts"].iloc[-1]
            if now.isoformat(timespec="microseconds") <= str(latest):
                now = pd.Timestamp(latest) + pd.Timedelta(microseconds=1)
        return now.isoformat(timespec="microseconds")

    def add_measurements(self, rows: pd.DataFrame) -> set[str]:
        """Stamp *rows* with the measurement time and append them.
        Returns the ``roi_group_uid``s that already had earlier measurements.
        """
        rows = rows.copy()
        rows["roi_ts"] = self._next_measurement_stamp()
        rows = rows.loc[:, saved_export_columns()]

        remeasured = set(rows["roi_group_uid"]) & set(
            self._rows.get("roi_group_uid", [])
        )
        self._rows = self._appended(rows)
        self._save(rows)
        return remeasured

    def delete_at(self, positions: list[int]) -> int:
        """Drop rows by view position. Returns how many went."""
        if not positions:
            return 0
        # Map positions to index labels first, so the drop stays correct even if the
        # view is ever sorted or filtered.
        labels = self._rows.index[positions]
        self._rows = self._rows.drop(labels).reset_index(drop=True)
        self._save()
        return len(positions)

    def merge_imported(self, rows: pd.DataFrame) -> tuple[int, int]:
        """Append an imported table, skipping rows already present.

        Returns ``(added, skipped)``. Appending rather than replacing lets analyses
        from several sessions or machines combine in one table. ``roi_group_uid`` keeps
        every row attributable to the ROI it was measured from.
        """
        n_before = len(self._rows)
        combined = self._appended(rows)
        # A measurement is identified by what was measured where and when.
        duplicates = combined[MEASUREMENT_KEY].astype(str).duplicated()
        self._rows = combined[~duplicates].reset_index(drop=True)
        self._save(self._rows.iloc[n_before:])

        skipped = int(duplicates.sum())
        return len(rows) - skipped, skipped

    def _appended(self, rows: pd.DataFrame) -> pd.DataFrame:
        # Concatenating onto the empty initial frame, whose columns are all object
        # dtype, would make every numeric column object too.
        if self._rows.empty:
            return rows.reset_index(drop=True)
        return pd.concat([self._rows, rows], ignore_index=True)

    def _save(self, appended: pd.DataFrame | None = None) -> None:
        """Mirror the table to its CSV: append *appended*, or rewrite it after a delete.

        An emptied table leaves the file as it was: the session's only backup must
        not go with a select-all and Delete. The next save then rewrites it, since
        appending would bring the deleted rows back on import.
        """
        if self._autosave_path is None or self._rows.empty:
            return
        path = self._autosave_path
        try:
            if appended is None or len(appended) == len(self._rows):
                write_roi_table_csv(self._rows, path)
            else:
                append_roi_table_csv(appended, path)
        except OSError:
            # A failing backup must never discard the ROI data just saved.
            logger.exception("could not autosave the ROI table to %s", path)
