"""The Saved Analysis table on disk: the CSV it is collected in, and the XLSX it is exported as.

Headless, so callers choose the path, the controller with a file dialog, a batch run from its plan.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

import pandas as pd

from optari.config import settings
from optari.provenance import file_origin
from optari.roi.roi_features import SAVED_FIXED_SOURCE_COLUMNS
from optari.roi.roi_utils import saved_export_columns
from optari.utils.files import atomic_destination, filename_token

logger = logging.getLogger(__name__)

# Bump only when the meaning of saved-table columns changes (units, semantics).
# Columns being added or removed can be handled without a schema version bump.
# 2: roi_geometry always in scan coordinates, std with ddof=1, timestamps in UTC with
#    offset, derived layers dated by sweep start, lines and paths measured along the line.
ROI_TABLE_SCHEMA_VERSION = 2
ROI_TABLE_SHEET = "roi_table"
ROI_TABLE_META_SHEET = "optari_meta"
# One row of an Excel sheet is the header.
XLSX_MAX_ROWS = 1_048_575


def default_roi_table_filename() -> str:
    """``roi_data_<operator>_<analysis id>_<timestamp>.xlsx``.

    The timestamp is UTC so it matches ``creation_time`` in the provenance sheet.
    """
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        f"roi_data_{filename_token(settings.general.OPERATOR)}"
        f"_{filename_token(settings.general.ANALYSIS_ID)}_{timestamp}.xlsx"
    )


def append_roi_table_csv(rows: pd.DataFrame, path: Path) -> None:
    """Append *rows* to the CSV form of the ROI table, creating it with its header first."""
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as file:
        if new:
            meta = file_origin(
                roi_table_schema_version=ROI_TABLE_SCHEMA_VERSION
            )
            file.write(f"# {json.dumps(meta)}\n")
        rows.to_csv(file, header=new, index=False)


def write_roi_table_csv(rows: pd.DataFrame, path: Path) -> None:
    """Rewrite the CSV ROI table with *rows*, atomically (after a delete)."""
    with atomic_destination(path) as temporary:
        append_roi_table_csv(rows, temporary)


def write_roi_table_xlsx(rows: pd.DataFrame, path: Path) -> None:
    """Write the ROI table as an XLSX file with its provenance sheet.

    Raises ValueError for a table larger than one Excel sheet.
    """
    if len(rows) > XLSX_MAX_ROWS:
        raise ValueError(
            f"{len(rows)} rows do not fit in an Excel sheet "
            f"({XLSX_MAX_ROWS} at most). The CSV form holds them all."
        )

    meta = file_origin(roi_table_schema_version=ROI_TABLE_SCHEMA_VERSION)
    meta_df = pd.DataFrame(
        {"key": list(meta.keys()), "value": [str(v) for v in meta.values()]}
    )
    # Atomic, since a half-written file would replace the user's earlier table
    with (
        atomic_destination(path) as temporary,
        pd.ExcelWriter(temporary) as writer,
    ):
        rows.to_excel(writer, sheet_name=ROI_TABLE_SHEET, index=False)
        meta_df.to_excel(writer, sheet_name=ROI_TABLE_META_SHEET, index=False)


def read_roi_table(path: Path) -> pd.DataFrame:
    """Read an exported ROI table (XLSX) or a CSV backup, in the current column order.

    Raises ValueError for a file that is not an OPTARI ROI table of this schema version.
    """
    # Folder names identify the scan when restoring: "001" must not come back as 1
    text_columns = {"study_folder": str, "scan_folder": str, "scan_name": str}
    is_csv = path.suffix.lower() == ".csv"
    try:
        if is_csv:
            with path.open(encoding="utf-8") as file:
                meta = json.loads(file.readline().removeprefix("# "))
        else:
            meta_df = pd.read_excel(path, sheet_name=ROI_TABLE_META_SHEET)
            meta = dict(zip(meta_df["key"], meta_df["value"]))
    except (ValueError, KeyError) as exc:
        raise ValueError(f"'{path.name}' is not a OPTARI ROI table.") from exc

    file_version = str(meta.get("roi_table_schema_version", ""))
    if file_version != str(ROI_TABLE_SCHEMA_VERSION):
        raise ValueError(
            f"ROI table schema version {file_version or 'missing'} cannot be read by "
            f"this OPTARI version, which expects version {ROI_TABLE_SCHEMA_VERSION}."
        )

    df = (
        pd.read_csv(path, skiprows=1, dtype=text_columns)
        if is_csv
        else pd.read_excel(
            path, sheet_name=ROI_TABLE_SHEET, dtype=text_columns
        )
    )

    missing_required = [
        c for c in SAVED_FIXED_SOURCE_COLUMNS if c not in df.columns
    ]
    if missing_required:
        raise ValueError(
            f"ROI table is missing required column(s): {', '.join(missing_required)}."
        )

    # Without a group identity a row cannot be grouped or restored, and a blank one
    # would drop out of every groupby silently rather than failing.
    if df["roi_group_uid"].fillna("").astype(str).str.strip().eq("").any():
        raise ValueError("ROI table has row(s) with no roi_group_uid.")

    # Reconcile by name, not position, the export column set follows FEATURE_REGISTRY
    # and can grow between releases without a schema version bump.
    expected = saved_export_columns()
    dropped = [c for c in df.columns if c not in expected]
    added = [c for c in expected if c not in df.columns]
    if dropped:
        logger.warning(
            "ignoring unknown column(s) in %s: %s", path, ", ".join(dropped)
        )
    if added:
        logger.warning(
            "filling absent column(s) in %s: %s", path, ", ".join(added)
        )

    return df.reindex(columns=expected).reset_index(drop=True)
