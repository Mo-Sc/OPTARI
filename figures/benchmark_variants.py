"""Detailed per-step benchmark: for each pipeline step, times named alternative
configurations against a shared upstream baseline, so a comparison isolates exactly
one step's effect.

Unlike ``benchmark_pipeline.py`` (one canonical run feeding the manuscript figure),
this produces a nested, per-step comparison report. There is no single "total" time:
multiple mutually exclusive branches exist per step (e.g. backprojection vs DeepMB
reconstruction), so summing across them would not mean anything.

Held constant across comparisons (see ``base_choices`` in the output JSON):
  - reconstruction/segmentation compare against the *same* HDF5-loaded scan
  - unmixing compares against the *same* backprojection reconstruction
  - feature extraction compares against the *same* "all classes" segmentation and the
    *same* full-wavelength/full-chromophore unmixing

Usage
-----
    python figures/benchmark_variants.py \\
        --hdf5-scan /path/to/Scan_3.hdf5 --ithera-scan /path/to/Scan_3 \\
        --label workstation --repeats 100

Writes ``figures/timings_variants.json`` (or ``--output``) and prints a summary.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import onnxruntime as ort
import patato as pat
from patato.io.attribute_tags import ReconAttributeTags
from patato.unmixing.spectra import SPECTRA_NAMES

from optari.config import settings as optari_settings
from optari.patato_bridge import display_data_from_patato_obj, scale_from_patato_obj
from optari.roi import Ellipse, Polygon, ROIPlacementConfig, Rectangle
from optari.roi.roi_records import ROIRecord
from optari.roi.roi_utils import compute_roi_stats
from optari.segmentation.segmenter import create_segmenter, load_model_registry
from optari.utils.setup import get_user_models_dir

from benchmark_pipeline import (
    DEFAULT_CONFIGS,
    _resolve_deepmb_params,
    detect_scan_kind,
    gather_environment,
    open_scan,
    summarize,
    timed_repeats,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("benchmark_variants")

HERE = Path(__file__).parent
_ROI_SHAPES = {"ellipse": Ellipse, "rectangle": Rectangle, "polygon": Polygon}


@dataclass
class Config:
    hdf5_scan: Path | None = None    # required, set from --hdf5-scan
    ithera_scan: Path | None = None  # required, set from --ithera-scan
    label: str | None = None
    repeats: int = 100
    warmup: int = 3
    frame_idx: int = 0
    channel_idx: int = 0

    reconstruction_preset_bp: Path = DEFAULT_CONFIGS / "presets/reconstruction/backproject_ithera.json"
    reconstruction_preset_deepmb: Path = DEFAULT_CONFIGS / "presets/reconstruction/deepmb_ithera.json"

    unmixing_wavelengths_partial: tuple[int, ...] = (760, 850)
    unmixing_chromophores_partial: tuple[str, ...] = ("Hb", "HbO2")
    unmixing_chromophores_full: tuple[str, ...] = ("Hb", "HbO2", "Lipid", "Melanin")

    segmentation_model_id: str | None = None       # None -> optari_settings.segmentation.default_model
    segmentation_single_class: str | None = None   # None -> segmentation model's default_class

    roi_shape: str = "ellipse"
    roi_width_mm: float = 10.0
    roi_height_mm: float = 2.0
    roi_top_margin_mm: float = 0.0
    roi_tissue_class: str | None = None  # None -> segmentation_single_class

    output_json: Path = HERE / "timings_variants.json"


# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------


def bench_data_loading(scan_path: Path, kind: str, warmup: int, repeats: int, desc: str):
    """Time full scan loading, including I/O. Keeps only the last opened handle."""
    durations = []
    pa_data = None
    for i in range(warmup + repeats):
        if pa_data is not None:
            pa_data.close()
        t0 = time.perf_counter()
        pa_data = open_scan(scan_path, kind)
        dt = time.perf_counter() - t0
        if i >= warmup:
            durations.append(dt)
    mean = float(np.mean(durations))
    sd = float(np.std(durations, ddof=1)) if repeats > 1 else 0.0
    logger.info("%s: %.4f +/- %.4f s (n=%d)", desc, mean, sd, repeats)
    return summarize(durations), pa_data


# ---------------------------------------------------------------------------
# reconstruction
# ---------------------------------------------------------------------------


def _load_reconstruction_preset(preset_path: Path) -> tuple[dict, float]:
    preset = json.loads(preset_path.read_text())
    speed_of_sound = float(preset.get(ReconAttributeTags.SPEED_OF_SOUND, 1500))
    preset = dict(preset)
    preset.pop("OFFSET_X", None)
    preset.pop("OFFSET_Z", None)
    _resolve_deepmb_params(preset)
    return preset, speed_of_sound


def bench_reconstruction(preset_path: Path, pa_data, frame_idx: int, warmup: int, repeats: int, desc: str):
    preset, speed_of_sound = _load_reconstruction_preset(preset_path)

    build_t0 = time.perf_counter()
    preprocessor = pat.read_reconstruction_preset(preset)
    reconstruction_algorithm = preprocessor.children[0]
    build_time = time.perf_counter() - build_t0  # one-time cost, excluded from the per-run timing below

    frame = pa_data[frame_idx : frame_idx + 1]

    def run_once():
        filtered_time_series, new_settings, _ = preprocessor.run(frame.get_time_series(), frame)
        reconstruction, _, _ = reconstruction_algorithm.run(
            filtered_time_series, frame, speed_of_sound=speed_of_sound, **new_settings
        )
        return reconstruction

    durations, reconstruction = timed_repeats(run_once, warmup, repeats, desc)
    return summarize(durations), reconstruction, build_time


def reconstruct_all_frames(preset_path: Path, pa_data):
    """Untimed setup: reconstruct every frame, for the feature-extraction all-frames variant."""
    preset, speed_of_sound = _load_reconstruction_preset(preset_path)
    preprocessor = pat.read_reconstruction_preset(preset)
    reconstruction_algorithm = preprocessor.children[0]
    filtered_time_series, new_settings, _ = preprocessor.run(pa_data.get_time_series(), pa_data)
    reconstruction, _, _ = reconstruction_algorithm.run(
        filtered_time_series, pa_data, speed_of_sound=speed_of_sound, **new_settings
    )
    return reconstruction


# ---------------------------------------------------------------------------
# unmixing
# ---------------------------------------------------------------------------


def valid_wavelengths_for_chromophores(wavelengths: list[int], chromophores: list[str]) -> list[int]:
    """Keep only wavelengths where every chromophore has a defined absorption value.

    PATATO's spectra tables don't cover every chromophore at every wavelength -- Hb and
    HbO2 have no data above ~980nm in this scan's range, for instance. Unmixing with an
    out-of-table wavelength puts NaN in the spectra matrix and the pseudo-inverse's SVD
    fails to converge, so this is a real data-validity check, not just tidying.
    """
    wl_arr = np.array(wavelengths, dtype=float)
    valid = np.ones(len(wavelengths), dtype=bool)
    for chromophore in chromophores:
        valid &= np.isfinite(SPECTRA_NAMES[chromophore].get_spectrum(wl_arr))
    dropped = [w for w, ok in zip(wavelengths, valid) if not ok]
    if dropped:
        logger.warning(
            "dropping wavelength(s) %s: no defined absorption spectrum for one or more of "
            "%s there (PATATO's spectra tables don't extend that far)",
            dropped, chromophores,
        )
    return [w for w, ok in zip(wavelengths, valid) if ok]


def bench_unmixing(reconstruction, pa_data, wavelengths, chromophores, warmup: int, repeats: int, desc: str):
    unmixer = pat.SpectralUnmixer(
        chromophores=list(chromophores),
        wavelengths=np.array(wavelengths, dtype=float),
        rescaling_factor=1,
        algorithm_id="",
    )

    def run_once():
        unmixed, _, _ = unmixer.run(reconstruction, pa_data)
        return unmixed

    durations, unmixed = timed_repeats(run_once, warmup, repeats, desc)
    return summarize(durations), unmixed


def unmix_all_frames(pa_data, reconstruction_all, wavelengths, chromophores):
    """Untimed setup: unmix every frame, for the feature-extraction all-frames variant."""
    unmixer = pat.SpectralUnmixer(
        chromophores=list(chromophores),
        wavelengths=np.array(wavelengths, dtype=float),
        rescaling_factor=1,
        algorithm_id="",
    )
    unmixed, _, _ = unmixer.run(reconstruction_all, pa_data)
    return unmixed


# ---------------------------------------------------------------------------
# segmentation
# ---------------------------------------------------------------------------


def bench_segmentation(segmenter, frame_2d: np.ndarray, selected_ids: set[int], n_channels: int,
                        warmup: int, repeats: int, desc: str):
    """Times inference *and* the class-filtering step (mirrors SegmentationController's
    ``_segment_frames``), since that filtering is what "selected classes" actually
    changes -- ``segmenter.predict()`` alone always predicts every class regardless."""

    def run_once():
        result = segmenter.predict(frame_2d[np.newaxis])[0]
        filtered = np.where(np.isin(result.seg, list(selected_ids)), result.seg, 0).astype(np.int32)
        mask = np.repeat(filtered[np.newaxis, np.newaxis], n_channels, axis=1)  # (1, n_channels, H, W)
        return mask, result.class_names

    durations, (mask, class_names) = timed_repeats(run_once, warmup, repeats, desc)
    return summarize(durations), mask, class_names


# ---------------------------------------------------------------------------
# feature extraction
# ---------------------------------------------------------------------------


def bench_feature_extraction_single_frame(layer_stub, records, channel_idx: int,
                                           warmup: int, repeats: int, desc: str):
    def run_once():
        return compute_roi_stats(records, layer_stub, frame_idx=0, channel_idx=channel_idx, feature_ids=None)

    durations, _ = timed_repeats(run_once, warmup, repeats, desc)
    return summarize(durations)


def bench_feature_extraction_all_frames(layer_stub, records, channel_idx: int, n_frames: int,
                                         warmup: int, repeats: int, desc: str):
    def run_once():
        for frame_idx in range(n_frames):
            compute_roi_stats(records, layer_stub, frame_idx=frame_idx, channel_idx=channel_idx, feature_ids=None)

    durations, _ = timed_repeats(run_once, warmup, repeats, desc)
    return summarize(durations)


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def print_summary(steps: dict) -> None:
    for step_name, variants in steps.items():
        print(f"\n{step_name}")
        for variant_name, s in variants.items():
            print(f"  {variant_name:<32}{s['mean_s']:>12.6f} s  +/- {s['sd_s']:>10.6f}  (n={s['n']})")
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hdf5-scan", required=True, type=Path)
    parser.add_argument("--ithera-scan", required=True, type=Path)
    parser.add_argument("--label", default=None)
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--frame", type=int, default=0, dest="frame_idx")
    parser.add_argument("--channel", type=int, default=0, dest="channel_idx")
    parser.add_argument("--reconstruction-preset-bp", type=Path, default=Config.reconstruction_preset_bp)
    parser.add_argument("--reconstruction-preset-deepmb", type=Path, default=Config.reconstruction_preset_deepmb)
    parser.add_argument("--segmentation-model", default=None, dest="segmentation_model_id")
    parser.add_argument("--segmentation-single-class", default=None)
    parser.add_argument("--roi-shape", choices=list(_ROI_SHAPES), default="ellipse")
    parser.add_argument("--roi-width-mm", type=float, default=10.0)
    parser.add_argument("--roi-height-mm", type=float, default=2.0)
    parser.add_argument("--roi-top-margin-mm", type=float, default=0.0)
    parser.add_argument("--roi-tissue-class", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    output = args.output
    if output is None:
        stem = "timings_variants" + (f"_{args.label}" if args.label else "")
        output = HERE / f"{stem}.json"

    return Config(
        hdf5_scan=args.hdf5_scan,
        ithera_scan=args.ithera_scan,
        label=args.label,
        repeats=args.repeats,
        warmup=args.warmup,
        frame_idx=args.frame_idx,
        channel_idx=args.channel_idx,
        reconstruction_preset_bp=args.reconstruction_preset_bp,
        reconstruction_preset_deepmb=args.reconstruction_preset_deepmb,
        segmentation_model_id=args.segmentation_model_id,
        segmentation_single_class=args.segmentation_single_class,
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

    # Populated incrementally so a late failure (e.g. one variant's numerics don't work
    # out) doesn't throw away already-measured, expensive results (DeepMB reconstruction
    # alone is ~25 min at 100 reps) -- see save_partial() below.
    steps: dict = {}
    partial_path = cfg.output_json.with_name(cfg.output_json.stem + ".partial" + cfg.output_json.suffix)

    def save_partial() -> None:
        with open(partial_path, "w") as f:
            json.dump({"generated_at": datetime.now(UTC).isoformat(), "label": cfg.label,
                       "steps_completed_before_failure": steps}, f, indent=2, default=str)
        logger.warning("run failed partway through -- completed steps saved to %s", partial_path)

    hdf5_kind = detect_scan_kind(cfg.hdf5_scan)
    ithera_kind = detect_scan_kind(cfg.ithera_scan)
    logger.info("hdf5 scan kind: %s, ithera scan kind: %s", hdf5_kind, ithera_kind)

    # --- data loading: hdf5 vs ithera (independent, nothing shared upstream) ---
    load_hdf5_summary, pa_data_hdf5 = bench_data_loading(
        cfg.hdf5_scan, hdf5_kind, cfg.warmup, cfg.repeats, "data loading: hdf5"
    )
    load_ithera_summary, pa_data_ithera = bench_data_loading(
        cfg.ithera_scan, ithera_kind, cfg.warmup, cfg.repeats, "data loading: ithera"
    )
    pa_data_ithera.close()  # not needed downstream; hdf5 is the base for every later step
    steps["data_loading"] = {"hdf5": load_hdf5_summary, "ithera": load_ithera_summary}

    pa_data = pa_data_hdf5
    try:
        # --- reconstruction: backprojection vs deepmb, both from the same loaded scan ---
        recon_bp_summary, recon_bp, recon_bp_build_s = bench_reconstruction(
            cfg.reconstruction_preset_bp, pa_data, cfg.frame_idx, cfg.warmup, cfg.repeats,
            "reconstruction: backprojection",
        )
        recon_deepmb_summary, _recon_deepmb, recon_deepmb_build_s = bench_reconstruction(
            cfg.reconstruction_preset_deepmb, pa_data, cfg.frame_idx, cfg.warmup, cfg.repeats,
            "reconstruction: deepmb",
        )
        steps["reconstruction"] = {
            "backprojection": {**recon_bp_summary, "preset": str(cfg.reconstruction_preset_bp)},
            "deepmb": {**recon_deepmb_summary, "preset": str(cfg.reconstruction_preset_deepmb)},
        }
        save_partial()

        # --- unmixing: partial vs full, both from the same (backprojection) reconstruction.
        # Wavelengths are filtered to ones every requested chromophore actually has
        # absorption data for -- PATATO's Hb/HbO2 tables stop around 980nm, so blindly
        # using every acquired wavelength produces NaN in the spectra matrix. ---
        available_wavelengths = [int(w) for w in pa_data.get_wavelengths()]
        partial_wavelengths = valid_wavelengths_for_chromophores(
            list(cfg.unmixing_wavelengths_partial), list(cfg.unmixing_chromophores_partial)
        )
        full_wavelengths = valid_wavelengths_for_chromophores(
            available_wavelengths, list(cfg.unmixing_chromophores_full)
        )
        if not partial_wavelengths or not full_wavelengths:
            raise ValueError("no wavelength has defined absorption data for all requested chromophores")

        unmix_partial_summary, _unmixed_partial = bench_unmixing(
            recon_bp, pa_data, partial_wavelengths, cfg.unmixing_chromophores_partial,
            cfg.warmup, cfg.repeats, "unmixing: partial (2wl/2chromo)",
        )
        unmix_full_summary, unmixed_full = bench_unmixing(
            recon_bp, pa_data, full_wavelengths, cfg.unmixing_chromophores_full,
            cfg.warmup, cfg.repeats, "unmixing: full (all wl/all chromo)",
        )
        steps["unmixing"] = {
            "partial_2wl_2chromo": {
                **unmix_partial_summary,
                "wavelengths_nm": partial_wavelengths,
                "chromophores": list(cfg.unmixing_chromophores_partial),
            },
            "full_all_wl_all_chromo": {
                **unmix_full_summary,
                "wavelengths_nm": full_wavelengths,
                "wavelengths_dropped_nm": sorted(set(available_wavelengths) - set(full_wavelengths)),
                "chromophores": list(cfg.unmixing_chromophores_full),
            },
        }
        save_partial()

        # --- segmentation: single class vs all classes, same model/session, same US frame ---
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

        seg_build_t0 = time.perf_counter()
        segmenter = create_segmenter(model_config)
        seg_build_s = time.perf_counter() - seg_build_t0

        us_obj = pa_data.get_ultrasound()
        if not hasattr(us_obj, "da"):
            raise RuntimeError("this scan has no ultrasound data -- segmentation cannot be benchmarked from it.")
        us_img = display_data_from_patato_obj(us_obj)  # (n_frames, n_channels, H, W)
        frame_2d = us_img[cfg.frame_idx, 0]
        n_channels = int(us_img.shape[1])

        class_name_to_id = {name: cid for cid, name in model_config.class_names.items()}
        single_class_name = cfg.segmentation_single_class or model_config.default_class
        if single_class_name not in class_name_to_id:
            raise ValueError(f"'{single_class_name}' not in model classes: {list(class_name_to_id)}")
        single_ids = {class_name_to_id[single_class_name]}
        all_ids = set(model_config.class_names.keys())

        seg_single_summary, seg_single_mask, _ = bench_segmentation(
            segmenter, frame_2d, single_ids, n_channels, cfg.warmup, cfg.repeats,
            "segmentation: single class",
        )
        seg_all_summary, seg_all_mask, _ = bench_segmentation(
            segmenter, frame_2d, all_ids, n_channels, cfg.warmup, cfg.repeats,
            "segmentation: all classes",
        )
        ort_providers = list(segmenter.session.get_providers())
        steps["segmentation"] = {
            "single_class": {**seg_single_summary, "selected_classes": [single_class_name]},
            "all_classes": {**seg_all_summary, "selected_classes": sorted(model_config.class_names.values())},
        }
        save_partial()

        # --- feature extraction: single frame vs all frames ---
        # ROI placement itself isn't a requested comparison here -- placed once (untimed)
        # from the "all classes" segmentation, which is a superset of "single class".
        roi_tissue_class = cfg.roi_tissue_class or single_class_name
        class_mask = seg_all_mask[0, 0] == class_name_to_id[roi_tissue_class]
        if not np.any(class_mask):
            raise ValueError(f"class '{roi_tissue_class}' not present in frame {cfg.frame_idx}.")

        us_scale = scale_from_patato_obj(us_obj, tuple(optari_settings.general.US_FALLBACK_SCALE))
        sy, sx = us_scale[-2], us_scale[-1]
        shape = _ROI_SHAPES[cfg.roi_shape](ROIPlacementConfig(
            width_mm=cfg.roi_width_mm, height_mm=cfg.roi_height_mm, depth_mm=cfg.roi_top_margin_mm
        ))
        verts = shape.to_napari_verts_world(class_mask=class_mask, sy=sy, sx=sx, ty=0.0, tx=0.0)
        record = ROIRecord(
            roi_id=0, track_id=0, frame_id=0, verts=verts, kind=shape.shape_type, tissue_class=roi_tissue_class
        )

        unmixed_full_scale = scale_from_patato_obj(unmixed_full, tuple(optari_settings.general.PA_FALLBACK_SCALE))
        layer_stub_single = SimpleNamespace(
            data=display_data_from_patato_obj(unmixed_full),
            scale=unmixed_full_scale,
            translate=(0.0,) * len(unmixed_full_scale),
            metadata={"filepath": str(cfg.hdf5_scan), "scan_name": cfg.hdf5_scan.name},
            name="Unmixed (benchmark, single frame)",
        )
        extract_single_summary = bench_feature_extraction_single_frame(
            layer_stub_single, [record], cfg.channel_idx, cfg.warmup, cfg.repeats,
            "feature extraction: single frame",
        )

        # untimed setup for the all-frames variant: reconstruct + unmix every frame once,
        # same presets/config as the "base" branches above (backprojection, full unmixing).
        logger.info("reconstructing + unmixing every frame for the all-frames variant (untimed setup)...")
        recon_all = reconstruct_all_frames(cfg.reconstruction_preset_bp, pa_data)
        unmixed_all = unmix_all_frames(pa_data, recon_all, full_wavelengths, cfg.unmixing_chromophores_full)
        n_frames = int(pa_data.shape[0])
        unmixed_all_scale = scale_from_patato_obj(unmixed_all, tuple(optari_settings.general.PA_FALLBACK_SCALE))
        layer_stub_all = SimpleNamespace(
            data=display_data_from_patato_obj(unmixed_all),
            scale=unmixed_all_scale,
            translate=(0.0,) * len(unmixed_all_scale),
            metadata={"filepath": str(cfg.hdf5_scan), "scan_name": cfg.hdf5_scan.name},
            name="Unmixed (benchmark, all frames)",
        )
        extract_all_summary = bench_feature_extraction_all_frames(
            layer_stub_all, [record], cfg.channel_idx, n_frames, cfg.warmup, cfg.repeats,
            "feature extraction: all frames",
        )
        steps["feature_extraction"] = {
            "single_frame": {**extract_single_summary, "n_frames": 1},
            "all_frames": {**extract_all_summary, "n_frames": n_frames},
        }

        dims = {
            "raw_time_series_shape": tuple(int(x) for x in pa_data.shape),
            "wavelengths_nm": available_wavelengths,
            "n_frames": n_frames,
            "reconstruction_image_shape": tuple(int(x) for x in np.asarray(recon_bp.da).shape),
            "unmixed_full_image_shape": tuple(int(x) for x in np.asarray(unmixed_full.da).shape),
        }
    except Exception:
        save_partial()
        raise
    finally:
        pa_data_hdf5.close()

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "label": cfg.label,
        "scan": {"hdf5_path": str(cfg.hdf5_scan), "ithera_path": str(cfg.ithera_scan)},
        "repeats": cfg.repeats,
        "warmup_runs_discarded": cfg.warmup,
        "frame_idx": cfg.frame_idx,
        "channel_idx": cfg.channel_idx,
        "base_choices": {
            "note": "each step's variants are benchmarked against the same upstream result "
                    "named here, so a comparison isolates only that step's own effect.",
            "reconstruction_uses_data_loading": "hdf5",
            "unmixing_uses_reconstruction": "backprojection",
            "feature_extraction_uses_segmentation": "all_classes",
            "feature_extraction_uses_unmixing": "full_all_wl_all_chromo",
        },
        "model_loading": {
            "included_in_per_step_timings": False,
            "reconstruction_algorithm_build_s": {
                "backprojection": recon_bp_build_s, "deepmb": recon_deepmb_build_s,
            },
            "segmentation_session_build_s": seg_build_s,
        },
        "onnxruntime": {
            "available_providers": list(ort.get_available_providers()),
            "segmentation_session_providers": ort_providers,
        },
        "environment": gather_environment(),
        "scan_dimensions": dims,
        "steps": steps,
    }

    cfg.output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.output_json, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("wrote %s", cfg.output_json)
    partial_path.unlink(missing_ok=True)  # run succeeded end to end, drop the crash-recovery file

    print_summary(steps)
    print(f"ONNX Runtime execution provider used for segmentation: {ort_providers}")
    print(f"Reconstruction algorithm build (one-time): BP={recon_bp_build_s:.3f}s "
          f"DeepMB={recon_deepmb_build_s:.3f}s")
    print(f"Segmentation session build (one-time): {seg_build_s:.3f} s")


if __name__ == "__main__":
    main()
