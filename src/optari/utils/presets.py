from __future__ import annotations

import json
from pathlib import Path

from optari.utils.files import atomic_destination


def normalize_preset_name(name: str) -> str:
    """Return a safe preset stem or raise for path-like names."""
    name = str(name).strip()
    if name.lower().endswith(".json"):
        name = name[:-5].rstrip()
    if (
        not name
        or name in {".", ".."}
        or Path(name).name != name
        or "\\" in name
    ):
        raise ValueError("Preset name must be a single file name.")
    return name


class PresetStore:
    """Store JSON presets in one directory."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def list_paths(self) -> list[Path]:
        return sorted(self.directory.glob("*.json"))

    def path_for(self, name: str) -> Path:
        return self.directory / f"{normalize_preset_name(name)}.json"

    def load(self, preset: str | Path) -> dict:
        path = Path(preset)
        if path.suffix.lower() != ".json":
            path = self.path_for(str(preset))
        if not path.exists():
            raise FileNotFoundError(f"Preset not found: {path.name}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON in {path.name}: {exc.msg}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(f"Preset must contain a JSON object: {path.name}")
        return data

    def save(
        self,
        name: str,
        data: dict,
        *,
        overwrite: bool = False,
    ) -> Path:
        if not isinstance(data, dict):
            raise ValueError("Preset data must be a JSON object.")

        path = self.path_for(name)
        self.directory.mkdir(parents=True, exist_ok=True)
        if path.exists() and not overwrite:
            raise ValueError(f"Preset already exists: {path.stem}")

        with atomic_destination(path) as temporary:
            temporary.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return path

    def delete(self, preset: str | Path) -> bool:
        path = Path(preset)
        if path.suffix.lower() != ".json":
            path = self.path_for(str(preset))
        if not path.exists():
            return False
        path.unlink()
        return True
