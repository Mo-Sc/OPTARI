"""Exporting scans: OPTARI HDF5 with ROIs and derived images, IPASC raw data, batch report."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import patato as pat
import pytest
from patato.io.attribute_tags import HDF5Tags

from optari import OPTARI_SOURCE_TAG
from optari.batch.plan import BatchJob
from optari.batch.report import REPORT_COLUMNS, REPORT_SHEET, BatchReport
from optari.io.discovery import ScanInfo, scan_type
from optari.controllers.unmixing_controller import (
    UnmixingController,
    _unmix_frames,
)
from optari.io.export_pipeline import (
    OPTARI_FILE_FORMAT_VERSION,
    ROI_TABLE_META_SHEET,
    export_scan_to_hdf5,
    export_scan_to_ipasc,
)
from optari.patato_bridge import (
    build_napari_layers,
    display_data_from_patato_obj,
    roi_records_from_scan_rois,
)
from optari.roi.roi_records import ROIRecord
from tests.conftest import ITHERA_SCAN, needs_study, run_to_end

pytestmark = needs_study

FRAME = 24  # lowest-motion frame of Scan_2
FOV = (0.04, 0.04)


def controller_with(pa_data, records=(), derived=None, restored=True):
    """The slice of OptariController that the export pipeline reads."""
    return SimpleNamespace(
        pa_data=pa_data,
        roi_ctrl=SimpleNamespace(
            sync_records_from_shapes=lambda: True,
            roi_records=list(records),
            stored_rois_restored=restored,
        ),
        scan_ctrl=SimpleNamespace(get_fov=lambda: FOV),
        derived_patato_objects=derived or {},
        segmentation_ctrl=SimpleNamespace(
            seg_layer=None
        ),  # _write_derived_data reads this
        clinical_metadata_edits=None,  # _write_derived_data reads this
    )


def test_hdf5_export_round_trip(ithera_scan, tmp_path):
    roi = ROIRecord(
        roi_id=0,
        track_id=0,
        frame_id=FRAME,
        kind="ellipse",
        tissue_class="Muskel1",
        verts=np.array(
            [[15.0, 15.0], [15.0, 25.0], [17.0, 25.0], [17.0, 15.0]]
        ),
    )
    recon = next(iter(ithera_scan.get_scan_reconstructions().values()))
    (unmixed, _, _), _ = run_to_end(
        _unmix_frames(
            recon[FRAME : FRAME + 1],
            ithera_scan,
            [700, 730, 760, 800, 850],
            ["Hb", "HbO2"],
            1,
            "",
            False,
            False,
            4,
        )
    )
    _, export_attrs = UnmixingController._build_output_metadata(
        source_layer_name="Recon: iThera BP-40mm(res:100μm)_0",
        output_frames=[FRAME],
        axis1_labels=["Hb", "HbO2"],
        filepath=str(ITHERA_SCAN),
        timestamps=None,
        acquisition_start=None,
        pa_kind="unmixed",
        frame_mode="current",
        include_chromophores=True,
        settings={},
    )
    UnmixingController._set_export_frame_attrs(unmixed, export_attrs)

    destination = tmp_path / "Scan_2.hdf5"
    controller = controller_with(ithera_scan, [roi], {"Unmixed: iThera": unmixed})
    assert export_scan_to_hdf5(controller, destination)
    assert not export_scan_to_hdf5(controller, destination)  # never overwrites

    with h5py.File(destination) as file:
        origin = json.loads(file.attrs[HDF5Tags.FILE_ORIGIN])
    assert (
        origin["tool"] == "OPTARI"
        and origin["format_version"] == OPTARI_FILE_FORMAT_VERSION
    )
    assert scan_type(destination) == "hdf5"

    reopened = pat.PAData.from_hdf5(str(destination), mode="r")
    layers, _ = build_napari_layers(reopened)
    names = [kw["name"] for _, kw in layers]
    assert names[:2] == ["US", "Recon: iThera BP-40mm(res:100μm)_0"] and names[
        2
    ].startswith("Unmixed: ")
    unmixed_data, unmixed_kw = layers[2]
    assert unmixed_data.shape == (26, 2, 400, 400) and unmixed_kw["metadata"][
        "frames"
    ] == [FRAME]
    assert unmixed_kw["metadata"]["chromophores"] == ["Hb", "HbO2"]
    np.testing.assert_allclose(
        unmixed_data[FRAME], display_data_from_patato_obj(unmixed)[0]
    )
    assert (
        unmixed_data[FRAME - 1].any() == False
    )  # frames that were not unmixed stay empty

    (restored,) = roi_records_from_scan_rois(reopened, *FOV)
    np.testing.assert_allclose(restored.verts, roi.verts, atol=1e-6)
    assert (restored.frame_id, restored.kind, restored.tissue_class) == (
        FRAME,
        "ellipse",
        "Muskel1",
    )
    assert (restored.roi_id, restored.track_id, restored.roi_group_uid) == (
        0,
        0,
        roi.roi_group_uid,
    )
    reopened.close()


def test_ipasc_export_reloads_as_raw_scan(ithera_scan, tmp_path):
    destination = tmp_path / "Scan_2_ipasc.hdf5"
    assert export_scan_to_ipasc(controller_with(ithera_scan), destination)
    assert scan_type(destination) == "ipasc"

    reopened = pat.PAData.from_hdf5(str(destination), mode="r")
    np.testing.assert_allclose(
        reopened.get_wavelengths(), ithera_scan.get_wavelengths()
    )  # stored in metres
    # Each reader reports wall clock seconds on its own clock: iThera on the scanner's local
    # clock, IPASC on UTC. IPASC also keeps one time per frame, so the per-wavelength
    # sub-second stamps do not survive the export.
    offset = ithera_scan.get_scan_datetime().utcoffset().total_seconds()
    np.testing.assert_allclose(
        np.asarray(reopened.get_timestamps())[:, 0],
        np.asarray(ithera_scan.get_timestamps())[:, 0] - offset,
    )
    assert reopened.shape == (26, 13)
    # Raw time series only: no ultrasound and nothing reconstructed yet.
    assert build_napari_layers(reopened)[0] == []
    np.testing.assert_array_equal(
        reopened[FRAME : FRAME + 1].get_time_series().raw_data,
        ithera_scan[FRAME : FRAME + 1].get_time_series().raw_data,
    )


def test_batch_report_lifecycle(tmp_path):
    def job(number):
        return BatchJob(
            Path("/d/Study_1"),
            Path(f"/d/Study_1/Scan_{number}.hdf5"),
            ScanInfo("hdf5", f"S{number}"),
        )

    path = tmp_path / "batch_report.xlsx"
    report = BatchReport(path, plan_source={"steps": {}})

    report.start(job(1))
    report.note(job(1), analysis_frame=15, n_rows=13)
    report.succeed(job(1))
    report.start(job(2))
    report.fail(job(2), "no reconstruction", step="unmixing")
    report.cancel(job(3))  # never started: still gets a row

    rows = report.rows
    assert list(rows.columns) == REPORT_COLUMNS
    assert rows.loc[
        0, ["scan", "scan_name", "analysis_frame", "n_rows"]
    ].tolist() == ["Scan_1.hdf5", "S1", 15, 13]
    assert rows.loc[1, ["failed_step", "message"]].tolist() == [
        "unmixing",
        "no reconstruction",
    ]
    assert report.summary() == "3 scan(s): 1 cancelled, 1 failed, 1 ok"

    on_disk = pd.read_excel(
        path, sheet_name=None
    )  # rewritten after every scan
    assert set(on_disk) == {REPORT_SHEET, ROI_TABLE_META_SHEET}
    assert on_disk[REPORT_SHEET]["status"].tolist() == [
        "ok",
        "failed",
        "cancelled",
    ]

    with pytest.raises(AttributeError, match="no field 'typo'"):
        report.note(job(1), typo=1)
