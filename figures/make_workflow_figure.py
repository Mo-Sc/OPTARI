"""Assemble the PATARI workflow/timing figure from pre-exported panel screenshots.

Standalone: reads image files and ``timings.json``, no PATARI/PATATO import. Keep it that
way so the figure can be regenerated later without the rest of the stack installed.

Usage
-----
    python figures/make_workflow_figure.py

Everything tunable lives in ``CONFIG`` below.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("make_workflow_figure")

HERE = Path(__file__).parent


@dataclass
class Config:
    # --- input panels -----------------------------------------------------
    # Row 1 is the optoacoustic chain, row 2 the ultrasound chain; panel (f) is where
    # they converge. Order here is layout order: (a,b,c) top row, (d,e,f) bottom row.
    panels: dict[str, str] = field(
        default_factory=lambda: {
            "raw": "images/raw.png",
            "reconstruction": "images/reconstruction.png",
            "unmixed": "images/unmixed.png",
            "us": "images/us.png",
            "segmentation": "images/segmentation.png",
            "roi": "images/unmixed_roi.png",
        }
    )
    layout: tuple[tuple[str, str], tuple[str, str]] = (
        ("raw", "reconstruction"),
        ("us", "segmentation"),
    )
    # third column handled separately below (unmixed / roi), since it is the panel the
    # two rows share
    row1_third: str = "unmixed"
    row2_third: str = "roi"

    # Row-scoped, not sequential: (a1)-(a3) is the optoacoustic chain, (b1)-(b2) the
    # ultrasound chain, (c) is where they converge. A single a->f alphabet would read
    # as one linear pipeline, which this isn't -- (b1) doesn't follow from (a3).
    letters: dict[str, str] = field(
        default_factory=lambda: {
            "raw": "a1",
            "reconstruction": "a2",
            "unmixed": "a3",
            "us": "b1",
            "segmentation": "b2",
            "roi": "c",
        }
    )
    titles: dict[str, str] = field(
        default_factory=lambda: {
            "raw": "Raw time series",
            "reconstruction": "Reconstruction",
            "unmixed": "Unmixed",
            "us": "Ultrasound",
            "segmentation": "Segmentation",
            "roi": "Unmixed + ROI",
        }
    )
    # panel -> [(step, variant, label template, count field), ...] into timings.json's
    # nested "steps" block (steps.<step>.<variant>.mean_s/sd_s). None = no timing line
    # (us). Each panel gets one line per entry, stacked, so every panel here needs the
    # same number of variants or the rows stop aligning.
    # count field: None for a static label; "<field>" reads an int field from that
    # variant's JSON entry and fills it into "{n}" in the label; "len:<field>" reads a
    # list field's length instead. Pulls the actual number (e.g. class/frame count)
    # from the data rather than hardcoding "all".
    timing_variants: dict[str, list[tuple[str, str, str, str | None]] | None] = field(
        default_factory=lambda: {
            "raw": [
                ("data_loading", "hdf5", "HDF5", None),
                ("data_loading", "ithera", "iThera", None),
            ],
            "reconstruction": [
                ("reconstruction", "backprojection", "BP", None),
                ("reconstruction", "deepmb", "DeepMB", None),
            ],
            "unmixed": [
                ("unmixing", "partial_2wl_2chromo", "2λ/2chromo", None),
                ("unmixing", "full_all_wl_all_chromo", "9λ/4chromo", None),
            ],
            "us": None,
            "segmentation": [
                ("segmentation", "single_class", "1 class", None),
                ("segmentation", "all_classes", "{n} classes", "len:selected_classes"),
            ],
            "roi": [
                ("feature_extraction", "single_frame", "1 frame", None),
                ("feature_extraction", "all_frames", "{n} frames", "n_frames"),
            ],
        }
    )

    # --- per-panel crop overrides ------------------------------------------------
    # (start, end) in source-image pixel coordinates, along whichever axis is being
    # trimmed to make the panel square (the long axis). Omit a panel for a plain
    # centre crop. Needed for e.g. "raw" where the informative part of a sinogram is
    # rarely centred.
    crop: dict[str, tuple[int, int]] = field(default_factory=dict)

    # --- normalisation ------------------------------------------------------------
    panel_px: int = 800  # target square size; Lanczos downscale only, never upscale
    min_panel_in: float = 1.8  # warn if a cropped panel can't support this at 300 dpi

    # --- page geometry --------------------------------------------------------
    # Get the real value from the manuscript: put \the\textwidth in the .tex and
    # divide the result (in pt) by 72.27 to get inches.
    fig_width_in: float = 6.5
    left_margin_in: float = 0.05
    right_margin_in: float = 0.05
    top_margin_in: float = 0.02
    bottom_margin_in: float = 0.02
    col_gap_in: float = 0.34  # horizontal gap between columns; carries 1 h-arrow each
    # Panels shrink to this fraction of the full column width (the freed width goes to
    # centred outer margin, not bigger gaps -- col_gap_in stays sized for the arrows).
    # Needed room: two timing lines per panel now instead of one.
    panel_scale: float = 0.78
    # vertical gap between rows, split top -> bottom into: row-1 timing text,
    # the vertical arrow, row-2 panel title. Each sized independently so none overlap.
    # timing_line_h_in is per line; each panel shows up to 2 stacked lines (see
    # timing_variants), so the timing zones below are sized for 2 lines.
    timing_line_h_in: float = 0.135
    arrow_zone_h_in: float = 0.19
    row2_title_h_in: float = 0.17
    row_title_h_in: float = 0.17  # row-1 title zone (letter + title text, above row 1)

    @property
    def row1_timing_h_in(self) -> float:
        return 2 * self.timing_line_h_in

    @property
    def row_timing_h_in(self) -> float:
        return 2 * self.timing_line_h_in

    panel_border: bool = False  # thin light border per panel, off by default

    # --- styling -----------------------------------------------------------------
    font_family: tuple[str, ...] = ("Times New Roman", "Nimbus Roman", "serif")
    title_fontsize: float = 9.0
    timing_fontsize: float = 8.0
    arrow_color: str = "0.35"
    arrow_linewidth: float = 0.9
    arrow_mutation_scale: float = 7.0
    arrow_pad_in: float = 0.04  # keep arrows off the panel edges
    # the (c)->(f) vertical arrow is the whole point of the figure (segmentation runs on
    # US, not PA) but has less run than the horizontal arrows to carry it in -> drawn
    # heavier so it reads at a glance, not just on close inspection.
    vertical_arrow_linewidth: float = 1.4
    vertical_arrow_mutation_scale: float = 9.0

    # --- optional segmentation legend --------------------------------------------
    show_segmentation_legend: bool = False
    legend_h_in: float = 0.14
    class_names: dict[int, str] = field(default_factory=dict)  # id -> English name
    class_colors: dict[int, str] = field(default_factory=dict)  # id -> matplotlib color

    # --- I/O -----------------------------------------------------------------
    timings_json: str = "timings_variants.json"
    output_pdf: str = "workflow_figure.pdf"
    output_png: str = "workflow_figure.png"
    png_dpi: int = 300


CONFIG = Config()


# ---------------------------------------------------------------------------
# panel normalisation
# ---------------------------------------------------------------------------


def _square_crop_bounds(width: int, height: int, override: tuple[int, int] | None) -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) for a centred (or overridden) square crop."""
    side = min(width, height)
    if width >= height:
        if override is not None:
            left, right = override
        else:
            left = (width - side) // 2
            right = left + side
        return left, 0, right, height
    if override is not None:
        top, bottom = override
    else:
        top = (height - side) // 2
        bottom = top + side
    return 0, top, width, bottom


