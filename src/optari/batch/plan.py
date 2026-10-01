"""Resolve a batch preset plus a dataset folder into a concrete, checked analysis plan.

A batch preset names the per-step presets rather than copying their contents, so the
presets the user tuned in the docks stay the single source of truth and the plan itself
stays small enough to read, share and cite.

Everything here is headless: no Qt, no napari, no viewer. Building a plan and telling
the user what is wrong with it must work before anything is loaded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from optari.controllers.scan_controller import ScanController, ScanInfo
from optari.roi.roi_presets import RoiPreset, RoiPresetStore
from optari.roi.roi_utils import MeasureScope
from optari.segmentation.segmenter import load_model_registry
from optari.utils.presets import PresetStore
from optari.utils.setup import (
    get_user_models_dir,
    get_user_reconstruction_presets_dir,
    get_user_roi_presets_dir,
    get_user_segmentation_presets_dir,
    get_user_unmixing_presets_dir,
)

logger = logging.getLogger(__name__)

BATCH_TABLE_NAME = "batch_roi_table.xlsx"
BATCH_REPORT_NAME = "batch_report.xlsx"
MEASURE_LAYER_MODES = ("analysis", "all_pa")


@dataclass(frozen=True)
class BatchJob:
    """One scan to process, and where its outputs belong."""

    study_path: Path
    scan_path: Path
    scan_info: ScanInfo

    @property
    def scan_stem(self) -> str:
        """``Scan_3``, whether the scan is an HDF5 file or an iThera folder."""
        return ScanController.scan_key(self.scan_path)

    @property
    def key(self) -> str:
        """Identifier for this scan's outputs, unique across the dataset."""
        return f"{self.study_path.name}_{self.scan_stem}"

    @property
    def scan_name(self) -> str:
        """The scan's internal name from its acquisition metadata, or empty if it has none."""
        return self.scan_info.internal_name or ""


@dataclass(frozen=True)
class OutputSpec:
    """Which outputs a batch run writes per scan: ROI table, HDF5/IPASC export, and overlay PNG."""

    xlsx: bool = True
    hdf5: bool = False
    ipasc: bool = False
    overlay_png: bool = True
    # Layer-name prefix for the overlay. None means the last layer the run produced.
    overlay_layer: str | None = None


@dataclass
class BatchPlan:
    """A dataset, a set of resolved step settings, and where the results go."""

    jobs: list[BatchJob]
    output_dir: Path
    # The batch preset this plan came from, recorded verbatim in the run's report.
    preset: dict = field(default_factory=dict)
    reconstruction: dict | None = None
    unmixing: dict | None = None
    segmentation: dict | None = None
    roi: RoiPreset | None = None
    # Layer-name prefix picking the reconstruction everything downstream runs on.
    # None means the reconstruction step's own output, or the scan's default PA layer.
    source: str | None = None
    frame: int | str = "motion"
    measure: MeasureScope = field(default_factory=MeasureScope)
    outputs: OutputSpec = field(default_factory=OutputSpec)

    @property
    def table_path(self) -> Path:
        """Where the run's ROI measurements are written (batch_roi_table.xlsx)."""
        return self.output_dir / BATCH_TABLE_NAME

    @property
    def report_path(self) -> Path:
        """Where the run's per-scan status report is written (batch_report.xlsx)."""
        return self.output_dir / BATCH_REPORT_NAME

    @property
    def roi_placement(self) -> str:
        """How the ROI preset asks to be placed. Owned by the preset, not the plan."""
        return self.roi.placement if self.roi is not None else "static"

    @property
    def step_names(self) -> list[str]:
        """The analysis steps this plan will run, in execution order."""
        names = []
        if self.reconstruction is not None:
            names.append("reconstruction")
        if self.segmentation is not None:
            names.append("segmentation")
        if self.unmixing is not None:
            names.append("unmixing")
        if self.roi is not None:
            names.append(f"roi ({self.roi_placement})")
        return names


def _step_preset_name(steps: dict, label: str) -> str | None:
    """The preset a step names, or None if the step is not in the plan.

    A step is just a preset name: everything that step does is the preset's business,
    so there is exactly one place to tune it and one thing to cite.
    """
    if label not in steps:
        return None
    name = steps[label]
    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            f"The {label} step must be a preset name, got {name!r}. "
            "Step settings belong in the step's own preset."
        )
    return name.strip()


def _load_named(store: PresetStore, name: str, label: str) -> dict:
    try:
        return store.load(name)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise ValueError(
            f"Could not load {label} preset '{name}': {exc}"
        ) from exc


