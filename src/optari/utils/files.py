"""Writing files so that a failed write never leaves a half-written file behind."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_destination(path: Path) -> Iterator[Path]:
    """Yield a temporary path next to *path*, moved onto it only if the block succeeds.

    *path* then holds either its previous content or the complete new one. The
    temporary file keeps *path*'s suffix, since some writers (pandas' ExcelWriter)
    pick their format from it.
    """
    temporary = path.with_name(f".{path.stem}.tmp{path.suffix}")
    # A leftover from an earlier crash must not be appended to (PATATO opens with "a").
    temporary.unlink(missing_ok=True)
    try:
        yield temporary
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
