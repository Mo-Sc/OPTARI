from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


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
    """Config for a single ONNX segmentation model."""
    model_id: str
    onnx_path: Path
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
) -> dict[str, SegmentationModelConfig]:
    """Load model configs and return a mapping of model_id -> config."""
    path = config_path if config_path is not None else DEFAULT_MODELS_CONFIG
    raw = json.loads(path.read_text(encoding="utf-8"))
    base_dir = path.parent

    models: dict[str, SegmentationModelConfig] = {}
    for item in raw["models"]:
        model_id = str(item["id"])
        model_path = Path(item["onnx_path"])
        if not model_path.is_absolute():
            model_path = (base_dir / model_path).resolve()

        models[model_id] = SegmentationModelConfig(
            model_id=model_id,
            onnx_path=model_path,
            class_names={
                int(k): str(v) for k, v in item["class_names"].items()
            },
            input_height=int(item["input_height"]),
            input_width=int(item["input_width"]),
        )

    return models


def dummy_mask(us_2d: np.ndarray, class_names: dict[int, str]) -> np.ndarray:
    """Deterministic dummy mask generator for testing without an ONNX model."""
    h, w = us_2d.shape
    class_ids = sorted(class_names.keys())
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
            
    return seg

def create_segmenter(model_config: SegmentationModelConfig) -> Segmenter:
    """Factory to create a Segmenter from a config."""
    return Segmenter(model_config)

class Segmenter:
    """ONNX-based Segmenter wrapper.
    
    Currently returns dummy masks for testing layout. Uncomment ONNX code 
    to enable proper inference.
    """

    def __init__(self, model_config: SegmentationModelConfig) -> None:
        self.model_config = model_config
        self.class_names = model_config.class_names
        self.onnx_path = model_config.onnx_path
        self.input_shape = (model_config.input_height, model_config.input_width)
        
        # import onnxruntime as ort
        # if not self.onnx_path.exists():
        #     logger.warning(f"ONNX model missing at {self.onnx_path}")
        # else:
        #     self.session = ort.InferenceSession(str(self.onnx_path), providers=["CPUExecutionProvider"])
        #     self.input_name = self.session.get_inputs()[0].name
        #     self.output_name = self.session.get_outputs()[0].name

    def preprocess(self, us_2d: np.ndarray) -> tuple[np.ndarray, tuple[int, ...]]:
        from scipy.ndimage import zoom
        orig_shape = us_2d.shape
        us_norm = us_2d.astype(np.float32)
        v_min, v_max = us_norm.min(), us_norm.max()
        if v_max > v_min:
            us_norm = (us_norm - v_min) / (v_max - v_min)

        target_h, target_w = self.input_shape
        zoom_factors = (target_h / orig_shape[0], target_w / orig_shape[1])
        us_resized = zoom(us_norm, zoom_factors, order=1)
        
        us_tensor = np.expand_dims(us_resized, axis=(0, 1))
        return us_tensor, orig_shape

    def predict(self, us_2d: np.ndarray) -> SegmentationResult:
        """Run ONNX inference and return the upscaled segmentation map."""
        
        # --- DUMMY MASK IMPLEMENTATION ---
        seg = dummy_mask(us_2d, self.class_names)
        return SegmentationResult(seg=seg, class_names=dict(self.class_names))

        # --- REAL ONNX IMPLEMENTATION ---
        # from scipy.ndimage import zoom
        # tensor, orig_shape = self.preprocess(us_2d)
        # outputs = self.session.run([self.output_name], {self.input_name: tensor})
        # logits = outputs[0]
        # pred_mask = np.argmax(logits, axis=1).squeeze(0)
        # target_h, target_w = self.input_shape
        # zoom_factors = (orig_shape[0] / target_h, orig_shape[1] / target_w)
        # pred_mask_orig = zoom(pred_mask.astype(np.float32), zoom_factors, order=0)
        # return SegmentationResult(
        #     seg=pred_mask_orig.astype(np.int32), 
        #     class_names=dict(self.class_names)
        # )
