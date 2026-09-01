import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import requests

from patari.config import settings

DOWNLOAD_TIMEOUT_S = 10
DOWNLOAD_CHUNK_BYTES = 512 * 1024


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


def roi_color_for_index(index: int) -> str:
    """Return the configured display color for a given roi index."""
    roi_colors = settings.annotation.roi_colors
    return roi_colors[int(index) % len(roi_colors)]


def open_download(url: str | None, dest_name: str) -> tuple[requests.Response, int]:
    """Open a streaming GET and return ``(response, total_size)`` without reading the body.

    Called on the main thread so the size is known before the transfer is handed to a worker.
    Necessary to get the total donwload size for a progress bar
    """
    if not url:
        raise FileNotFoundError(f"{dest_name} not found and no download URL provided.")

    response = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_S)
    response.raise_for_status()
    return response, int(response.headers.get("content-length", 0))


def download_chunks(response: requests.Response, dest_path: Path) -> Iterator[int]:
    """Stream *response* to *dest_path*, yielding the bytes written per chunk.

    Runs in a worker thread, pair with `open_download` on the main thread. Writes to a
    scratch file and only moves it into place once complete, so a cancelled or failed
    download can never leave a corrupt file at the real destination.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest_path.parent, prefix=f"{dest_path.name}.", suffix=".part")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                if chunk:
                    f.write(chunk)
                    yield len(chunk)
        tmp_path.replace(dest_path)
    finally:
        response.close()
        tmp_path.unlink(missing_ok=True)