def load_and_crop_panel(key: str, path: Path, crop_override: tuple[int, int] | None) -> Image.Image:
    if not path.is_file():
        raise FileNotFoundError(f"Panel image for '{key}' not found: {path}")

    img = Image.open(path).convert("RGB")
    width, height = img.size
    left, top, right, bottom = _square_crop_bounds(width, height, crop_override)
    side = right - left if width >= height else bottom - top
    logger.info(
        "panel '%s': source %dx%d -> crop box (%d, %d, %d, %d), side %dpx",
        key, width, height, left, top, right, bottom, side,
    )
    if right - left != bottom - top:
        raise AssertionError(
            f"panel '{key}': crop override does not produce a square "
            f"({right - left}px x {bottom - top}px)"
        )
    return img.crop((left, top, right, bottom))


def normalize_panels(cfg: Config) -> dict[str, np.ndarray]:
    """Crop every configured panel to a square and resample to a common size.

    Never upscales: if any cropped panel is smaller than ``cfg.panel_px``, falls back
    to the largest size every panel can provide.
    """
    cropped: dict[str, Image.Image] = {}
    for key, rel_path in cfg.panels.items():
        cropped[key] = load_and_crop_panel(key, HERE / rel_path, cfg.crop.get(key))

    cropped_sides = {key: img.size[0] for key, img in cropped.items()}  # square: w==h
    target_px = cfg.panel_px
    smallest_key = min(cropped_sides, key=cropped_sides.get)
    smallest_side = cropped_sides[smallest_key]
    if smallest_side < cfg.panel_px:
        logger.warning(
            "panel '%s' is only %dpx square after cropping (< PANEL_PX=%d). "
            "Falling back to %dpx for every panel so nothing is upscaled.",
            smallest_key, smallest_side, cfg.panel_px, smallest_side,
        )
        target_px = smallest_side

    min_required_px = int(np.ceil(cfg.min_panel_in * 300))
    for key, side in cropped_sides.items():
        if side < min_required_px:
            logger.warning(
                "panel '%s' is %dpx square after cropping, below the %dpx needed for "
                "a %.2f in panel at 300 dpi. This panel will look soft in print.",
                key, side, min_required_px, cfg.min_panel_in,
            )

    resampled: dict[str, np.ndarray] = {}
    for key, img in cropped.items():
        if img.size[0] != target_px:
            img = img.resize((target_px, target_px), Image.LANCZOS)
        resampled[key] = np.asarray(img)

    shapes = {arr.shape for arr in resampled.values()}
    assert len(shapes) == 1, f"normalised panels do not share a shape: {shapes}"
    return resampled


