from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class SegmentationResult:
    """Result of segmenting a single 2D US frame.

    seg:
        (H, W) integer class id map.
    class_names:
        Mapping of class id -> display name.
    """

    seg: np.ndarray
    class_names: dict[int, str]


@dataclass(frozen=True)
class SegmentationModelConfig:
    """Segmentation model configuration loaded from a JSON registry."""

    model_id: str
    display_name: str
    class_names: dict[int, str]
    onnx_path: Path
    input_name: str
    output_name: str
    input_height: int
    input_width: int


DEFAULT_MODELS_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "segmentation_models.json"
)


def load_onnx_model_registry(
    config_path: Path | None = None,
) -> tuple[str, dict[str, SegmentationModelConfig]]:
    """Load ONNX model configs and return the default model id plus registry."""
    path = (
        Path(config_path) if config_path is not None else DEFAULT_MODELS_CONFIG
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    base_dir = path.parent

    models: dict[str, SegmentationModelConfig] = {}
    for item in raw["models"]:
        class_names = {
            int(class_id): str(name)
            for class_id, name in item["class_names"].items()
        }

        model_path = Path(item["onnx_path"])
        if not model_path.is_absolute():
            model_path = (base_dir / model_path).resolve()

        config = SegmentationModelConfig(
            model_id=str(item["id"]),
            display_name=str(item["display_name"]),
            class_names=class_names,
            onnx_path=model_path,
            input_name=str(item["input_name"]),
            output_name=str(item["output_name"]),
            input_height=int(item["input_height"]),
            input_width=int(item["input_width"]),
        )
        models[config.model_id] = config

    default_model_id = str(raw["default_model"])
    if default_model_id not in models:
        raise ValueError(
            f"Unknown default model '{default_model_id}' in {path}"
        )

    return default_model_id, models


class OnnxSegmenter:
    """Single-model segmenter.

    The real ONNX inference is temporarily replaced by a deterministic dummy
    mask generator so the widget can be exercised without a trained model.
    """

    def __init__(self, model: SegmentationModelConfig) -> None:
        self.model = model
        self.class_names = dict(model.class_names)

    def predict(self, us_2d: np.ndarray) -> SegmentationResult:
        """Return a deterministic class-id map for one 2D US frame."""
        us_2d = np.asarray(us_2d)
        if us_2d.ndim != 2:
            raise ValueError(f"Expected 2D US frame, got shape {us_2d.shape}")

        h, w = us_2d.shape
        if h <= 0 or w <= 0:
            raise ValueError("Expected non-empty US frame")

        class_ids = sorted(int(class_id) for class_id in self.class_names)
        seg = np.zeros((h, w), dtype=np.int32)

        if len(class_ids) == 1:
            seg[:, :] = class_ids[0]
        else:
            edges = np.linspace(0, h, num=len(class_ids) + 1, dtype=int)
            for i, class_id in enumerate(class_ids):
                y0 = int(edges[i])
                y1 = int(edges[i + 1])
                if y1 > y0:
                    seg[y0:y1, :] = class_id

            for i, class_id in enumerate(class_ids):
                seg[min(i, h - 1), 0] = class_id

        return SegmentationResult(seg=seg, class_names=dict(self.class_names))


def create_segmenter(model: SegmentationModelConfig) -> OnnxSegmenter:
    """Create the currently configured ONNX segmenter wrapper."""
    return OnnxSegmenter(model)
