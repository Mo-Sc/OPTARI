from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile

from patari.utils.setup import archive_user_dir, get_user_config_file, get_user_dir

CONFIG_SCHEMA_VERSION = 5 # adapt in default config.json as well

@dataclass(frozen=True)
class GeneralConfig:
    LOG_LEVEL: str
    GUI_LOG_LEVEL: str
    DEFAULT_PA_LAYER: str
    PA_FALLBACK_SCALE: tuple[float, float, float]
    DEFAULT_US_LAYER: str # not implemented yet
    US_FALLBACK_SCALE: tuple[float, float, float]
    DEFAULT_FRAME_INDEX: int | str # frame index or "motion" for motion-based selection
    DEFAULT_CHANNEL_INDEX: int
    DEFAULT_PLAYBACK_FPS: int
    OPERATOR: str
    ANALYSIS_ID: str
    LAYER_COLOR_MAPS: dict = field(default_factory=dict)
    DEFAULT_VISIBLE_DOCKS: dict = field(default_factory=dict)  # dock label -> 0/1, missing = visible

@dataclass(frozen=True)
class AnnotationConfig:
    roi_colors: list = field(default_factory=list)
    roi_features: dict[str, int] = field(default_factory=dict)
    show_track_id: bool = True  # label shapes "roi_id/track_id" instead of just "roi_id"
    roi_label_size: int = 8

@dataclass(frozen=True)
class AnalysisConfig:
    histogram_bins: int

@dataclass(frozen=True)
class SegmentationConfig:
    default_model: str

@dataclass(frozen=True)
class ExportConfig:
    font_size: int
    cbar_width: int
    padding: int

@dataclass(frozen=True)
class PatariConfig:
    schema_version: int
    general: GeneralConfig
    annotation: AnnotationConfig
    analysis: AnalysisConfig
    segmentation: SegmentationConfig
    export: ExportConfig

    @classmethod
    def load_from_user_dir(cls) -> "PatariConfig":
        """Loads the user's config.json and safely parses it into the dataclasses."""
        config_path = get_user_config_file()
        data = json.loads(config_path.read_text())

        schema_version = data.get("schema_version")

        if schema_version != CONFIG_SCHEMA_VERSION:
            archive_user_dir(get_user_dir())
            config_path = get_user_config_file()
            data = json.loads(config_path.read_text())
        
        return _config_from_dict(data)


def _config_from_dict(data: dict) -> PatariConfig:
    return PatariConfig(
        schema_version=data["schema_version"],
        general=GeneralConfig(**data["general"]),
        annotation=AnnotationConfig(**data["annotation"]),
        analysis=AnalysisConfig(**data["analysis"]),
        segmentation=SegmentationConfig(**data["segmentation"]),
        export=ExportConfig(**data["export"]),
    )


def read_user_config_dict() -> dict:
    """Return the raw contents of the user's config.json."""
    return json.loads(get_user_config_file().read_text(encoding="utf-8"))


def write_user_config_dict(data: dict) -> Path:
    """Validate *data* against the config dataclasses and write it atomically.
    """
    if data.get("schema_version") != CONFIG_SCHEMA_VERSION:
        # A mismatch makes the loader archive the whole user directory on next launch.
        raise ValueError(
            f"Refusing to write config with schema_version {data.get('schema_version')!r}; "
            f"expected {CONFIG_SCHEMA_VERSION}."
        )

    # Constructing the sections also works as validation: the loader is intolerant of missing or
    # unknown keys, so anything it would reject never reaches disk.
    _config_from_dict(data)

    path = get_user_config_file()
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(data, temporary_file, indent=4, ensure_ascii=False)
            temporary_file.write("\n")
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return path
