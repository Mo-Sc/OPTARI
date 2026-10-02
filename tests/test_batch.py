"""Batch mode: resolving a preset into a plan, checking it, and the per-scan run loop."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from napari.components import ViewerModel

from optari.batch.plan import (
    BatchJob,
    BatchPlan,
    OutputSpec,
    build_plan,
    plan_warnings,
    validate_plan,
)
from optari.batch.report import BatchReport
from optari.batch.runner import (
    BatchRunner,
    BatchStepError,
    Tick,
    _in_background,
)
from optari.io.discovery import ScanInfo
from optari.roi.roi_utils import MeasureScope
from optari.utils.presets import PresetStore
from optari.utils.setup import get_user_batch_presets_dir, get_user_models_dir
from tests.conftest import HDF5_SCAN, ITHERA_SCAN, STUDY_DIR, needs_study


def batch_preset(name):
    return PresetStore(get_user_batch_presets_dir()).load(name)


@needs_study
def test_shipped_presets_resolve_against_the_dataset(tmp_path):
    plan = build_plan(
        root=STUDY_DIR.parent,
        batch_preset=batch_preset("clinical_muscle_roi"),
        output_dir=tmp_path,
    )

    assert [job.key for job in plan.jobs] == [
        "Study_19_Scan_2",
        "Study_19_Scan_3",
    ]
    assert [job.scan_path for job in plan.jobs] == [ITHERA_SCAN, HDF5_SCAN]
    assert plan.jobs[1].scan_name == "DEMO_SCAN_3"
    assert plan.step_names == [
        "reconstruction",
        "segmentation",
        "unmixing",
        "roi (auto)",
    ]
    assert (
        plan.reconstruction["RECONSTRUCTION_ALGORITHM"]
        == "Reference Backprojection"
    )
    assert plan.unmixing["SPECTRA"] == ["Hb", "HbO2"]
    assert plan.segmentation["model_id"] == "c_unet_gastrocnemius-transverse"
    assert (
        plan.roi.geometry.tissue_class == "Muskel1" and plan.frame == "motion"
    )
    assert plan.measure == MeasureScope(
        all_layers=False,
        all_frames=False,
        all_channels=True,
        follow_track=False,
    )
    assert plan.outputs == OutputSpec(
        xlsx=True,
        hdf5=False,
        ipasc=False,
        overlay_png=True,
        overlay_layer=None,
    )
    assert plan.table_path == tmp_path / "batch_roi_table.xlsx"

    convert = build_plan(
        root=STUDY_DIR,
        batch_preset=batch_preset("convert_to_hdf5"),
        output_dir=tmp_path,
    )
    assert (
        convert.step_names == []
        and convert.outputs.hdf5
        and not convert.outputs.xlsx
    )

    existing = build_plan(
        root=STUDY_DIR,
        batch_preset=batch_preset("existing_recon_roi"),
        output_dir=tmp_path,
    )
    assert (
        existing.source == "Recon: iThera" and existing.reconstruction is None
    )
    assert plan_warnings(existing) == [] and plan_warnings(convert) == []
    assert plan_warnings(
        build_plan(
            root=STUDY_DIR,
            batch_preset={"steps": {"roi": "clinical_ellipse_5x2mm"}},
            output_dir=tmp_path,
        )
    )


def test_validate_plan_reports_every_problem(tmp_path):
    empty_root, out = tmp_path / "data", tmp_path / "out"
    empty_root.mkdir()
    out.mkdir()
    problems = validate_plan(
        build_plan(root=empty_root, batch_preset={"steps": {}}, output_dir=out)
    )
    assert [p[:14] for p in problems] == ["No scans found", "The plan has n"]

    preset = {
        "steps": {
            "segmentation": "muscle_poly",
            "unmixing": "haemoglobin",
            "roi": "clinical_ellipse_10x2mm_Muskel1",
        }
    }
    plan = build_plan(root=empty_root, batch_preset=preset, output_dir=out)
    plan.segmentation = {**plan.segmentation, "selected_class_ids": [3, 99]}
    plan.unmixing = {**plan.unmixing, "SPECTRA": ["Hb", "Unobtainium"]}
    plan.roi.geometry.tissue_class = "Dermis"
    (out / "batch_roi_table.xlsx").touch()
    problems = validate_plan(plan)

    expected = [
        "no class id(s) [99]",
        "targets tissue class 'Dermis'",
        "Unknown chromophore(s): Unobtainium",
        "already contains batch_roi_table.xlsx",
    ]
    if not (
        get_user_models_dir() / "c_unet_ta_20260928_gastrocnemius.onnx"
    ).is_file():
        expected.insert(0, "are not downloaded")
    assert len(problems) == len(expected) + 1
    for text in expected:
        assert any(text in p for p in problems), text

    plan.segmentation = None
    assert any("needs a segmentation step" in p for p in validate_plan(plan))

    # DeepMB names its weights in the preset; a batch run never downloads them.
    plan.reconstruction = {
        "RECONSTRUCTION_PARAMS": {"model_path": str(tmp_path / "deepmb.onnx")}
    }
    assert any("Reconstruction weights" in p for p in validate_plan(plan))


def job(number, kind="hdf5"):
    return BatchJob(
        Path("/d/Study_1"),
        Path(f"/d/Study_1/Scan_{number}.hdf5"),
        ScanInfo(kind, f"S{number}"),
    )


def make_runner(plan, controller):
    """A runner without the Qt driver, ready to have ``_run()`` stepped by hand."""
    runner = BatchRunner.__new__(BatchRunner)
    runner.controller, runner.viewer, runner.plan = (
        controller,
        controller.viewer,
        plan,
    )
    runner.report = BatchReport(None)
    runner.saved_table = SimpleNamespace(add_measurements=lambda rows: set())
    runner._on_progress = lambda job, status: None
    runner._on_finished = lambda: None
    runner._cancel_requested = False
    runner._worker = None
    return runner


def drive(generator, *, cancel_after=None, runner=None):
    """Step the run loop, answering every background step with a fake result."""
    ticks = 0
    try:
        step = next(generator)
        while True:
            if isinstance(step, Tick):
                ticks += 1
                if ticks == cancel_after:
                    runner.cancel()
            step = generator.send(None)
    except StopIteration:
        return ticks


def test_runner_isolates_failures_and_honours_cancel():
    """Load failures, refused frames and outright bugs each fail one scan, not the run."""
    plan = BatchPlan(
        jobs=[job(1), job(2), job(3), job(4)],
        output_dir=Path("/nowhere"),
        frame=30,
        outputs=OutputSpec(xlsx=False, overlay_png=False),
    )
    viewer = ViewerModel()
    recon = viewer.add_image(
        np.zeros((2, 1, 4, 4)), name="Recon: x", metadata={"type": "pa"}
    )

    class ScanCtrl:
        """Scan_1 cannot be opened, Scan_2 does not have the requested frame."""

        def load_scan(self, path, info):
            self.current = path.stem
            return self.current != "Scan_1"

        def go_to_frame(self, selector):
            if self.current == "Scan_2":
                raise ValueError(f"frame {selector} is outside this scan")
            return 0

    controller = SimpleNamespace(
        viewer=viewer,
        active_recon_layer=recon,
        resolve_active_recon_layer=lambda: None,
        scan_ctrl=ScanCtrl(),
    )
    runner = make_runner(plan, controller)
    runner._write_outputs = lambda job, frame_idx, layer: None
    drive(runner._run())
    statuses = runner.report.rows.set_index("scan")["status"].to_dict()
    assert statuses == {
        "Scan_1.hdf5": "failed",
        "Scan_2.hdf5": "failed",
        "Scan_3.hdf5": "ok",
        "Scan_4.hdf5": "ok",
    }
    failures = runner.report.rows.loc[:1, ["failed_step", "message"]]
    assert failures.values.tolist() == [
        ["load", "could not open scan"],
        ["frame", "frame 30 is outside this scan"],
    ]

    runner = make_runner(plan, controller)
    runner._write_outputs = lambda job, frame_idx, layer: 1 / 0
    drive(runner._run())
    assert (
        runner.report.rows.loc[2:, ["failed_step", "message"]].values.tolist()
        == [["unexpected", "ZeroDivisionError: division by zero"]] * 2
    )

    runner = make_runner(plan, controller)
    runner._write_outputs = lambda job, frame_idx, layer: None
    drive(runner._run(), cancel_after=3, runner=runner)
    assert runner.report.rows["status"].tolist() == [
        "failed",
        "failed",
        "cancelled",
    ]  # Scan_4 never starts


def test_source_and_overlay_layer_selection(tmp_path):
    viewer = ViewerModel()
    vendor = viewer.add_image(
        np.zeros((1, 1, 2, 2)),
        name="Recon: iThera BP-40mm_0",
        metadata={"type": "pa"},
    )
    ours = viewer.add_image(
        np.zeros((1, 1, 2, 2)),
        name="Recon: Reference Backprojection_F15",
        metadata={"type": "pa"},
    )
    unmixed = viewer.add_image(
        np.zeros((1, 2, 2, 2)),
        name="Unmixed: Reference Backprojection_F15",
        metadata={"type": "pa", "source_layer": ours.name},
    )
    so2 = viewer.add_image(
        np.zeros((1, 1, 2, 2)),
        name="sO2: Reference Backprojection_F15",
        metadata={"type": "pa", "source_layer": ours.name},
    )
    viewer.add_image(
        np.zeros((1, 1, 2, 2)), name="US", metadata={"type": "us"}
    )
    controller = SimpleNamespace(
        viewer=viewer,
        active_recon_layer=vendor,
        resolve_active_recon_layer=lambda: None,
    )

    plan = BatchPlan(jobs=[], output_dir=tmp_path)
    runner = make_runner(plan, controller)
    assert (
        runner._select_source_layer(ours.name) is ours
    )  # the reconstruction this run made
    assert (
        runner._select_source_layer(None) is vendor
    )  # nothing made, nothing named: the default PA layer
    assert list(viewer.layers.selection) == [vendor]
    plan.source = "Recon: iThera"
    assert (
        runner._select_source_layer(ours.name) is vendor
    )  # an explicit source wins
    plan.source = "Recon: DeepMB"
    with pytest.raises(
        BatchStepError,
        match="no reconstruction layer starting with 'Recon: DeepMB' \\(scan has: Recon: iThera",
    ):
        runner._select_source_layer(None)

    assert runner._analysis_layers(ours) == [ours, unmixed, so2]
    assert runner._analysis_layers(vendor) == [vendor]
    assert (
        runner._overlay_layer(ours) is so2
    )  # the most derived layer of this run's chain
    plan.outputs = OutputSpec(overlay_layer="Unmixed")
    assert runner._overlay_layer(ours) is unmixed
    plan.outputs = OutputSpec(overlay_layer="THb")
    with pytest.raises(BatchStepError, match="no layer starting with 'THb'"):
        runner._overlay_layer(ours)

    assert (
        runner._export_path(job(3), "hdf5", "Scan_3.hdf5")
        == tmp_path / "hdf5" / "Study_1" / "Scan_3.hdf5"
    )
    assert (tmp_path / "hdf5" / "Study_1").is_dir()
