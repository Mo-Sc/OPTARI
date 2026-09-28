"""Measure real per-step runtimes of the OPTARI pipeline on a real scan.

Unlike ``make_workflow_figure.py`` this script imports OPTARI/PATATO and needs a scan on
disk. It calls the same PATATO/OPTARI entry points the app's controllers call
(``patato.read_reconstruction_preset``, ``SpectralUnmixer``, the segmentation adapters,
``ROIShape.to_napari_verts_world``, ``compute_roi_stats``) directly, without going through
napari/Qt -- the docks only wire these calls to buttons and threads, they do no work
themselves.

Usage
-----
    python figures/benchmark_pipeline.py --scan /path/to/Scan_1 --label workstation

Writes ``figures/timings.json`` (or ``--output``) and prints a summary table.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import numpy as np
import onnxruntime as ort
import patato as pat
from patato.io.attribute_tags import HDF5Tags, IPASCTags, ReconAttributeTags, UnmixingAttributeTags
from patato.io.ithera.read_ithera import iTheraMSOT

from optari import __version__ as optari_version
from optari.config import settings as optari_settings
from optari.patato_bridge import display_data_from_patato_obj, scale_from_patato_obj
from optari.roi import Ellipse, Polygon, ROIPlacementConfig, Rectangle
from optari.roi.roi_records import ROIRecord
from optari.roi.roi_utils import compute_roi_stats
from optari.segmentation.segmenter import create_segmenter, load_model_registry
from optari.utils.setup import get_user_models_dir

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("benchmark_pipeline")

HERE = Path(__file__).parent
DEFAULT_CONFIGS = HERE.parent / "src" / "optari" / "config" / "default_configs"
_ROI_SHAPES = {"ellipse": Ellipse, "rectangle": Rectangle, "polygon": Polygon}
# must match ReconstructionController.DEEPMB_ALGORITHM (reconstruction_controller.py) --
# duplicated as a literal rather than imported so this script never needs Qt/napari.
_DEEPMB_ALGORITHM = "DeepMB ONNX Reconstruction"


@dataclass
class Config:
    scan_path: Path | None = None  # required, set from --scan
    label: str | None = None
    repeats: int = 10
    warmup: int = 3
    frame_idx: int = 0
    channel_idx: int = 0  # unmixed/chromophore channel used for feature extraction

    reconstruction_preset: Path = DEFAULT_CONFIGS / "presets/reconstruction/backproject_ithera.json"
    unmixing_preset: Path = DEFAULT_CONFIGS / "presets/unmixing/haemoglobin.json"

    segmentation_model_id: str | None = None  # None -> optari_settings.segmentation.default_model
    roi_shape: str = "ellipse"
    roi_width_mm: float = 10.0
    roi_height_mm: float = 2.0
    roi_top_margin_mm: float = 0.0
    roi_tissue_class: str | None = None  # None -> segmentation model's default_class
    feature_ids: list[str] | None = None  # None -> every registered feature

    output_json: Path = HERE / "timings.json"


# ---------------------------------------------------------------------------
# timing helper
# ---------------------------------------------------------------------------


def timed_repeats(fn: Callable[[], object], warmup: int, repeats: int, desc: str) -> tuple[list[float], object]:
    """Run *fn* ``warmup`` times (discarded) then ``repeats`` times, timed.

    Warm-up is mandatory, not optional: JAX traces and compiles reconstruction
    algorithms on first call, and ONNX Runtime builds its session graph on first
    inference. Skipping warm-up inflates the mean by an order of magnitude.
    """
    logger.info("%s: %d warm-up run(s)", desc, warmup)
    for _ in range(warmup):
        fn()

    logger.info("%s: %d timed run(s)", desc, repeats)
    durations = []
    result = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = fn()
        durations.append(time.perf_counter() - t0)

    mean = float(np.mean(durations))
    sd = float(np.std(durations, ddof=1)) if repeats > 1 else 0.0
    logger.info("%s: %.4f +/- %.4f s (n=%d)", desc, mean, sd, repeats)
    return durations, result


def summarize(durations: list[float]) -> dict:
    mean = float(np.mean(durations))
    sd = float(np.std(durations, ddof=1)) if len(durations) > 1 else 0.0
    return {"durations_s": durations, "mean_s": mean, "sd_s": sd, "n": len(durations)}


# distinct steps that make up one full pass through the pipeline. "roi_and_features"
# stands in for its two components (roi_placement + feature_extraction) so they aren't
# double-counted.
TOTAL_STEPS = ("data_loading", "reconstruction", "unmixing", "segmentation", "roi_and_features")


def total_summary(steps: dict[str, dict]) -> dict:
    """Sum of step means, with SDs combined as independent stopwatches (variances add)."""
    means = [steps[key]["mean_s"] for key in TOTAL_STEPS]
    variances = [steps[key]["sd_s"] ** 2 for key in TOTAL_STEPS]
    return {
        "steps_included": list(TOTAL_STEPS),
        "mean_s": sum(means),
        "sd_s": float(np.sqrt(sum(variances))),
    }


# ---------------------------------------------------------------------------
# scan loading
# ---------------------------------------------------------------------------


def detect_scan_kind(path: Path) -> str:
    """Mirror ScanController.scan_type without importing the Qt controller stack."""
    import h5py

    if path.is_dir():
        if any(path.glob("*.msot")):
            return "ithera"
        raise ValueError(f"'{path}' is a directory but contains no .msot file")
    if path.suffix.lower() != ".hdf5":
        raise ValueError(f"unrecognised scan path: {path} (expected a folder with a "
                          f".msot file, or a .hdf5 file)")
    with h5py.File(path, "r") as f:
        if IPASCTags.BINARY_DATA in f:
            return "ipasc"
        if HDF5Tags.RAW_DATA in f:
            return "hdf5"
    raise ValueError(f"'{path}' is an HDF5 file but not a recognised PATATO/IPASC scan")


def open_scan(scan_path: Path, kind: str):
    if kind == "ithera":
        return pat.PAData(iTheraMSOT(str(scan_path)))
    return pat.PAData.from_hdf5(str(scan_path), mode="r")


def bench_data_loading(cfg: Config, kind: str) -> tuple[list[float], object]:
    """Time full scan loading, including I/O. Keeps only the last opened handle."""
    durations = []
    pa_data = None
    for i in range(cfg.warmup + cfg.repeats):
        if pa_data is not None:
            pa_data.close()
        t0 = time.perf_counter()
        pa_data = open_scan(cfg.scan_path, kind)
        dt = time.perf_counter() - t0
        if i >= cfg.warmup:
            durations.append(dt)
    mean = float(np.mean(durations))
    sd = float(np.std(durations, ddof=1)) if cfg.repeats > 1 else 0.0
    logger.info("data loading: %.4f +/- %.4f s (n=%d)", mean, sd, cfg.repeats)
    return durations, pa_data


# ---------------------------------------------------------------------------
# reconstruction
# ---------------------------------------------------------------------------


def _resolve_deepmb_params(preset: dict) -> None:
    """Mirror ReconstructionController._resolve_deepmb_model in place: expand the ONNX
    weights path and drop the optari-only 'model_url' key before PATATO sees it.

    Never downloads the weights itself -- unlike OPTARI's UI, which offers a progress
    dialog, a headless benchmark silently fetching ~100s of MB would be a surprise.
    """
    if preset.get(ReconAttributeTags.RECONSTRUCTION_ALGORITHM) != _DEEPMB_ALGORITHM:
        return
    params = dict(preset[ReconAttributeTags.ADDITIONAL_PARAMETERS])
    model_path = Path(params["model_path"]).expanduser()
    if not model_path.is_file():
        raise FileNotFoundError(
            f"DeepMB ONNX weights not downloaded: {model_path}. Launch OPTARI once so it "
            f"can fetch them, or download from {params.get('model_url')}."
        )
    params["model_path"] = str(model_path)
    params.pop("model_url", None)
    preset[ReconAttributeTags.ADDITIONAL_PARAMETERS] = params


def bench_reconstruction(cfg: Config, pa_data) -> tuple[list[float], object, float]:
    preset = json.loads(cfg.reconstruction_preset.read_text())
    speed_of_sound = float(preset.get(ReconAttributeTags.SPEED_OF_SOUND, 1500))
    preset = dict(preset)
    preset.pop("OFFSET_X", None)
    preset.pop("OFFSET_Z", None)
    _resolve_deepmb_params(preset)

    build_t0 = time.perf_counter()
    preprocessor = pat.read_reconstruction_preset(preset)
    reconstruction_algorithm = preprocessor.children[0]
    build_time = time.perf_counter() - build_t0  # one-time cost: builds the DeepMB ONNX
    # session if applicable. Excluded from the per-frame timing below.

    frame = pa_data[cfg.frame_idx : cfg.frame_idx + 1]

    def run_once():
        filtered_time_series, new_settings, _ = preprocessor.run(frame.get_time_series(), frame)
        reconstruction, _, _ = reconstruction_algorithm.run(
            filtered_time_series, frame, speed_of_sound=speed_of_sound, **new_settings
        )
        return reconstruction

    durations, reconstruction = timed_repeats(run_once, cfg.warmup, cfg.repeats, "reconstruction")
    return durations, reconstruction, build_time


# ---------------------------------------------------------------------------
# unmixing
# ---------------------------------------------------------------------------


def bench_unmixing(cfg: Config, pa_data, reconstruction) -> tuple[list[float], object]:
    preset = json.loads(cfg.unmixing_preset.read_text())

    explicit_wavelengths = preset.get(UnmixingAttributeTags.UNMIXING_WAVELENGTHS)
    if explicit_wavelengths is not None:
        wavelengths = [int(w) for w in explicit_wavelengths]
    else:
        all_wavelengths = [int(w) for w in pa_data.get_wavelengths()]
        wl_range = preset.get(UnmixingAttributeTags.WAVELENGTH_RANGE)
        if wl_range is not None:
            lo, hi = int(wl_range[0]), int(wl_range[1])
            wavelengths = [w for w in all_wavelengths if lo <= w <= hi]
        else:
            wavelengths = all_wavelengths

    chromophores = list(preset.get(UnmixingAttributeTags.SPECTRA, []))
    if not wavelengths or not chromophores:
        raise ValueError(
            f"unmixing preset '{cfg.unmixing_preset}' resolved to no wavelengths or no "
            f"chromophores for this scan -- cannot benchmark unmixing."
        )

    reduce_factor = int(preset.get(UnmixingAttributeTags.RESOLUTION_REDUCE, 1))
    suffix = str(preset.get(UnmixingAttributeTags.SUFFIX, ""))
    generate_thb = bool(preset.get(UnmixingAttributeTags.COMPUTE_THB, False))
    generate_so2 = bool(preset.get(UnmixingAttributeTags.COMPUTE_SO2, False))

    unmixer = pat.SpectralUnmixer(
        chromophores=chromophores,
        wavelengths=np.array(wavelengths, dtype=float),
        rescaling_factor=reduce_factor,
        algorithm_id=suffix,
    )
    thb_calc = pat.THbCalculator(algorithm_id=suffix) if generate_thb else None
    so2_calc = pat.SO2Calculator(algorithm_id=suffix, nan_invalid=True) if generate_so2 else None

    def run_once():
        unmixed, _, _ = unmixer.run(reconstruction, pa_data)
        if thb_calc is not None:
            thb_calc.run(unmixed, pa_data)
        if so2_calc is not None:
            so2_calc.run(unmixed, pa_data)
        return unmixed

    return timed_repeats(run_once, cfg.warmup, cfg.repeats, "unmixing")


# ---------------------------------------------------------------------------
# segmentation
# ---------------------------------------------------------------------------


def bench_segmentation(cfg: Config, pa_data):
    registry = load_model_registry()
    model_id = cfg.segmentation_model_id or optari_settings.segmentation.default_model
    if model_id not in registry:
        raise ValueError(f"segmentation model '{model_id}' not in registry: {list(registry)}")
    model_config = registry[model_id]

    model_path = get_user_models_dir() / model_config.filename
    if not model_path.is_file():
        raise FileNotFoundError(
            f"segmentation model not downloaded: {model_path}. Launch OPTARI once so it "
            f"can fetch it, or download it from {model_config.url}."
        )

    build_t0 = time.perf_counter()
    segmenter = create_segmenter(model_config)
    build_time = time.perf_counter() - build_t0  # one-time cost: ONNX session creation.
    # Excluded from the per-frame timing below.

    us_obj = pa_data.get_ultrasound()
    if not hasattr(us_obj, "da"):
        raise RuntimeError(
            "this scan has no ultrasound data (IPASC scans have none) -- segmentation "
            "cannot be benchmarked from it."
        )
    us_img = display_data_from_patato_obj(us_obj)  # (n_frames, n_channels, H, W)
    frame_2d = us_img[cfg.frame_idx, 0]

    def run_once():
        return segmenter.predict(frame_2d[np.newaxis])[0]

    durations, seg_result = timed_repeats(run_once, cfg.warmup, cfg.repeats, "segmentation")

    # Query the execution provider actually bound to the session rather than assuming
    # GPU/CPU -- ONNX Runtime falls back to CPU silently when a requested provider isn't
    # available.
    session_providers = list(segmenter.session.get_providers())

    return durations, seg_result, build_time, model_id, model_config, us_obj, session_providers


# ---------------------------------------------------------------------------
# ROI placement + feature extraction
# ---------------------------------------------------------------------------


def bench_roi_and_features(
    cfg: Config, us_obj, unmixed, seg_result, model_config
) -> tuple[list[float], list[float], object]:
    class_name_to_id = {name: class_id for class_id, name in model_config.class_names.items()}
    tissue_class = cfg.roi_tissue_class or model_config.default_class
    if tissue_class not in class_name_to_id:
        raise ValueError(
            f"tissue class '{tissue_class}' not in model classes: {list(class_name_to_id)}"
        )
    class_id = class_name_to_id[tissue_class]
    class_mask = seg_result.seg == class_id
    if not np.any(class_mask):
        raise ValueError(
            f"class '{tissue_class}' is not present in frame {cfg.frame_idx} -- pick "
            f"another --roi-tissue-class or --frame."
        )

    # ROI placement happens on the US/segmentation grid, exactly like
    # SegmentationController.on_generate_roi_from_mask_clicked.
    us_scale = scale_from_patato_obj(us_obj, tuple(optari_settings.general.US_FALLBACK_SCALE))
    sy, sx = us_scale[-2], us_scale[-1]
    ty, tx = 0.0, 0.0  # the US layer carries no translate in the normal pipeline

    shape_cls = _ROI_SHAPES[cfg.roi_shape]
    shape = shape_cls(ROIPlacementConfig(
        width_mm=cfg.roi_width_mm, height_mm=cfg.roi_height_mm, depth_mm=cfg.roi_top_margin_mm
    ))

    def place_once():
        return shape.to_napari_verts_world(class_mask=class_mask, sy=sy, sx=sx, ty=ty, tx=tx)

    place_durations, verts = timed_repeats(place_once, cfg.warmup, cfg.repeats, "roi placement")

    # Feature extraction measures the *unmixed* image (panel f is "Unmixed + ROI"): the
    # ROI is placed from US-space segmentation but the world-mm verts are rasterized onto
    # whichever layer the stats are computed from, which is the point of the two-branch
    # pipeline -- segmentation runs on ultrasound, ROI stats are read off the optoacoustic
    # data. compute_roi_stats only needs a napari-Image-shaped duck type
    # (.data/.scale/.translate/.metadata/.name), so no napari/Qt is spun up here.
    unmixed_scale = scale_from_patato_obj(unmixed, tuple(optari_settings.general.PA_FALLBACK_SCALE))
    unmixed_display = display_data_from_patato_obj(unmixed)  # (n_frames, n_channels, H, W)
    layer_stub = SimpleNamespace(
        data=unmixed_display,
        scale=unmixed_scale,
        translate=(0.0,) * len(unmixed_scale),
        metadata={"filepath": str(cfg.scan_path), "scan_name": cfg.scan_path.name},
        name="Unmixed (benchmark)",
    )
    record = ROIRecord(
        roi_id=0, track_id=0, frame_id=0, verts=verts, kind=shape.shape_type, tissue_class=tissue_class
    )

    def extract_once():
        return compute_roi_stats(
            [record], layer_stub, frame_idx=0, channel_idx=cfg.channel_idx, feature_ids=cfg.feature_ids
        )

    extract_durations, stats_df = timed_repeats(extract_once, cfg.warmup, cfg.repeats, "feature extraction")

    return place_durations, extract_durations, stats_df


# ---------------------------------------------------------------------------
# environment info
# ---------------------------------------------------------------------------


def cpu_model() -> str:
    system = platform.system()
    try:
        if system == "Darwin":
            return subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
        if system == "Linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        if system == "Windows":
            out = subprocess.check_output(["wmic", "cpu", "get", "name"], text=True)
            return out.splitlines()[1].strip()
    except (OSError, subprocess.CalledProcessError, IndexError):
        pass
    return platform.processor() or "unknown"


def total_ram_gib() -> float | None:
    system = platform.system()
    try:
        if system == "Darwin":
            raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            return round(int(raw) / 2**30, 1)
        if system == "Linux":
            page_size = os.sysconf("SC_PAGE_SIZE")
            n_pages = os.sysconf("SC_PHYS_PAGES")
            return round(page_size * n_pages / 2**30, 1)
        if system == "Windows":
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(MemoryStatusEx)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / 2**30, 1)
    except Exception:
        logger.warning("could not determine total RAM", exc_info=True)
    return None


def gpu_model() -> str | None:
    system = platform.system()
    try:
        if system == "Darwin":
            out = subprocess.check_output(["system_profiler", "SPDisplaysDataType"], text=True)
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("Chipset Model:"):
                    return line.split(":", 1)[1].strip()
        elif system == "Linux":
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], text=True
            )
            lines = out.strip().splitlines()
            return lines[0] if lines else None
        elif system == "Windows":
            out = subprocess.check_output(["wmic", "path", "win32_VideoController", "get", "name"], text=True)
            lines = [l.strip() for l in out.splitlines() if l.strip() and l.strip() != "Name"]
            return lines[0] if lines else None
    except (OSError, subprocess.CalledProcessError, IndexError):
        return None
    return None


def package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {"python": sys.version.split()[0]}
    for name in ("patato", "jax", "onnxruntime", "numpy"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    versions["optari"] = optari_version
    return versions


def gather_environment() -> dict:
    return {
        "cpu_model": cpu_model(),
        "ram_gib": total_ram_gib(),
        "os": platform.platform(),
        "gpu_model": gpu_model(),
        "onnxruntime_available_providers": list(ort.get_available_providers()),
        "package_versions": package_versions(),
    }


def scan_dimensions(pa_data, reconstruction, unmixed) -> dict:
    dims: dict = {"raw_time_series_shape": tuple(int(x) for x in pa_data.shape)}
    try:
        dims["wavelengths_nm"] = [int(w) for w in pa_data.get_wavelengths()]
    except Exception:
        logger.warning("could not read wavelengths from scan", exc_info=True)
        dims["wavelengths_nm"] = None
    dims["reconstruction_image_shape"] = tuple(int(x) for x in np.asarray(reconstruction.da).shape)
    dims["unmixed_image_shape"] = tuple(int(x) for x in np.asarray(unmixed.da).shape)
    return dims


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def print_summary_table(steps: dict[str, dict]) -> None:
    name_w = max(len(k) for k in steps) + 2
    print(f"\n{'step':<{name_w}}{'mean_s':>10}{'sd_s':>10}{'n':>5}")
    print("-" * (name_w + 25))
    for name, s in steps.items():
        print(f"{name:<{name_w}}{s['mean_s']:>10.4f}{s['sd_s']:>10.4f}{s['n']:>5}")
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", required=True, type=Path, help="path to a scan (iThera folder or .hdf5 file)")
    parser.add_argument("--label", default=None, help="tag appended to the output filename, e.g. 'laptop'")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--frame", type=int, default=0, dest="frame_idx")
    parser.add_argument("--channel", type=int, default=0, dest="channel_idx")
    parser.add_argument("--reconstruction-preset", type=Path, default=Config.reconstruction_preset)
    parser.add_argument("--unmixing-preset", type=Path, default=Config.unmixing_preset)
    parser.add_argument("--segmentation-model", default=None, dest="segmentation_model_id")
    parser.add_argument("--roi-shape", choices=list(_ROI_SHAPES), default="ellipse")
    parser.add_argument("--roi-width-mm", type=float, default=10.0)
    parser.add_argument("--roi-height-mm", type=float, default=2.0)
    parser.add_argument("--roi-top-margin-mm", type=float, default=0.0)
    parser.add_argument("--roi-tissue-class", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    output = args.output
    if output is None:
        stem = "timings" + (f"_{args.label}" if args.label else "")
        output = HERE / f"{stem}.json"

    return Config(
        scan_path=args.scan,
        label=args.label,
        repeats=args.repeats,
        warmup=args.warmup,
        frame_idx=args.frame_idx,
        channel_idx=args.channel_idx,
        reconstruction_preset=args.reconstruction_preset,
        unmixing_preset=args.unmixing_preset,
        segmentation_model_id=args.segmentation_model_id,
        roi_shape=args.roi_shape,
        roi_width_mm=args.roi_width_mm,
        roi_height_mm=args.roi_height_mm,
        roi_top_margin_mm=args.roi_top_margin_mm,
        roi_tissue_class=args.roi_tissue_class,
        output_json=output,
    )


def main() -> None:
    cfg = parse_args()
    if cfg.warmup < 1:
        raise ValueError("--warmup must be >= 1: JAX/ONNX first-call costs must be discarded")

    scan_kind = detect_scan_kind(cfg.scan_path)
    logger.info("scan kind: %s", scan_kind)

    load_durations, pa_data = bench_data_loading(cfg, scan_kind)
    try:
        recon_durations, reconstruction, recon_build_s = bench_reconstruction(cfg, pa_data)
        unmix_durations, unmixed = bench_unmixing(cfg, pa_data, reconstruction)
        (
            seg_durations, seg_result, seg_build_s, model_id, model_config, us_obj, ort_providers,
        ) = bench_segmentation(cfg, pa_data)
        place_durations, extract_durations, stats_df = bench_roi_and_features(
            cfg, us_obj, unmixed, seg_result, model_config
        )
        dims = scan_dimensions(pa_data, reconstruction, unmixed)
    finally:
        pa_data.close()

    combined_roi_durations = [p + e for p, e in zip(place_durations, extract_durations)]

    steps = {
        "data_loading": summarize(load_durations),
        "reconstruction": summarize(recon_durations),
        "unmixing": summarize(unmix_durations),
        "segmentation": summarize(seg_durations),
        "roi_placement": summarize(place_durations),
        "feature_extraction": summarize(extract_durations),
        "roi_and_features": summarize(combined_roi_durations),
    }

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "label": cfg.label,
        "scan_path": str(cfg.scan_path),
        "scan_kind": scan_kind,
        "repeats": cfg.repeats,
        "warmup_runs_discarded": cfg.warmup,
        "frame_idx": cfg.frame_idx,
        "channel_idx": cfg.channel_idx,
        "presets": {
            "reconstruction": str(cfg.reconstruction_preset),
            "unmixing": str(cfg.unmixing_preset),
            "segmentation_model_id": model_id,
            "roi_shape": cfg.roi_shape,
            "roi_width_mm": cfg.roi_width_mm,
            "roi_height_mm": cfg.roi_height_mm,
            "roi_top_margin_mm": cfg.roi_top_margin_mm,
            "roi_tissue_class": cfg.roi_tissue_class or model_config.default_class,
        },
        "model_loading": {
            "included_in_per_step_timings": False,
            "note": "Reconstruction-algorithm build and segmentation ONNX-session creation "
                    "are one-time costs (weight/model load, DeepMB ONNX session if used) "
                    "and are reported here separately, not folded into the per-step means "
                    "above.",
            "reconstruction_algorithm_build_s": recon_build_s,
            "segmentation_session_build_s": seg_build_s,
        },
        "onnxruntime": {
            "available_providers": list(ort.get_available_providers()),
            "segmentation_session_providers": ort_providers,
        },
        "environment": gather_environment(),
        "scan_dimensions": dims,
        "steps": steps,
        "total": total_summary(steps),
    }

    cfg.output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.output_json, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("wrote %s", cfg.output_json)

    print_summary_table(steps)
    total = output["total"]
    print(f"total (per scan): {total['mean_s']:.4f} +/- {total['sd_s']:.4f} s")
    print(f"ONNX Runtime execution provider used for segmentation: {ort_providers}")
    print(f"Reconstruction algorithm build (one-time): {recon_build_s:.3f} s")
    print(f"Segmentation session build (one-time): {seg_build_s:.3f} s")


if __name__ == "__main__":
    main()