def _measure_scope(spec: dict) -> MeasureScope:
    mode = str(spec.get("layers", "analysis"))
    if mode not in MEASURE_LAYER_MODES:
        raise ValueError(
            f"Invalid measure.layers '{mode}'. Use one of {MEASURE_LAYER_MODES}."
        )
    all_frames = bool(spec.get("all_frames", False))
    return MeasureScope(
        # "analysis" narrows to this run's own chain, which the runner passes explicitly.
        all_layers=mode == "all_pa",
        all_frames=all_frames,
        all_channels=bool(spec.get("all_channels", True)),
        # A batch ROI is placed on every frame it measures, so each frame's own
        # outline is the only sensible one to use there.
        follow_track=all_frames,
    )


def _frame_selector(value) -> int | str:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if value in (None, "motion"):
        return "motion"
    raise ValueError(
        f"Invalid frame selector {value!r}. Use 'motion' or a frame number."
    )


def build_plan(
    *, root: Path, batch_preset: dict, output_dir: Path
) -> BatchPlan:
    """Resolve *batch_preset* against the dataset at *root*.

    Raises ValueError, message safe to show the user, when the preset cannot be
    resolved at all. Problems that need the assembled plan to spot are reported by
    :func:`validate_plan` instead, so the dialog can list them together.
    """
    root = Path(root)
    steps = batch_preset.get("steps") or {}
    if not isinstance(steps, dict):
        raise ValueError("Batch preset 'steps' must be an object.")

    jobs = [
        BatchJob(study_path=study, scan_path=scan, scan_info=info)
        for study, scans in ScanController.discover_studies(root).items()
        for scan, info in scans.items()
    ]

    reconstruction = unmixing = segmentation = None
    name = _step_preset_name(steps, "reconstruction")
    if name is not None:
        reconstruction = _load_named(
            PresetStore(get_user_reconstruction_presets_dir()),
            name,
            "reconstruction",
        )
    name = _step_preset_name(steps, "unmixing")
    if name is not None:
        unmixing = _load_named(
            PresetStore(get_user_unmixing_presets_dir()), name, "unmixing"
        )
    name = _step_preset_name(steps, "segmentation")
    if name is not None:
        segmentation = _load_named(
            PresetStore(get_user_segmentation_presets_dir()),
            name,
            "segmentation",
        )

    roi = None
    name = _step_preset_name(steps, "roi")
    if name is not None:
        try:
            roi = RoiPresetStore(get_user_roi_presets_dir()).get(name)
        except (FileNotFoundError, TypeError, ValueError, OSError) as exc:
            raise ValueError(
                f"Could not load ROI preset '{name}': {exc}"
            ) from exc

    outputs_spec = batch_preset.get("outputs") or {}
    return BatchPlan(
        jobs=jobs,
        output_dir=Path(output_dir),
        preset=batch_preset,
        reconstruction=reconstruction,
        unmixing=unmixing,
        segmentation=segmentation,
        roi=roi,
        source=(batch_preset.get("source") or None),
        frame=_frame_selector(batch_preset.get("frame")),
        measure=_measure_scope(batch_preset.get("measure") or {}),
        outputs=OutputSpec(
            xlsx=bool(outputs_spec.get("xlsx", True)),
            hdf5=bool(outputs_spec.get("hdf5", False)),
            ipasc=bool(outputs_spec.get("ipasc", False)),
            overlay_png=bool(outputs_spec.get("overlay_png", True)),
            overlay_layer=outputs_spec.get("overlay_layer") or None,
        ),
    )


def validate_plan(plan: BatchPlan) -> list[str]:
    """Everything that would make this run fail or be pointless, reported together.

    Only cross-checks that can be made before loading a scan live here. Per-scan
    failures (wavelengths not acquired, ROI outside the FOV, class absent from a
    frame) are the run's own business and are recorded in its report.
    """
    problems: list[str] = []

    if not plan.jobs:
        problems.append(
            "No scans found. Pick a folder holding Study_*/Scan_* data."
        )
    if not plan.step_names and not (plan.outputs.hdf5 or plan.outputs.ipasc):
        problems.append(
            "The plan has no analysis steps and no file export, so it would do nothing."
        )

    problems += _validate_segmentation(plan)
    problems += _validate_unmixing(plan)
    problems += _validate_output_dir(plan)
    return problems


def plan_warnings(plan: BatchPlan) -> list[str]:
    """Things worth saying out loud that are not reasons to refuse the run."""
    if plan.source or plan.reconstruction is not None:
        return []
    if plan.unmixing is None and plan.roi is None:
        return []
    return [
        "No reconstruction step and no 'source', so the scan's default PA layer will "
        "be analysed. Set 'source' to a layer-name prefix to choose deliberately."
    ]


