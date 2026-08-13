from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from patari.utils.presets import PresetStore


@dataclass
class RoiPreset:
    """Serializable ROI geometry and placement metadata."""

    name: str
    description: str
    position: str
    created: str
    shape_type: str
    vertices: list[list[float]]
    source_fov_x_mm: float
    source_fov_y_mm: float

    def __post_init__(self) -> None:
        if self.source_fov_x_mm <= 0 or self.source_fov_y_mm <= 0:
            raise ValueError("ROI preset source FOV must be positive")

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "RoiPreset":
        vertices = [
            [float(vertex[0]), float(vertex[1])]
            for vertex in data.get("vertices", [])
            if isinstance(vertex, (list, tuple)) and len(vertex) >= 2
        ]
        if not vertices:
            raise ValueError(f"ROI preset must contain vertices: {name}")

        return cls(
            name=name,
            description=str(data.get("description", "")),
            position=str(data.get("position", "undefined")),
            created=str(data.get("created", "")),
            shape_type=str(data.get("shape_type", "polygon")),
            vertices=vertices,
            source_fov_x_mm=float(data["source_fov_x_mm"]),
            source_fov_y_mm=float(data["source_fov_y_mm"]),
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("name")
        return data


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
        position: str,
        shape_type: str,
        vertices: list[list[float]],
        source_fov_x_mm: float,
        source_fov_y_mm: float,
    ) -> Path:
        created = datetime.now(UTC).isoformat()
        preset = RoiPreset(
            name=name,
            description=description,
            position=position,
            created=created,
            shape_type=shape_type,
            vertices=vertices,
            source_fov_x_mm=source_fov_x_mm,
            source_fov_y_mm=source_fov_y_mm,
        )
        return self.save(name, preset.to_dict())