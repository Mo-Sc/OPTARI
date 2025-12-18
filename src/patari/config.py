DEFAULT_WAV_START_IDX = 0
DEFAULT_FRAME_START_IDX = 0
ROI_LABELS = True

dtype_map = {
    "roi_index": int,
    "source_layer": str,
    "roi_type": str,
    "scan_id": str,
    "frame": int,
    "wavelength": int,
    "mean": float,
    "median": float,
    "std": float,
    "min": float,
    "max": float,
    "n_pixels": int,
    "area_mm2": float,
    "filepath": str,
}

# TODO: better color maps
roi_colors_ordered = [
    "#8B0000",
    "#B22222",
    "#DC143C",
    "#FF4500",
    "#FF6347",
    "#FF7F50",
    "#FF8C00",
    "#FFA500",
    "#FFD700",
    "#FFFF00",
]
roi_colors = [
    "#8B0000",
    "#FFD700",
    "#FF6347",
    "#FF8C00",
    "#B22222",
    "#FFFF00",
    "#DC143C",
    "#FF4500",
    "#FFA500",
    "#FF7F50",
]
