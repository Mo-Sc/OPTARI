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

from patato.io.attribute_tags import ReconAttributeTags

from optari.io.discovery import ScanInfo, discover_studies, scan_key
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
    resolve_model_path,
)

logger = logging.getLogger(__name__)

MEASURE_LAYER_MODES = ("analysis", "all_pa")
ROI_FROM_SCAN = "from_scan"


@dataclass(frozen=True)
class BatchJob:
    """One scan to process, and where its outputs belong."""

    study_path: Path
    scan_path: Path
    scan_info: ScanInfo

    @property
    def scan_stem(self) -> str:
        """``Scan_3``, whether the scan is an HDF5 file or an iThera folder."""
        return scan_key(self.scan_path)

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
    # Measure the scan's own ROIs instead of placing one, each on its own frames.
    roi_from_scan: bool = False
    # Layer-name prefix picking the reconstruction everything downstream runs on.
    # None means the reconstruction step's own output, or the scan's default PA layer.
    source: str | None = None
    frame: int | str = "motion"
    measure: MeasureScope = field(default_factory=MeasureScope)
    outputs: OutputSpec = field(default_factory=OutputSpec)
    # A resumed run writes table and report under names of its own, so the
    # interrupted run's survive next to them.
    run_suffix: str = ""

    @property
    def table_path(self) -> Path:
        """Where the run's ROI measurements are written (batch_roi_table.xlsx)."""
        return self.output_dir / f"batch_roi_table{self.run_suffix}.xlsx"

    @property
    def report_path(self) -> Path:
        """Where the run's per-scan status report is written (batch_report.xlsx)."""
        return self.output_dir / f"batch_report{self.run_suffix}.xlsx"

    def export_path(self, job: BatchJob, kind: str) -> Path:
        """Where *job*'s ``"hdf5"`` or ``"ipasc"`` export goes.

        Exports mirror the input layout, so a converted dataset can be reopened
        exactly like the original: <out>/<format>/Study_X/Scan_Y.hdf5
        """
        # same suffix as the Scan Browser's export
        suffix = "_ipasc" if kind == "ipasc" else ""
        return (
            self.output_dir
            / kind
            / job.study_path.name
            / f"{job.scan_stem}{suffix}.hdf5"
        )

    @property
    def measures(self) -> bool:
        """Whether this plan measures ROIs at all."""
        return self.roi is not None or self.roi_from_scan

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
        if self.roi_from_scan:
            names.append("roi (from scan)")
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
    except (ValueError, OSError) as exc:
        raise ValueError(
            f"Could not load {label} preset '{name}': {exc}"
        ) from exc


def _measure_scope(spec: dict, all_frames: bool) -> MeasureScope:
    if "all_frames" in spec:
        raise ValueError(
            "'all_frames' moved out of 'measure' to the top level of the batch preset."
        )
    mode = str(spec.get("layers", "analysis"))
    if mode not in MEASURE_LAYER_MODES:
        raise ValueError(
            f"Invalid measure.layers '{mode}'. Use one of {MEASURE_LAYER_MODES}."
        )
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
    if value is None:
        return "motion"
    if value in ("motion", "acquisition_start", "roi"):
        return value
    raise ValueError(
        f"Invalid frame selector {value!r}. Use 'motion', 'acquisition_start', 'roi' or a frame number."
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
        for study, scans in discover_studies(root).items()
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
    roi_from_scan = name == ROI_FROM_SCAN
    if name is not None and not roi_from_scan:
        try:
            roi = RoiPresetStore(get_user_roi_presets_dir()).get(name)
        except (TypeError, ValueError, OSError) as exc:
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
        roi_from_scan=roi_from_scan,
        source=(batch_preset.get("source") or None),
        frame=_frame_selector(batch_preset.get("frame")),
        # the scan's ROIs sit on their own frames, so steps and measurement need them all
        measure=_measure_scope(
            batch_preset.get("measure") or {},
            bool(batch_preset.get("all_frames", False)) or roi_from_scan,
        ),
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

    problems += _validate_reconstruction(plan)
    problems += _validate_segmentation(plan)
    problems += _validate_unmixing(plan)
    problems += _validate_output_dir(plan)
    return problems


def plan_warnings(plan: BatchPlan) -> list[str]:
    """Things worth saying out loud that are not reasons to refuse the run."""
    if plan.source or plan.reconstruction is not None:
        return []
    if plan.unmixing is None and not plan.measures:
        return []
    return [
        "No reconstruction step and no 'source', so the scan's default PA layer will "
        "be analysed. Set 'source' to a layer-name prefix to choose deliberately."
    ]


def _validate_reconstruction(plan: BatchPlan) -> list[str]:
    if plan.reconstruction is None:
        return []
    # Learned reconstructions (DeepMB) name their weights, a batch run never downloads.
    model_path = plan.reconstruction.get(
        ReconAttributeTags.ADDITIONAL_PARAMETERS, {}
    ).get("model_path")
    if model_path is None or resolve_model_path(model_path).is_file():
        return []
    return [
        f"Reconstruction weights '{model_path}' are not downloaded. Run the "
        "reconstruction once from the Reconstruction dock to fetch them, then retry."
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


def resume_plan(plan: BatchPlan) -> list[str]:
    """Drop the scans an earlier run into the same folder already exported.

    Exports are written atomically and after a scan's measurements are saved, so an
    existing export marks a finished scan. Returns problems that rule out resuming,
    like ``validate_plan``.
    """
    kinds = [k for k in ("hdf5", "ipasc") if getattr(plan.outputs, k)]
    if not kinds:
        return [
            "Resuming needs an hdf5 or ipasc export to recognise finished scans."
        ]
    plan.jobs = [
        job
        for job in plan.jobs
        if not all(plan.export_path(job, kind).exists() for kind in kinds)
    ]
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
    if plan.roi_from_scan:
        lines.append(
            "ROI:        the scan's own, each on the frames it is drawn on"
        )

    # Nothing is analysed or measured without an ROI, so saying how would be noise.
    if plan.measures:
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
