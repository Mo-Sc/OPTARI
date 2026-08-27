from dataclasses import dataclass, field
import json

from patari.utils.setup import archive_user_dir, get_user_config_file, get_user_dir

CONFIG_SCHEMA_VERSION = 3 # adapt in default config.json as well

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
    OPERATOR: str # recorded in the file_origin attribute of exported HDF5 files
    LAYER_COLOR_MAPS: dict = field(default_factory=dict)

@dataclass(frozen=True)
class AnnotationConfig:
    roi_colors: list = field(default_factory=list)
    roi_features: dict[str, int] = field(default_factory=dict)

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
        
        return cls(
            schema_version=data["schema_version"],
            general=GeneralConfig(**data["general"]),
            annotation=AnnotationConfig(**data["annotation"]),
            analysis=AnalysisConfig(**data["analysis"]),
            segmentation=SegmentationConfig(**data["segmentation"]),
            export=ExportConfig(**data["export"])
        )