# ---------------------------------------------------------------------------
# timing formatting
# ---------------------------------------------------------------------------


def round_mean_sd(mean: float, sd: float) -> tuple[float, float, int]:
    """Round (mean, sd) to the precision set by the SD.

    Standard "round the uncertainty first" convention (PDG rule): the SD keeps 2
    significant figures if its leading digit is 1, else 1; the mean is rounded to the
    same decimal place. Reproduces e.g. 1.24 +/- 0.08, 0.42 +/- 0.03.
    """
    if sd <= 0 or not np.isfinite(sd):
        decimals = 2
        return round(mean, decimals), round(sd, decimals), decimals
    exponent = int(np.floor(np.log10(sd)))
    leading_digit = int(sd / 10.0 ** exponent)
    sig_figs = 2 if leading_digit == 1 else 1
    decimals = max(0, -(exponent - (sig_figs - 1)))
    return round(mean, decimals), round(sd, decimals), decimals


def format_timing(mean_s: float, sd_s: float) -> str:
    """Format a mean +/- SD timing, switching to ms below 1 s so short steps (ROI
    placement, feature extraction, ...) don't print four leading zeros."""
    if abs(mean_s) < 1.0:
        mean, sd, unit = mean_s * 1000.0, sd_s * 1000.0, "ms"
    else:
        mean, sd, unit = mean_s, sd_s, "s"
    mean_r, sd_r, decimals = round_mean_sd(mean, sd)
    return f"{mean_r:.{decimals}f} ± {sd_r:.{decimals}f} {unit}"


def load_timings(cfg: Config) -> dict:
    path = HERE / cfg.timings_json
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found. Run figures/benchmark_pipeline.py first -- timings are "
            f"never faked or defaulted."
        )
    with open(path) as f:
        return json.load(f)


def variant_mean_sd(timings: dict, step_key: str, variant_key: str) -> tuple[float, float]:
    try:
        variant = timings["steps"][step_key][variant_key]
    except KeyError as exc:
        raise KeyError(
            f"timings.json has no entry for steps.{step_key}.{variant_key}. "
            f"Available steps: {list(timings.get('steps', {}))}"
        ) from exc
    return float(variant["mean_s"]), float(variant["sd_s"])


def resolve_variant_label(
    timings: dict, step_key: str, variant_key: str, label_template: str, count_field: str | None
) -> str:
    """Fill "{n}" in *label_template* from the variant's own JSON data, if requested."""
    if count_field is None:
        return label_template
    variant = timings["steps"][step_key][variant_key]
    if count_field.startswith("len:"):
        n = len(variant[count_field[4:]])
    else:
        n = variant[count_field]
    return label_template.format(n=n)


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------


