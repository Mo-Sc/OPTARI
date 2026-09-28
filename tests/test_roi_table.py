"""The Saved Analysis table: appending, autosave, XLSX export/import and de-duplication."""

import numpy as np
import pandas as pd
import pytest

from optari.io.export_pipeline import (
    ROI_TABLE_META_SHEET,
    ROI_TABLE_SHEET,
    export_roi_table_to_xlsx,
    import_roi_table_from_xlsx,
)
from optari.roi.roi_records import ROIRecord
from optari.roi.roi_table import SavedRoiTable
from optari.roi.roi_utils import compute_roi_stats, saved_export_columns


@pytest.fixture
def measured_rows(image_layer):
    """Two ROIs measured on both channels of one frame, i.e. what a save produces."""
    layer = image_layer(
        np.random.default_rng(1).normal(size=(1, 2, 50, 50)),
        filepath="/data/Study_1/Scan_1.hdf5",
    )
    rois = [
        ROIRecord(
            roi_id=i,
            track_id=i,
            frame_id=0,
            kind="rectangle",
            verts=np.array([[1, 1], [1, 3], [3, 3], [3, 1]]) + i,
        )
        for i in range(2)
    ]
    return pd.concat(
        [compute_roi_stats(rois, layer, 0, c) for c in range(2)],
        ignore_index=True,
    )


def test_add_measurements_stamps_and_reports_remeasured(
    measured_rows, tmp_path
):
    path = tmp_path / "autosave.xlsx"
    table = SavedRoiTable(path)

    assert table.add_measurements(measured_rows) == set()
    assert table.add_measurements(measured_rows) == set(
        measured_rows["roi_group_uid"]
    )
    assert (
        len(table) == 2 * len(measured_rows)
        and list(table.rows.columns) == saved_export_columns()
    )
    assert table.rows["roi_ts"].nunique() == 2 and path.exists()

    table.delete_at(list(range(len(table))))
    assert table.is_empty and not path.exists()


def test_xlsx_export_import_round_trip_and_dedupe(measured_rows, tmp_path):
    table = SavedRoiTable()
    table.add_measurements(measured_rows)
    path = export_roi_table_to_xlsx(table.rows, tmp_path / "rois.xlsx")
    imported, _ = import_roi_table_from_xlsx(path)

    assert list(imported.columns) == saved_export_columns()
    np.testing.assert_allclose(imported["mean"], table.rows["mean"])
    meta = dict(pd.read_excel(path, sheet_name=ROI_TABLE_META_SHEET).values)
    assert meta["tool"] == "OPTARI" and {
        "operator",
        "analysis_id",
        "creation_time",
    } <= set(meta)

    # Rows already in the table are skipped: the session's own export and a second import.
    assert table.merge_imported(imported) == (0, len(imported))
    other = SavedRoiTable()
    assert other.merge_imported(imported) == (len(imported), 0)
    assert other.merge_imported(imported) == (0, len(imported))


def test_import_rejects_foreign_or_outdated_tables(measured_rows, tmp_path):
    measured_rows.to_excel(tmp_path / "foreign.xlsx", index=False)
    with pytest.raises(ValueError, match="not a OPTARI ROI table"):
        import_roi_table_from_xlsx(tmp_path / "foreign.xlsx")

    with pd.ExcelWriter(tmp_path / "outdated.xlsx") as writer:
        measured_rows.to_excel(writer, sheet_name=ROI_TABLE_SHEET, index=False)
        pd.DataFrame(
            {"key": ["roi_table_schema_version"], "value": ["0"]}
        ).to_excel(writer, sheet_name=ROI_TABLE_META_SHEET, index=False)
    with pytest.raises(ValueError, match="schema version 0"):
        import_roi_table_from_xlsx(tmp_path / "outdated.xlsx")
