from dataclasses import dataclass, field
import json

from patari.utils.setup import get_user_config_file

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
    LAYER_COLOR_MAPS: dict = field(default_factory=dict)

@dataclass(frozen=True)
class AnnotationConfig:
    max_rois: int
    roi_colors: list = field(default_factory=list)
    roi_features: dict[str, int] = field(default_factory=dict)

@dataclass(frozen=True)
class AnalysisConfig:
    histogram_bins: int

@dataclass(frozen=True)
class SegmentationConfig:
    default_model: str

@dataclass(frozen=True)
class PatariConfig:
    general: GeneralConfig
    annotation: AnnotationConfig
    analysis: AnalysisConfig
    segmentation: SegmentationConfig

    @classmethod
    def load_from_user_dir(cls) -> "PatariConfig":
        """Loads the user's config.json and safely parses it into the dataclasses."""
        config_path = get_user_config_file()
        data = json.loads(config_path.read_text())
        
        return cls(
            general=GeneralConfig(**data["general"]),
            annotation=AnnotationConfig(**data["annotation"]),
            analysis=AnalysisConfig(**data["analysis"]),
            segmentation=SegmentationConfig(**data["segmentation"])
        )