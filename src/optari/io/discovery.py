"""Finding studies and scans on disk. Headless: no Qt, no napari, no viewer."""

from __future__ import annotations

import logging
import re
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import h5py
from patato.io.attribute_tags import HDF5Tags, IPASCTags
from patato.io.hdf.hdf5_reader_factory import get_hdf5_reader

logger = logging.getLogger(__name__)

# Both are offered by the save dialog, so both must be found again.
HDF5_SUFFIXES = (".hdf5", ".h5")


@dataclass(frozen=True)
class ScanInfo:
    """Metadata for a discovered scan."""

    kind: str  # "hdf5", "ipasc", "ithera"
    internal_name: str | None


def scan_key(scan_path: Path) -> str:
    """Return the ``Scan_<n>`` prefix of *scan_path*'s name, or the full name if it doesn't match."""
    name = scan_path.stem if scan_path.is_file() else scan_path.name
    m = re.match(r"^(Scan_\d+)", name)
    return m.group(1) if m else name


def scan_sort_key(scan_path: Path):
    """Sort key that orders ``Scan_<n>`` names numerically, ahead of any other name sorted alphabetically.

    Files sharing a ``Scan_<n>`` prefix (an export, its IPASC copy) sort by full name.
    """
    key = scan_key(scan_path)
    m = re.match(r"^Scan_(\d+)$", key)
    if m:
        return (0, int(m.group(1)), scan_path.name)
    return (1, 0, scan_path.name)


def scan_type(path: Path) -> str | None:
    """
    Identify the format of a scan on disk, or ``None`` if the path is not a scan.
    """
    if path.is_dir():
        return "ithera" if any(path.glob("*.msot")) else None
    if path.suffix.lower() not in HDF5_SUFFIXES:
        return None
    try:
        with h5py.File(path, "r") as file:
            if IPASCTags.BINARY_DATA in file:
                return "ipasc"
            if HDF5Tags.RAW_DATA in file:
                return "hdf5"
    except OSError:
        logger.debug("could not open '%s' as HDF5", path, exc_info=True)
    return None


def _read_internal_scan_name(path: Path, kind: str) -> str | None:
    """
    Read the name the scanner gave the scan, or ``None`` if the format has none.
    Tries to avoid reading the whole scan into memory.
    """
    if kind == "ipasc":
        return None

    try:
        if kind == "ithera":
            # Stream the XML and stop at the scan's name
            # Not f"{path.name}.msot": a renamed scan folder keeps its old .msot name.
            msot = next(path.glob("*.msot"))
            in_scan_node = False
            for event, element in ElementTree.iterparse(
                msot, events=("start", "end")
            ):
                if event == "start" and element.tag == "ScanNode":
                    in_scan_node = True
                elif event == "end" and in_scan_node and element.tag == "Name":
                    return (element.text or "").strip() or None
        else:
            # An open read-only handle would block a later save into this file.
            with closing(get_hdf5_reader(str(path))) as reader:
                name = reader.get_scan_name()
            return str(name) if name else None
    except Exception:
        logger.debug(
            "failed to read internal scan name from '%s'",
            path,
            exc_info=True,
        )
    return None


def discover_studies(
    root: Path, max_depth: int = 3
) -> dict[Path, dict[Path, ScanInfo]]:
    """Map each study folder under *root* to its scans, in folder-name order.

    A study is simply any folder that holds at least one scan, so a flat folder
    of scans comes back as a single study and no naming convention is imposed
    beyond the ``Scan_*`` one ``discover_scans`` already relies on. A folder that
    is itself a study is not descended into.
    """
    studies: dict[Path, dict[Path, ScanInfo]] = {}

    def walk(folder: Path, depth: int) -> None:
        """Recurse into *folder* up to *max_depth*, stopping at the first folder that holds a scan."""
        scans = discover_scans(folder)
        if scans:
            studies[folder] = scans
            return
        if depth >= max_depth:
            return
        try:
            children = sorted(
                child
                for child in folder.iterdir()
                # Following symlinks here risks walking a cycle or wandering
                # outside the dataset the user picked.
                if child.is_dir() and not child.is_symlink()
            )
        except OSError:
            logger.warning("could not list '%s', skipping", folder)
            return
        for child in children:
            walk(child, depth + 1)

    walk(Path(root), 0)
    return studies


def discover_scans(folder: Path) -> dict[Path, ScanInfo]:
    """Find every scan directly under *folder*, keyed by path, in ``scan_sort_key`` order.

    Every HDF5 file is listed, also several sharing one ``Scan_<n>`` prefix: an
    OPTARI export, an IPASC export and a copy hold different data. An iThera folder
    is the raw form of a scan, so it is hidden once an HDF5 file with its prefix exists.
    """
    scans: dict[Path, ScanInfo] = {}
    for path in folder.iterdir():
        if path.is_dir():
            continue
        kind = scan_type(path)
        if kind is not None:
            scans[path] = ScanInfo(kind, _read_internal_scan_name(path, kind))

    converted = {scan_key(path) for path in scans}
    for path in folder.glob("Scan_*"):
        if not path.is_dir() or scan_key(path) in converted:
            continue
        kind = scan_type(path)
        if kind is not None:
            scans[path] = ScanInfo(kind, _read_internal_scan_name(path, kind))

    return dict(sorted(scans.items(), key=lambda item: scan_sort_key(item[0])))
