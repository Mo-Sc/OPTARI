"""ROI presets: reusable templates stored as JSON under ``presets/roi/``.

A preset pairs a named ``RoiGeometry`` with the ``source_fov_m`` it was drawn at and
a description. It carries no identifier, so placing it creates a fresh ROI each time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from optari.roi.roi_geometry import RoiGeometry
from optari.utils.presets import PresetStore

PLACEMENT_MODES = ("static", "auto")


@dataclass
class RoiPreset:
    """A named, reusable ROI template.

    The shape itself is a :class:`RoiGeometry`, the same FOV-independent
    representation used by the saved analysis table and HDF5 export.
    ``source_fov_m`` is kept so it can be re-placed proportionally
    in a scan with a different fov.

    ``placement`` is how the ROI wants to be positioned: ``static`` at its saved
    coordinates, or ``auto`` anchored onto the segmentation class named by
    ``geometry.tissue_class``. It lives here rather than at each call site so that
    placing a preset means the same thing in the dock and in a batch run.
    """

    name: str
    description: str
    created: str
    geometry: RoiGeometry
    source_fov_m: tuple[float, float]
    placement: str = "static"

    def __post_init__(self) -> None:
        """Coerce *source_fov_m* to floats and reject a non-positive FOV or unknown *placement*."""
        self.source_fov_m = (
            float(self.source_fov_m[0]),
            float(self.source_fov_m[1]),
        )
        if min(self.source_fov_m) <= 0:
            raise ValueError("ROI preset source FOV must be positive")
        if self.placement not in PLACEMENT_MODES:
            raise ValueError(
                f"ROI preset placement must be one of {PLACEMENT_MODES}: {self.placement}"
            )

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "RoiPreset":
        """Rebuild from a preset file's dict. Raises if ``source_fov_m`` is missing."""
        if "source_fov_m" not in data:
            raise ValueError(f"ROI preset must record its source FOV: {name}")
        return cls(
            name=name,
            description=str(data.get("description", "")),
            created=str(data.get("created", "")),
            geometry=RoiGeometry.from_dict(data.get("geometry", {})),
            source_fov_m=data["source_fov_m"],
            placement=str(data.get("placement", "static")),
        )

    def to_dict(self) -> dict:
        """Serialize to the dict written to the preset's JSON file."""
        return {
            "description": self.description,
            "created": self.created,
            "source_fov_m": list(self.source_fov_m),
            "placement": self.placement,
            "geometry": self.geometry.to_dict(),
        }


class RoiPresetStore(PresetStore):
    """Load and save named ROI presets in the user preset directory."""

    def list_presets(self) -> list[RoiPreset]:
        """Load every saved preset."""
        return [
            RoiPreset.from_dict(path.stem, self.load(path))
            for path in self.list_paths()
        ]

    def get(self, name: str) -> RoiPreset:
        """Load the preset named *name*."""
        return RoiPreset.from_dict(name, self.load(name))

    def save_preset(
        self,
        *,
        name: str,
        description: str,
        geometry: RoiGeometry,
        source_fov_m: tuple[float, float],
        placement: str = "static",
    ) -> Path:
        """Build a preset from the given fields, stamp it with the current time, and save it to disk."""
        preset = RoiPreset(
            name=name,
            description=description,
            created=datetime.now(UTC).isoformat(),
            geometry=geometry,
            source_fov_m=source_fov_m,
            placement=placement,
        )
        return self.save(name, preset.to_dict())
