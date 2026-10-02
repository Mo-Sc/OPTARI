"""Finding studies and scans on disk. Headless: no Qt, no napari, no viewer."""

from __future__ import annotations

import logging
import re
import xml.dom.minidom
from dataclasses import dataclass
from pathlib import Path

import h5py
from patato.io.attribute_tags import HDF5Tags, IPASCTags
from patato.io.hdf.hdf5_reader_factory import get_hdf5_reader

logger = logging.getLogger(__name__)


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
    """Sort key that orders ``Scan_<n>`` names numerically, ahead of any other name sorted alphabetically."""
    key = scan_key(scan_path)
    m = re.match(r"^Scan_(\d+)$", key)
    if m:
        return (0, int(m.group(1)), key)
    return (1, 0, key)


def scan_type(path: Path) -> str | None:
    """
    Identify the format of a scan on disk, or ``None`` if the path is not a scan.
    """
    if path.is_dir():
        return "ithera" if any(path.glob("*.msot")) else None
    if path.suffix.lower() != ".hdf5":
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
            # Parse only the relevant XML node rather than the whole scan.
            msot = path / f"{path.name}.msot"
            tree = xml.dom.minidom.parse(str(msot))
            scan_nodes = tree.getElementsByTagName("ScanNode")
            if scan_nodes:
                name_nodes = scan_nodes[0].getElementsByTagName("Name")
                if name_nodes and name_nodes[0].firstChild:
                    return name_nodes[0].firstChild.nodeValue.strip()
        else:
            reader = get_hdf5_reader(str(path))
            name = reader.get_scan_name()
            reader.close()
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
        except (PermissionError, OSError):
            logger.warning("could not list '%s', skipping", folder)
            return
        for child in children:
            walk(child, depth + 1)

    walk(Path(root), 0)
    return studies


def discover_scans(folder: Path) -> dict[Path, ScanInfo]:
    """Find every scan directly under *folder*, keyed by path and deduplicated by ``scan_key``.

    When both an HDF5 file and an iThera folder resolve to the same key, the HDF5
    one wins.
    """
    by_key: dict[str, tuple[Path, ScanInfo]] = {}
    for path in sorted(folder.glob("*.hdf5")):
        kind = scan_type(path)
        if kind is not None:
            info = ScanInfo(kind, _read_internal_scan_name(path, kind))
            by_key[scan_key(path)] = (path, info)

    # An iThera folder only counts if no HDF5 file holds the same scan.
    for path in folder.glob("Scan_*"):
        key = scan_key(path)
        kind = scan_type(path)
        if kind is not None and key not in by_key:
            info = ScanInfo(kind, _read_internal_scan_name(path, kind))
            by_key[key] = (path, info)

    return dict(
        sorted(by_key.values(), key=lambda item: scan_sort_key(item[0]))
    )
