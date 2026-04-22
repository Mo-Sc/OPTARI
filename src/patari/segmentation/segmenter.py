from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
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
class OnnxModelSpec:
    """ONNX model configuration loaded from a JSON registry."""

    model_id: str
    display_name: str
    onnx_path: Path
    input_name: str
    output_name: str
    input_height: int
    input_width: int
    class_names: dict[int, str]


DEFAULT_MODELS_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "segmentation_models.json"
)


def load_onnx_model_registry(
    config_path: Path | None = None,
) -> tuple[str, dict[str, OnnxModelSpec]]:
    path = (
        Path(config_path) if config_path is not None else DEFAULT_MODELS_CONFIG
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    base_dir = path.parent

    models: dict[str, OnnxModelSpec] = {}
    for item in raw["models"]:
        model_path = Path(item["onnx_path"])
        if not model_path.is_absolute():
            model_path = (base_dir / model_path).resolve()

        class_names = {
            int(class_id): str(name)
            for class_id, name in item["class_names"].items()
        }

        spec = OnnxModelSpec(
            model_id=str(item["id"]),
            display_name=str(item["display_name"]),
            onnx_path=model_path,
            input_name=str(item["input_name"]),
            output_name=str(item["output_name"]),
            input_height=int(item["input_height"]),
            input_width=int(item["input_width"]),
            class_names=class_names,
        )
        models[spec.model_id] = spec

    default_model_id = str(raw["default_model"])
    if default_model_id not in models:
        raise ValueError(
            f"Unknown default model '{default_model_id}' in {path}"
        )

    return default_model_id, models


class OnnxSegmenter:
    """ONNX Runtime segmenter for a single US tissue model.

    Expects model output logits as (1, C, H, W).
    """

    def __init__(self, model: OnnxModelSpec) -> None:
        import onnxruntime as ort  # pyright: ignore[reportMissingImports]

        self.model = model
        self.class_names = dict(model.class_names)
        self._session = ort.InferenceSession(
            str(model.onnx_path),
            providers=["CPUExecutionProvider"],
        )

    def predict(self, us_2d: np.ndarray) -> SegmentationResult:
        us_2d = np.asarray(us_2d, dtype=np.float32)
        if us_2d.ndim != 2:
            raise ValueError(f"Expected 2D US frame, got shape {us_2d.shape}")

        h_in, w_in = us_2d.shape

        us_min = float(us_2d.min())
        us_range = float(us_2d.max() - us_min)
        us_norm = (us_2d - us_min) / (us_range if us_range > 0.0 else 1.0)

        resized = cv2.resize(
            us_norm,
            (self.model.input_width, self.model.input_height),
            interpolation=cv2.INTER_LINEAR,
        )
        model_input = resized[None, None, :, :].astype(np.float32, copy=False)

        logits = self._session.run(
            [self.model.output_name],
            {self.model.input_name: model_input},
        )[0]
        seg_small = np.argmax(logits, axis=1)[0].astype(np.int32, copy=False)

        seg = cv2.resize(
            seg_small,
            (w_in, h_in),
            interpolation=cv2.INTER_NEAREST,
        ).astype(np.int32, copy=False)

        return SegmentationResult(seg=seg, class_names=dict(self.class_names))
