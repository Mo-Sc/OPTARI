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
        ("Application metadata", dict(layer.metadata)),
    ]
    return [
        (label, _format(value), _format(value, details=True))
        for label, value in rows
    ]


def clinical_metadata_rows(metadata) -> list[tuple[str, str, str]]:

    # just for debugging: dummy metadata
    # TODO: remove this once clinical metadata is available
    metadata = {
        "Patient ID": "12345",
        "Patient Name": "John Doe",
        "Patient Age": 45,
        "Patient Sex": "Male",
        "Patient Weight": 80.5,
        "Patient Height": 180.0,
        "Clinical Notes": "This is a test note.",
    }
    if not metadata:
        return [
            (
                "Status",
                "No clinical metadata available",
                "No clinical metadata available",
            )
        ]
    return [
        (str(label), _format(value), _format(value, details=True))
        for label, value in metadata.items()
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
        ("Acquisition date", pa_data.get_scan_datetime()),
        ("Clinical scan", pa_data.is_clinical()),
        ("Acquisition shape", getattr(pa_data, "shape", None)),
        ("Wavelengths", np.asarray(pa_data.get_wavelengths())),
        ("Sampling frequency", pa_data.get_sampling_frequency()),
        ("Time samples", pa_data.get_n_samples()),
        ("Speed of sound", pa_data.get_speed_of_sound()),
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