def _validate_segmentation(plan: BatchPlan) -> list[str]:
    needs_classes = plan.roi is not None and plan.roi_placement == "auto"
    if plan.segmentation is None:
        if needs_classes:
            return [
                "Auto ROI placement needs a segmentation step, but the plan has none."
            ]
        return []

    try:
        registry = load_model_registry()
    except (OSError, ValueError, KeyError) as exc:
        return [f"Could not read the segmentation model registry: {exc}"]

    model_id = str(plan.segmentation.get("model_id", ""))
    if model_id not in registry:
        return [f"Unknown segmentation model '{model_id}'."]

    config = registry[model_id]
    problems: list[str] = []
    if not (get_user_models_dir() / config.filename).is_file():
        problems.append(
            f"Segmentation weights '{config.filename}' are not downloaded. Run "
            "segmentation once from the Segmentation dock to fetch them, then retry."
        )

    known_ids = set(config.class_names)
    unknown = sorted(
        int(c)
        for c in plan.segmentation.get("selected_class_ids", [])
        if int(c) not in known_ids
    )
    if unknown:
        problems.append(f"Model '{model_id}' has no class id(s) {unknown}.")

    if needs_classes:
        tissue_class = plan.roi.geometry.tissue_class.strip()
        if tissue_class not in set(config.class_names.values()):
            problems.append(
                f"ROI preset '{plan.roi.name}' targets tissue class '{tissue_class}', "
                f"which model '{model_id}' does not produce."
            )
    return problems


def _validate_unmixing(plan: BatchPlan) -> list[str]:
    if plan.unmixing is None:
        return []
    from patato.unmixing.spectra import SPECTRA_NAMES

    chromophores = list(plan.unmixing.get("SPECTRA", []))
    if not chromophores:
        return ["The unmixing preset selects no chromophores."]
    unknown = [c for c in chromophores if c not in SPECTRA_NAMES]
    if unknown:
        return [f"Unknown chromophore(s): {', '.join(unknown)}."]
    return []


def _validate_output_dir(plan: BatchPlan) -> list[str]:
    output_dir = plan.output_dir
    if not output_dir.is_dir():
        return [f"Output folder does not exist: {output_dir}"]
    # Refusing beats overwriting: a previous run's table is somebody's analysis.
    existing = [
        path.name
        for path in (plan.table_path, plan.report_path)
        if path.exists()
    ]
    if existing:
        return [
            f"Output folder already contains {', '.join(existing)}. "
            "Pick an empty folder so an earlier run is not overwritten."
        ]
    probe = output_dir / ".optari-batch-write-test"
    try:
        probe.touch()
        probe.unlink()
    except OSError:
        return [f"Output folder is not writable: {output_dir}"]
    return []


def describe_plan(plan: BatchPlan) -> str:
    """The resolved settings, as shown in the batch window before the run."""
    lines = [
        f"Scans:      {len(plan.jobs)} in {len({job.study_path for job in plan.jobs})} study folder(s)",
        f"Steps:      {' -> '.join(plan.step_names) or 'none (conversion only)'}",
        f"Frame:      {plan.frame}",
    ]
    if plan.reconstruction is not None:
        lines.append(
            "Recon:      "
            f"{plan.reconstruction.get('RECONSTRUCTION_ALGORITHM', 'unknown')} @ "
            f"{plan.reconstruction.get('RECONSTRUCTION_SPEED_OF_SOUND', '?')} m/s"
        )
    if plan.unmixing is not None:
        lines.append(
            f"Unmixing:   {', '.join(plan.unmixing.get('SPECTRA', []))}"
        )
    if plan.segmentation is not None:
        lines.append(f"Model:      {plan.segmentation.get('model_id', '?')}")
    if plan.roi is not None:
        lines.append(
            f"ROI:        {plan.roi.name} ({plan.roi_placement}, "
            f"tissue class '{plan.roi.geometry.tissue_class}')"
        )

    # Nothing is analysed or measured without an ROI, so saying how would be noise.
    if plan.roi is not None:
        if plan.source:
            source = f"layer starting with '{plan.source}'"
        elif plan.reconstruction is not None:
            source = "the reconstruction produced by this plan"
        else:
            source = "the scan's default PA layer"
        lines.append(f"Analyse:    {source}")

        scope = plan.measure
        layers = (
            "every PA layer in the scan"
            if scope.all_layers
            else "that layer and what is unmixed from it"
        )
        channels = (
            "all channels"
            if scope.all_layers or scope.all_channels
            else "current wavelength (derived layers: all channels)"
        )
        lines.append(
            "Measure:    "
            f"{layers}, "
            f"{'all frames' if scope.all_frames else 'analysis frame'}, "
            f"{channels}"
        )
    wanted = [
        name
        for name, on in (
            ("xlsx", plan.outputs.xlsx),
            ("hdf5", plan.outputs.hdf5),
            ("ipasc", plan.outputs.ipasc),
            ("overlay png", plan.outputs.overlay_png),
        )
        if on
    ]
    lines.append(f"Outputs:    {', '.join(wanted) or 'none'}")
    lines.append(f"Folder:     {plan.output_dir}")
    return "\n".join(lines)
