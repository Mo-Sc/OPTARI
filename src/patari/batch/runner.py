"""Drive a :class:`BatchPlan` over a dataset, one scan at a time.

The whole run is a single generator. Work that has to touch the viewer (loading a
scan, placing an ROI, measuring, screenshots) happens inline on the main thread;
each heavy stage is yielded as a :class:`BackgroundStep` that the runner hands to a
worker thread and resumes from when it finishes. Writing it as a generator is what
makes "log this scan's failure and carry on" an ordinary ``try``/``except`` around
the per-scan body rather than a state machine.

Resuming happens on the worker's ``finished`` signal, not ``returned``. superqt emits
``returned`` first and ``finished`` second, and the task helper clears the UI gate in
its ``on_done``; resuming any earlier would let the finishing worker tear down the
progress bar and gate that the next step has already set up.
"""

from __future__ import annotations

import datetime as dt
import logging
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from napari.layers import Image
from qtpy.QtCore import QTimer

from patari.batch.plan import BatchJob, BatchPlan
from patari.batch.report import BatchReport
from patari.controllers.reconstruction_controller import ReconParams
from patari.controllers.segmentation_controller import SegmentParams
from patari.controllers.unmixing_controller import UnmixParams
from patari.io.export_pipeline import export_scan_to_hdf5, export_scan_to_ipasc
from patari.io.utils import save_viewer_screenshot
from patari.roi.roi_table import SavedRoiTable
from patari.utils.logging import run_log_file
from patari.utils.tasks import BackgroundStep, run_background_task

logger = logging.getLogger(__name__)


class BatchStepError(Exception):
    """This scan cannot be processed. Record it and move on to the next one."""


class BatchCancelled(Exception):
    """The user stopped the run. Nothing further should start."""


@dataclass(frozen=True)
class Tick:
    """Hand control back to the event loop, so Cancel stays responsive between scans."""


@contextmanager
def _only_visible(viewer, keep):
    """Show only the layers in *keep* for the duration of the block.

    A screenshot has to be of a known display state. Without this an overlay would
    show whatever the previous scan happened to leave switched on.
    """
    previous = [(layer, layer.visible) for layer in viewer.layers]
    keep = [layer for layer in keep if layer is not None]
    for layer, _ in previous:
        layer.visible = layer in keep
    try:
        yield
    finally:
        for layer, was_visible in previous:
            layer.visible = was_visible


