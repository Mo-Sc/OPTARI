from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass
class RoiLibraryEntry:
    id: str
    description: str
    position: str
    created: str
    shape_type: str
    vertices: list[list[float]]
    source_fov_x_mm: float | None
    source_fov_y_mm: float | None


class RoiLibrary:
    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)
        self._entries: list[RoiLibraryEntry] = []

    def load(self) -> None:
        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception(
                "failed to load ROI library from %s", self.file_path
            )
            self._entries = []
            return

        entries = []
        for row in (
            payload.get("rois", []) if isinstance(payload, dict) else []
        ):
            if not isinstance(row, dict) or not (
                roi_id := str(row.get("id", "")).strip()
            ):
                continue
            vertices = [
                [float(v[0]), float(v[1])]
                for v in row.get("vertices", [])
                if isinstance(v, (list, tuple)) and len(v) >= 2
            ]
            entries.append(
                RoiLibraryEntry(
                    id=roi_id,
                    description=str(row.get("description", "")),
                    position=str(row.get("position", "undefined")),
                    created=str(row.get("created", "")),
                    shape_type=str(row.get("shape_type", "polygon")),
                    vertices=vertices,
                    source_fov_x_mm=(
                        float(x)
                        if (x := row.get("source_fov_x_mm")) is not None
                        else None
                    ),
                    source_fov_y_mm=(
                        float(y)
                        if (y := row.get("source_fov_y_mm")) is not None
                        else None
                    ),
                )
            )
        self._entries = entries

    def save(self) -> None:
        payload = {
            "version": "1.0",
            "rois": [asdict(e) for e in self._entries],
        }
        self.file_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def list_ids(self) -> list[str]:
        return [e.id for e in self._entries]

    def get_by_id(self, roi_id: str) -> RoiLibraryEntry | None:
        for entry in self._entries:
            if entry.id == roi_id:
                return entry
        return None

    def add_or_update(
        self,
        *,
        roi_id: str,
        description: str,
        position: str,
        shape_type: str,
        vertices: list[list[float]],
        source_fov_x_mm: float | None,
        source_fov_y_mm: float | None,
    ) -> None:
        created = datetime.now(UTC).isoformat()
        new_entry = RoiLibraryEntry(
            id=roi_id,
            description=description,
            position=position,
            created=created,
            shape_type=shape_type,
            vertices=vertices,
            source_fov_x_mm=source_fov_x_mm,
            source_fov_y_mm=source_fov_y_mm,
        )

        for i, entry in enumerate(self._entries):
            if entry.id == roi_id:
                self._entries[i] = new_entry
                return
        self._entries.append(new_entry)

    def remove(self, roi_id: str) -> bool:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != roi_id]
        return len(self._entries) != before
