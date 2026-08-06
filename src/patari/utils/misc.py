import requests
from pathlib import Path
from napari.utils import progress

from patari.config import settings

def parse_float_input(text: str) -> float | None:
    """
    Parse a float from text input. Returns None if parsing fails or input is
    empty.
    """
    t = (text or "").strip()
    if t == "":
        return None
    try:
        return float(t.replace(",", "."))
    except Exception:
        return None


def roi_color_for_index(roi_index: int) -> str:
    """Return the configured display color for a given ROI index."""
    roi_colors = settings.annotation.roi_colors
    return roi_colors[int(roi_index) % len(roi_colors)]

    

def download_file(url: str, dest_path: Path) -> None:
    """Downloads a file using napari progress bar. Raises an exception if download fails."""

    # check if destination directory exists, if not, create it
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    response = requests.get(url, stream=True)
    response.raise_for_status()

    total_size = int(response.headers.get('content-length', 0))
    # write to temp file first, rename later to avoid partial files on failure    
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")

    from napari import current_viewer

    viewer = current_viewer()
    # deprecated private API access, however currently only way to force the activity dock to open
    # https://github.com/napari/napari/issues/4598
    viewer.window._status_bar._toggle_activity_dock(True)

    # use native Napari progress loop
    with progress(total=total_size, desc=f"Downloading {dest_path.name}") as pbr:
        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=512 * 1024): # 512KB chunks
                if chunk:
                    f.write(chunk)
                    pbr.update(len(chunk))
    tmp_path.rename(dest_path)

    viewer.window._status_bar._toggle_activity_dock(False)