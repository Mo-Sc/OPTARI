MAX_ROIS = 10
DEFAULT_PA_LAYER = "Recon: iThera BP-40mm(res:100μm)_0"
DEFAULT_US_LAYER = ""
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_GUI_LOG_LEVEL = "WARNING"

dtype_map = {
    "roi_index": int,
    "source_layer": str,
    "roi_type": str,
    "scan_id": str,
    "frame": int,
    "channel": object,
    "mean": float,
    "median": float,
    "std": float,
    "p10": float,
    "p90": float,
    "min": float,
    "max": float,
    "n_pixels": int,
    "area_mm2": float,
    "timestamp": str,
    "filepath": str,
}

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