def build_figure(cfg: Config, panels: dict[str, np.ndarray], timings: dict) -> plt.Figure:
    plt.rcParams["font.family"] = list(cfg.font_family)
    plt.rcParams["mathtext.fontset"] = "stix"  # Times-like, matches the serif family
    plt.rcParams["pdf.fonttype"] = 42  # keep text vector/editable in the PDF
    plt.rcParams["ps.fonttype"] = 42

    n_cols = 3
    content_w_in = cfg.fig_width_in - cfg.left_margin_in - cfg.right_margin_in
    full_panel_w_in = (content_w_in - (n_cols - 1) * cfg.col_gap_in) / n_cols
    panel_w_in = full_panel_w_in * cfg.panel_scale  # smaller panels, same col_gap for arrows
    panel_h_in = panel_w_in  # square panels
    row_w_in = n_cols * panel_w_in + (n_cols - 1) * cfg.col_gap_in
    row_left_in = cfg.left_margin_in + (content_w_in - row_w_in) / 2  # centre the shrunk row

    legend_h_in = cfg.legend_h_in if cfg.show_segmentation_legend else 0.0

    fig_height_in = (
        cfg.top_margin_in
        + cfg.row_title_h_in
        + panel_h_in
        + cfg.row1_timing_h_in
        + cfg.arrow_zone_h_in
        + cfg.row2_title_h_in
        + panel_h_in
        + cfg.row_timing_h_in
        + legend_h_in
        + cfg.bottom_margin_in
    )

    fig = plt.figure(figsize=(cfg.fig_width_in, fig_height_in))

    def frac_x(x_in: float) -> float:
        return x_in / cfg.fig_width_in

    def frac_y(y_in_from_top: float) -> float:
        return 1.0 - y_in_from_top / fig_height_in

    col_left_in = [row_left_in + c * (panel_w_in + cfg.col_gap_in) for c in range(n_cols)]
    col_center_in = [x + panel_w_in / 2 for x in col_left_in]

    row1_title_top_in = cfg.top_margin_in
    row1_panel_top_in = row1_title_top_in + cfg.row_title_h_in
    row1_panel_bottom_in = row1_panel_top_in + panel_h_in
    row1_timing_top_in = row1_panel_bottom_in
    arrow_zone_top_in = row1_timing_top_in + cfg.row1_timing_h_in
    row2_title_top_in = arrow_zone_top_in + cfg.arrow_zone_h_in
    row2_panel_top_in = row2_title_top_in + cfg.row2_title_h_in
    row2_panel_bottom_in = row2_panel_top_in + panel_h_in
    row2_timing_top_in = row2_panel_bottom_in
    legend_top_in = row2_timing_top_in + cfg.row_timing_h_in

    row_panel_top_in = [row1_panel_top_in, row2_panel_top_in]
    row_keys = [
        [cfg.layout[0][0], cfg.layout[0][1], cfg.row1_third],
        [cfg.layout[1][0], cfg.layout[1][1], cfg.row2_third],
    ]
    row_title_top_in = [row1_title_top_in, row2_title_top_in]
    row_title_h_in = [cfg.row_title_h_in, cfg.row2_title_h_in]
    row_timing_top_in = [row1_timing_top_in, row2_timing_top_in]
    row_timing_h_in = [cfg.row1_timing_h_in, cfg.row_timing_h_in]

    for row_idx, keys in enumerate(row_keys):
        for col_idx, key in enumerate(keys):
            ax = fig.add_axes(
                [
                    frac_x(col_left_in[col_idx]),
                    frac_y(row_panel_top_in[row_idx] + panel_h_in),
                    panel_w_in / cfg.fig_width_in,
                    panel_h_in / fig_height_in,
                ]
            )
            ax.imshow(panels[key], aspect="equal")
            ax.set_xticks([])
            ax.set_yticks([])
            if cfg.panel_border:
                for spine in ax.spines.values():
                    spine.set_visible(True)
                    spine.set_color("0.75")
                    spine.set_linewidth(0.5)
            else:
                for spine in ax.spines.values():
                    spine.set_visible(False)

            # title: bold panel letter (via mathtext) + regular title text
            title_y_in = row_title_top_in[row_idx] + row_title_h_in[row_idx] * 0.5
            fig.text(
                frac_x(col_center_in[col_idx]),
                frac_y(title_y_in),
                rf"$\mathbf{{({cfg.letters[key]})}}$ {cfg.titles[key]}",
                ha="center", va="center", fontsize=cfg.title_fontsize,
            )

            # timing text: one line per variant, stacked. Panel (b1, ultrasound) has no
            # variants -> reserved blank slot of the same height, keeps the row aligned.
            variants = cfg.timing_variants.get(key)
            if variants is not None:
                zone_top_in = row_timing_top_in[row_idx]
                for line_idx, (step_key, variant_key, label_template, count_field) in enumerate(variants):
                    mean, sd = variant_mean_sd(timings, step_key, variant_key)
                    label = resolve_variant_label(timings, step_key, variant_key, label_template, count_field)
                    line_y_in = zone_top_in + cfg.timing_line_h_in * (line_idx + 0.5)
                    fig.text(
                        frac_x(col_center_in[col_idx]),
                        frac_y(line_y_in),
                        f"{label}: t = {format_timing(mean, sd)}",
                        ha="center", va="center", fontsize=cfg.timing_fontsize, color="0.15",
                    )

    # --- horizontal arrows: (a)->(b), (b)->(c), (d)->(e), (e)->(f) ---
    for row_idx in range(2):
        mid_y_in = row_panel_top_in[row_idx] + panel_h_in / 2
        for col_idx in range(n_cols - 1):
            x0_in = col_left_in[col_idx] + panel_w_in + cfg.arrow_pad_in
            x1_in = col_left_in[col_idx + 1] - cfg.arrow_pad_in
            arrow = FancyArrowPatch(
                (frac_x(x0_in), frac_y(mid_y_in)),
                (frac_x(x1_in), frac_y(mid_y_in)),
                transform=fig.transFigure,
                arrowstyle="-|>", mutation_scale=cfg.arrow_mutation_scale,
                color=cfg.arrow_color, linewidth=cfg.arrow_linewidth, shrinkA=0, shrinkB=0,
            )
            fig.add_artist(arrow)

    # --- vertical arrow: (c) -> (f), confined to the arrow zone so it never crosses
    # row-1 timing text above it or row-2's panel title below it ---
    col3_x_in = col_center_in[2]
    arrow = FancyArrowPatch(
        (frac_x(col3_x_in), frac_y(arrow_zone_top_in + cfg.arrow_pad_in)),
        (frac_x(col3_x_in), frac_y(arrow_zone_top_in + cfg.arrow_zone_h_in - cfg.arrow_pad_in)),
        transform=fig.transFigure,
        arrowstyle="-|>", mutation_scale=cfg.vertical_arrow_mutation_scale,
        color=cfg.arrow_color, linewidth=cfg.vertical_arrow_linewidth, shrinkA=0, shrinkB=0,
    )
    fig.add_artist(arrow)

    # --- optional segmentation legend, under panel (e) ---
    if cfg.show_segmentation_legend and cfg.class_names:
        seg_col = 1  # panel (e) is the middle column of row 2
        legend_ax = fig.add_axes(
            [
                frac_x(col_left_in[seg_col]),
                frac_y(legend_top_in + legend_h_in),
                panel_w_in / cfg.fig_width_in,
                legend_h_in / fig_height_in,
            ]
        )
        legend_ax.set_xlim(0, 1)
        legend_ax.set_ylim(0, 1)
        legend_ax.axis("off")
        n = len(cfg.class_names)
        for i, (class_id, name) in enumerate(sorted(cfg.class_names.items())):
            x = (i + 0.5) / n
            color = cfg.class_colors.get(class_id, "0.5")
            legend_ax.add_patch(
                plt.Rectangle((x - 0.03, 0.55), 0.06, 0.35, transform=legend_ax.transAxes,
                               facecolor=color, edgecolor="none")
            )
            legend_ax.text(x, 0.15, name, transform=legend_ax.transAxes, ha="center",
                            va="center", fontsize=cfg.timing_fontsize - 1)

    return fig


def main() -> None:
    cfg = CONFIG
    panels = normalize_panels(cfg)
    timings = load_timings(cfg)
    fig = build_figure(cfg, panels, timings)

    pdf_path = HERE / cfg.output_pdf
    png_path = HERE / cfg.output_png
    fig.savefig(pdf_path)
    fig.savefig(png_path, dpi=cfg.png_dpi)
    logger.info("wrote %s and %s", pdf_path, png_path)


if __name__ == "__main__":
    main()