class BatchRunner:
    """Runs a plan against the live viewer, reporting progress as it goes."""

    def __init__(
        self,
        controller,
        plan: BatchPlan,
        *,
        on_progress=None,
        on_finished=None,
    ) -> None:
        self.controller = controller
        self.viewer = controller.viewer
        self.plan = plan
        self.report = BatchReport(plan.report_path, plan_source=plan.preset)
        self.saved_table = SavedRoiTable(
            plan.table_path if plan.outputs.xlsx else None
        )
        self._on_progress = on_progress or (lambda job, status: None)
        self._on_finished = on_finished or (lambda: None)
        self._cancel_requested = False
        self._worker = None
        self._gen = None
        self._resources = ExitStack()

    # ============ driving ============
    def start(self) -> None:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = self.plan.output_dir / f"batch_{stamp}.log"
        self._resources.enter_context(run_log_file(log_path))
        logger.info(
            "batch run starting: %s scan(s), steps: %s",
            len(self.plan.jobs),
            " -> ".join(self.plan.step_names) or "none",
        )
        # load_scan resolves a path through the controller's scan map, so every scan
        # the plan covers has to be in it before the first load.
        self.controller._scans = {
            job.scan_path: job.scan_info for job in self.plan.jobs
        }
        self._gen = self._run()
        self._advance(("ok", None))

    def cancel(self) -> None:
        self._cancel_requested = True
        if self._worker is not None:
            self._worker.quit()

    def _advance(self, outcome) -> None:
        """Resume the plan generator with the last step's outcome. Main thread only."""
        if self.controller._is_shut_down:
            return
        kind, value = outcome
        try:
            if kind == "ok":
                step = self._gen.send(value)
            elif kind == "error":
                step = self._gen.throw(BatchStepError(value))
            else:
                step = self._gen.throw(BatchCancelled())
        except StopIteration:
            self._finish()
            return
        except Exception:
            logger.exception("batch run aborted")
            self._finish()
            return

        if isinstance(step, Tick):
            QTimer.singleShot(0, lambda: self._advance(("ok", None)))
            return
        self._start_background(step)

    def _start_background(self, step: BackgroundStep) -> None:
        outcome: list = []
        self._worker = run_background_task(
            self.viewer,
            step.func,
            total=step.total,
            desc=step.desc,
            on_result=lambda result: outcome.append(("ok", result)),
            on_error=lambda message: outcome.append(("error", message)),
            on_cancel=lambda: outcome.append(("cancelled", None)),
            # `finished` is the last signal a worker emits, so resuming here cannot
            # race this worker's own teardown against the next step's setup.
            on_done=lambda: self._advance(
                outcome[0] if outcome else ("error", "step produced no result")
            ),
        )
        self.controller.set_active_task(self._worker)

    def _finish(self) -> None:
        self._worker = None
        self.controller.set_active_task(None)
        logger.info("batch run finished: %s", self.report.summary())
        self._resources.close()
        self._on_finished()

    # ============ the plan ============
    def _run(self):
        for job in self.plan.jobs:
            yield Tick()  # let the event loop breathe between scans
            if self._cancel_requested:
                self.report.cancel(job)
                self._on_progress(job, "cancelled")
                return

            self.report.start(job)
            self._on_progress(job, "running")
            try:
                yield from self._run_job(job)
            except BatchStepError as exc:
                logger.warning("scan %s failed: %s", job.scan_path, exc)
                self.report.fail(job, str(exc))
                self._on_progress(job, "failed")
                continue
            except BatchCancelled:
                self.report.cancel(job)
                self._on_progress(job, "cancelled")
                return
            except Exception as exc:
                # A bug in one step must not take the rest of the dataset with it.
                logger.exception("unexpected failure on %s", job.scan_path)
                self.report.fail(job, f"{type(exc).__name__}: {exc}")
                self._on_progress(job, "failed")
                continue

            self.report.succeed(job)
            self._on_progress(job, "ok")

    def _run_job(self, job: BatchJob):
        controller = self.controller
        if not controller.scan_ctrl.load_scan(job.scan_path):
            raise BatchStepError("could not open scan")
        controller.study_path = job.study_path

        frame_idx = self._select_analysis_frame()
        self.report.note(job, analysis_frame=frame_idx)
        # Measuring across frames needs every frame reconstructed and segmented, not
        # just the one the overlay is taken on.
        run_frame = None if self.plan.measure.all_frames else frame_idx

        produced_recon = None
        if self.plan.reconstruction is not None:
            params = _guard(
                "reconstruction",
                ReconParams.from_settings,
                self.plan.reconstruction,
                controller,
                frame_id=run_frame,
            )
            result = yield _guard(
                "reconstruction", controller.reconstruction_ctrl.prepare, params
            )
            produced_recon = controller.reconstruction_ctrl.publish(result, params)

        # One run works on exactly one reconstruction: everything downstream (unmixing,
        # measurement, overlay) hangs off this layer, so a scan that already contains
        # several reconstructions still produces one unambiguous analysis.
        source_layer = self._select_source_layer(produced_recon)
        self.report.note(job, source_layer=source_layer.name)

        if self.plan.segmentation is not None:
            params = _guard(
                "segmentation",
                SegmentParams.build,
                controller,
                str(self.plan.segmentation.get("model_id", "")),
                {int(c) for c in self.plan.segmentation.get("selected_class_ids", [])},
                frame_idx=run_frame,
            )
            result = yield _guard(
                "segmentation", controller.segmentation_ctrl.prepare, params
            )
            controller.segmentation_ctrl.publish(result, params)

        if self.plan.unmixing is not None:
            params = _guard(
                "unmixing",
                UnmixParams.from_preset,
                self.plan.unmixing,
                controller,
                frame_id=run_frame,
            )
            result = yield _guard("unmixing", controller.unmixing_ctrl.prepare, params)
            controller.unmixing_ctrl.publish(result, params)

        if self.plan.roi is not None:
            self._place_roi()
            rows = self._measure(source_layer)
            self.saved_table.add_measurements(rows)
            self.report.note(job, n_rows=len(rows))

        self._write_outputs(job, frame_idx, source_layer)

    # ============ per-scan work ============
    def _pa_layers(self) -> list:
        return [
            layer
            for layer in self.viewer.layers
            if isinstance(layer, Image) and layer.metadata.get("type") == "pa"
        ]

    def _select_source_layer(self, produced_recon: str | None):
        """The one reconstruction this run analyses, and make it the active layer.

        Selecting it through the viewer rather than assigning the attribute keeps the
        layer visibility and contrast rules the GUI maintains, so an overlay taken
        later looks like the one a user would have produced by hand.
        """
        wanted = self.plan.source or produced_recon
        pa_layers = self._pa_layers()
        if wanted:
            layer = next((l for l in pa_layers if l.name.startswith(wanted)), None)
            if layer is None:
                available = ", ".join(l.name for l in pa_layers) or "none"
                raise BatchStepError(
                    f"no reconstruction layer starting with '{wanted}' (scan has: {available})"
                )
        else:
            # Nothing named and nothing produced: fall back to whatever opening the
            # scan selected, which follows the DEFAULT_PA_LAYER setting.
            layer = self.controller.active_recon_layer
            if layer is None:
                raise BatchStepError("scan contains no reconstruction to analyse")

        self.viewer.layers.selection.select_only(layer)
        self.controller._resolve_active_recon_layer()
        return layer

    def _analysis_layers(self, source_layer) -> list:
        """The source reconstruction plus everything unmixed from it."""
        return [source_layer] + [
            layer
            for layer in self._pa_layers()
            if layer.metadata.get("source_layer") == source_layer.name
        ]

    def _select_analysis_frame(self) -> int:
        """Pick and show the frame this scan is analysed on.

        ``default`` keeps whatever ``load_scan`` already chose from the config, so a
        plan that says nothing behaves exactly like opening the scan by hand.
        """
        if self.plan.frame == "default":
            return int(self.viewer.dims.current_step[0])

        frame_idx = self.controller.scan_ctrl.resolve_frame(self.plan.frame)
        n_frames = int(self.viewer.dims.nsteps[0]) if self.viewer.dims.ndim else 0
        if not (0 <= frame_idx < n_frames):
            raise BatchStepError(f"frame {frame_idx} is outside this scan ({n_frames} frames)")
        self.viewer.dims.set_point(0, frame_idx)
        return frame_idx

    def _place_roi(self) -> None:
        from patari.controllers.roi_controller import RoiController

        place = (
            RoiController._place_roi_preset_auto
            if self.plan.roi_placement == "auto"
            else RoiController._place_roi_preset_static
        )
        _guard("roi", place, self.controller, self.plan.roi)
        # The GUI relies on napari's data events to fold a new shape into the record
        # store. Do it explicitly here rather than depending on event delivery inside
        # one synchronous block.
        self.controller.roi_ctrl.sync_records_from_shapes()

    def _measure(self, source_layer):
        roi_ctrl = self.controller.roi_ctrl
        selected_ids = roi_ctrl._selected_roi_ids()
        if not selected_ids:
            raise BatchStepError("ROI was placed but could not be selected for measuring")
        # "all_pa" lets the scope pick up every PA layer in the scan; otherwise
        # measure only this run's own chain.
        layers = (
            None if self.plan.measure.all_layers else self._analysis_layers(source_layer)
        )
        rows = roi_ctrl._measure_selected_rois(
            selected_ids, scope=self.plan.measure, layers=layers
        )
        if rows.empty:
            raise BatchStepError("ROI measured no rows on this scan")
        return rows

    def _write_outputs(self, job: BatchJob, frame_idx: int, source_layer) -> None:
        # Exports mirror the input layout, so a converted dataset can be reopened
        # exactly like the original: <out>/<format>/Study_X/Scan_Y.hdf5
        if self.plan.outputs.hdf5:
            destination = self._export_path(job, "hdf5", f"{job.scan_stem}.hdf5")
            if not export_scan_to_hdf5(self.controller, destination):
                raise BatchStepError(f"HDF5 export failed (see log): {destination.name}")
            self.report.note(job, hdf5_path=str(destination))

        if self.plan.outputs.ipasc:
            # Same suffix the Scan Browser's IPASC export uses.
            destination = self._export_path(job, "ipasc", f"{job.scan_stem}_ipasc.hdf5")
            if not export_scan_to_ipasc(self.controller, destination):
                raise BatchStepError(f"IPASC export failed (see log): {destination.name}")
            self.report.note(job, ipasc_path=str(destination))

        if self.plan.outputs.overlay_png:
            self.report.note(
                job, overlay_path=str(self._write_overlay(job, frame_idx, source_layer))
            )

    def _export_path(self, job: BatchJob, kind: str, filename: str) -> Path:
        destination = self.plan.output_dir / kind / job.study_path.name / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        return destination

    def _write_overlay(self, job: BatchJob, frame_idx: int, source_layer) -> Path:
        overlay_layer = self._overlay_layer(source_layer)
        if overlay_layer is None:
            raise BatchStepError("no PA layer available for the overlay")

        channel_idx = (
            int(self.viewer.dims.current_step[1]) if self.viewer.dims.ndim > 1 else 0
        )
        destination = (
            self.plan.output_dir
            / "overlays"
            / f"{job.key}_F{frame_idx}_C{channel_idx}.png"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)

        keep = [
            self.controller.active_us_layer,
            overlay_layer,
            self.controller.shapes_layer,
        ]
        with _only_visible(self.viewer, keep):
            self.viewer.reset_view()
            save_viewer_screenshot(self.viewer, destination)
        return destination

    def _overlay_layer(self, source_layer):
        """The layer the overlay shows: the one named by the plan, else the last derived.

        Restricted to this run's own analysis chain, so the picture matches the numbers.
        """
        candidates = self._analysis_layers(source_layer)
        wanted = self.plan.outputs.overlay_layer
        if wanted:
            return next((l for l in candidates if l.name.startswith(wanted)), None)
        for prefix in reversed(self.plan.expected_layer_prefixes()):
            match = next((l for l in candidates if l.name.startswith(prefix)), None)
            if match is not None:
                return match
        return candidates[-1] if candidates else None


def _guard(step: str, func, *args, **kwargs):
    """Run *func*, turning a per-scan refusal into a failure this run can recover from."""
    try:
        return func(*args, **kwargs)
    except ValueError as exc:
        raise BatchStepError(f"{step}: {exc}") from exc

