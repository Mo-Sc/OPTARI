from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from patari.roi.roi_geometry import RoiGeometry
from patari.utils.presets import PresetStore


@dataclass
class RoiPreset:
    """A named, reusable ROI template.

    The shape itself is a :class:`RoiGeometry`, the same FOV-independent
    representation used by the saved analysis table and HDF5 export.
    ``source_fov_m`` is kept so it can be re-placed proportionally
    in a scan with a different fov.
    """

    name: str
    description: str
    created: str
    geometry: RoiGeometry
    source_fov_m: tuple[float, float]

    def __post_init__(self) -> None:
        self.source_fov_m = (float(self.source_fov_m[0]), float(self.source_fov_m[1]))
        if min(self.source_fov_m) <= 0:
            raise ValueError("ROI preset source FOV must be positive")

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "RoiPreset":
        if "source_fov_m" not in data:
            raise ValueError(f"ROI preset must record its source FOV: {name}")
        return cls(
            name=name,
            description=str(data.get("description", "")),
            created=str(data.get("created", "")),
            geometry=RoiGeometry.from_dict(data.get("geometry", {})),
            source_fov_m=data["source_fov_m"],
        )

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "created": self.created,
            "source_fov_m": list(self.source_fov_m),
            "geometry": self.geometry.to_dict(),
        }


class RoiPresetStore(PresetStore):
    """Load and save named ROI presets in the user preset directory."""

    def list_presets(self) -> list[RoiPreset]:
        return [
            RoiPreset.from_dict(path.stem, self.load(path))
            for path in self.list_paths()
        ]

    def get(self, name: str) -> RoiPreset:
        return RoiPreset.from_dict(name, self.load(name))

    def save_preset(
        self,
        *,
        name: str,
        description: str,
        geometry: RoiGeometry,
        source_fov_m: tuple[float, float],
    ) -> Path:
        preset = RoiPreset(
            name=name,
            description=description,
            created=datetime.now(UTC).isoformat(),
            geometry=geometry,
            source_fov_m=source_fov_m,
        )
        return self.save(name, preset.to_dict())