DEFAULT_WAV_START_IDX = 0
DEFAULT_FRAME_START_IDX = 0

dtype_map = {
    "roi_index": int,
    "source_layer": str,
    "roi_type": str,
    "frame": int,
    "wavelength": int,
    "n_pixels": int,
    "area_mm2": float,
    "mean": float,
    "median": float,
    "std": float,
    "min": float,
    "max": float,
}

# TODO: better color maps
roi_colors = [
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
