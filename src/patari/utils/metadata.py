"""Formatting helpers for layer and scan metadata views."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from numbers import Number
from pathlib import Path

import numpy as np


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _format(value, details: bool = False) -> str:
    """
    Format a value for display in the metadata table.
    str and numbers are displayed directly, arrays etc are summarized.
    """
    if value is None:
        return "N/A"
    if isinstance(value, (str, Number, date, time, np.generic, Path)):
        return str(value)
    if isinstance(value, np.ndarray):
        return (
            np.array2string(value, threshold=np.inf, separator=", ")
            if details
            else f"ndarray, shape={value.shape}"
        )
    if isinstance(value, dict):
        if not details:
            return f"dict, size={len(value)}"
        return json.dumps(value, indent=2, default=_json_default)
    if isinstance(value, (list, tuple)):
        if not details:
            return f"{type(value).__name__}, size={len(value)}"
        return json.dumps(value, indent=2, default=_json_default)
    return type(value).__name__


def layer_metadata_rows(layer) -> list[tuple[str, str, str]]:
    """
    layer infos
    """
    if layer is None:
        return [("Status", "No image layer selected", "No image layer selected")]

    rows = [
        ("Name", layer.name),
        ("Layer type", type(layer).__name__),
        ("Shape", tuple(layer.data.shape)),
        ("Dtype", layer.data.dtype),
        ("Scale", tuple(layer.scale)),
        ("Translate", tuple(layer.translate)),
        ("Units", layer.units),
        ("Visible", layer.visible),
        ("Opacity", layer.opacity),
        ("Blending", layer.blending),
        ("Colormap", layer.colormap.name),
        ("Contrast limits", tuple(layer.contrast_limits)),
        ("Layer-specific metadata", dict(layer.metadata)),
    ]
    return [
        (label, _format(value), _format(value, details=True))
        for label, value in rows
    ]


def scan_metadata_rows(
    pa_data,
    scan_path: Path | None = None,
    study_path: Path | None = None,
    scan_info=None,
) -> list[tuple[str, str, str]]:
    """
    global scan infos, including acquisition parameters and scan geometry.
    """
    if pa_data is None:
        return [("Status", "No scan loaded", "No scan loaded")]

    rows = [
        ("Study folder", study_path.stem if study_path else "N/A"),
        ("Scan path", scan_path),
        ("Scan name", pa_data.get_scan_name()),
        ("Internal name", getattr(scan_info, "internal_name", None)),
        ("File origin", pa_data.get_file_origin()),
        ("Acquisition date", pa_data.get_scan_datetime()),
        ("Device info", pa_data.get_device_info()),
        ("Clinical scan", pa_data.is_clinical()),
        ("Acquisition shape", getattr(pa_data, "shape", None)),
        ("Wavelengths", np.asarray(pa_data.get_wavelengths())),
        ("Sampling frequency", pa_data.get_sampling_frequency()),
        ("Time samples", pa_data.get_n_samples()),
        ("Speed of sound US (m/s)", pa_data.get_speed_of_sound()),
        ("Overall correction factor", np.asarray(pa_data.get_overall_correction_factor())),
        ("Impulse response", np.asarray(pa_data.get_impulse_response())),
        ("Scan geometry (m)", np.asarray(pa_data.get_scan_geometry())),
        ("Z positions (m)", np.asarray(pa_data.get_z_positions())),
        ("Timestamps (s)", np.asarray(pa_data.get_timestamps())),
    ]
    return [
        (label, _format(value), _format(value, details=True))
        for label, value in rows
    ]


def ipasc_metadata_rows(pa_data) -> list[tuple[str, str, str]]:
    """
    Scan metadata under the IPASC tag names, in IPASC SI units.

    These are the same values PATARI writes into the ``meta_data`` group on export, built by
    the custom PATATO fork. Fields IPASC marks as minimal
    are flagged, and fields the scan does not provide are listed as absent.
    """
    if pa_data is None:
        return [("Status", "No scan loaded", "No scan loaded")]

    from patato.io.ipasc.metadata_mapping import describe_ipasc_metadata

    entries = describe_ipasc_metadata(pa_data.scan_reader)
    minimal = [e for e in entries if e["minimal"]]
    missing = [e["tag"] for e in minimal if not e["present"]]
    status = (
        f"{len(minimal) - len(missing)}/{len(minimal)} minimal fields present"
        f" (minimal fields marked *)"
    )
    rows = [
        (
            "IPASC completeness",
            status,
            status if not missing else status + "\nMissing: " + ", ".join(missing),
        )
    ]
    for entry in entries:
        label = entry["tag"] + (" *" if entry["minimal"] else "")
        unit = "" if entry["unit"] in ("N/A", None) else f" [{entry['unit']}]"
        summary = "absent" if not entry["present"] else _format(entry["value"]) + unit
        rows.append((label, summary, _format(entry["value"], details=True)))
    return rows
