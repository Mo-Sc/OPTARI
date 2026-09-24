"""The Saved Analysis table consisting of saved ROI measurements.

- **Saving never overwrites.** Re-measuring an ROI appends a second set of rows under
  the same ``roi_group_uid``, separated by ``roi_ts``. TODO: should this be kept or cause error/delete prompt?
- **Every change writes to disk.** Each change to the saved table autosaves
- **Re-importing the same file adds nothing.** Identical rows are skipped, so analysis sheets can be combined

All the Qt stuff is in the controller
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

from patari.io.export_pipeline import export_roi_table_to_xlsx
from patari.roi.roi_utils import saved_export_columns, saved_table_columns

logger = logging.getLogger(__name__)

# unique measurement key within the table
MEASUREMENT_KEY = ["roi_group_uid", "roi_ts", "src_layer", "frame", "channel"]


class SavedRoiTable:
    """Measured ROI rows, mirrored to *autosave_path* after every change.

    ``autosave_path`` may be ``None`` to disable the save (e.g. for test cases)
    """

    def __init__(self, autosave_path: Path | None = None):
        self._rows = pd.DataFrame(columns=saved_export_columns())
        self._autosave_path = autosave_path

    # ============ reading ============
    def __len__(self) -> int:
        return len(self._rows)

    @property
    def is_empty(self) -> bool:
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
        """A roi timestamp. Must not collide.

        To avoid collisions, the stamp is guaranteed to be later than the most recent one in the table.
        TODO: really necessary? Or is wall clock time enough (microsecond precision)?
        """

        now = pd.Timestamp.now()
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
        self._rows = (
            rows
            if self._rows.empty
            else pd.concat([self._rows, rows], ignore_index=True)
        )
        self._autosave()
        return remeasured

    def delete_at(self, positions: list[int]) -> int:
        """Drop rows by view position; returns how many went."""
        if not positions:
            return 0
        # Map positions to index labels first, so the drop stays correct even if the
        # view is ever sorted or filtered.
        labels = self._rows.index[positions]
        self._rows = self._rows.drop(labels).reset_index(drop=True)
        self._autosave()
        return len(positions)

    def merge_imported(self, rows: pd.DataFrame) -> tuple[int, int]:
        """Append an imported table, skipping rows already present.

        Returns ``(added, skipped)``. Appending rather than replacing lets analyses
        from several sessions or machines combine in one table. ``roi_group_uid`` keeps
        every row attributable to the ROI it was measured from.
        """
        combined = pd.concat([self._rows, rows], ignore_index=True)
        # A measurement is identified by what was measured where and when.
        duplicates = combined[MEASUREMENT_KEY].astype(str).duplicated()
        self._rows = combined[~duplicates].reset_index(drop=True)
        self._autosave()

        skipped = int(duplicates.sum())
        return len(rows) - skipped, skipped


    def _autosave(self) -> None:
        """
        Write the table to disk, overwrite on every change. If the table is empty, delete the file
        """
        if self._autosave_path is None:
            return
        path = self._autosave_path
        # Keep the .xlsx suffix so ExcelWriter can still infer its engine.
        temporary_path = path.with_name(f".{path.stem}.tmp{path.suffix}")
        try:
            if self._rows.empty:
                path.unlink(missing_ok=True)
                return
            export_roi_table_to_xlsx(self._rows, temporary_path)
            os.replace(temporary_path, path)
        except OSError:
            # A failing backup must never discard the ROI data just saved.
            temporary_path.unlink(missing_ok=True)
            logger.exception("could not autosave the ROI table to %s", path)
