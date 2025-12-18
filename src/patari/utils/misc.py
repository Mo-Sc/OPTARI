from patari.config import roi_colors


def parse_float_input(text: str) -> float | None:
    """
    Parse a float from text input. Returns None if parsing fails or input is
    empty.
    """
    t = (text or "").strip()
    if t == "":
        return None
    try:
        return float(t)
    except Exception:
        return None


def roi_color_for_index(roi_index: int) -> str:
    """Return the configured display color for a given ROI index."""
    if not roi_colors:
        return "#aa0000ff"
    try:
        idx = int(roi_index)
    except Exception:
        idx = 0
    return roi_colors[idx % len(roi_colors)]
