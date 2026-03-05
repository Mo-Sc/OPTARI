DEFAULT_WAV_START_IDX = 0
DEFAULT_FRAME_START_IDX = 0
ROI_LABELS = True
DEFAULT_PA_LAYER = "Recon: iThera BP-40mm(res:100μm)_0"

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
    "timestamp": str,
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


# ROI placement presets (used by Annotation dock preset buttons).
# Each preset defines a single ROI placement configuration.
ROI_PLACEMENT_PRESETS = [
    {
        "name": "Skin",
        "segmentation_class": "Haut",
        "roi_type": "ellipse",
        "width_mm": 5.0,
        "height_mm": 1.0,
        "depth_mm": 0.0,
    },
    {
        "name": "Fat",
        "segmentation_class": "fat",
        "roi_type": "ellipse",
        "width_mm": 3.0,
        "height_mm": 1.5,
        "depth_mm": 0.5,
    },
    {
        "name": "Muscle",
        "segmentation_class": "Muskel1",
        "roi_type": "ellipse",
        "width_mm": 7.0,
        "height_mm": 2.0,
        "depth_mm": 0.0,
    },
]
