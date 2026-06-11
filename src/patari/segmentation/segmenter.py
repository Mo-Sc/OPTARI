from __future__ import annotations

import logging
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from scipy.ndimage import zoom

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
    """Config for a segmentation model."""
    model_id: str
    model_path: Path
    input_height: int
    input_width: int
    class_names: dict[int, str]
    default_class: str
    adapter_class: str


DEFAULT_MODELS_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "segmentation_models.json"
)


def load_model_registry(
    config_path: Path | None = None,
) -> dict[str, SegmentationModelConfig]:
    """Load model configs and return a mapping of model_id -> config."""
    path = config_path if config_path is not None else DEFAULT_MODELS_CONFIG
    raw = json.loads(path.read_text(encoding="utf-8"))
    models: dict[str, SegmentationModelConfig] = {}
    for item in raw["models"]:
        model_id = str(item["id"])
        class_names = {
            int(k): str(v) for k, v in item["class_names"].items()
        }
        models[model_id] = SegmentationModelConfig(
            model_id=model_id,
            model_path=Path(item["model_path"]),
            class_names=class_names,
            input_height=int(item["input_height"]),
            input_width=int(item["input_width"]),
            default_class=str(item["default_class"]),
            adapter_class=str(item["adapter_class"]),
        )

    return models

class ModelAdapterBase(ABC):
    """
    Base class for the segmentation adapters.
    Adapters have to implement preprocess, infer and postprocess methods,
    operating on single 2D US frames.
    """

    def __init__(self, model_config: SegmentationModelConfig) -> None:
        self.model_config = model_config
        self.class_names = model_config.class_names

    @abstractmethod
    def preprocess(
        self, us_2d: np.ndarray
    ) -> tuple[np.ndarray, tuple[int, int]]:
        raise NotImplementedError

    @abstractmethod
    def infer(self, input_tensor: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    @abstractmethod
    def postprocess(
        self, model_output: np.ndarray, orig_shape: tuple[int, int]
    ) -> np.ndarray:
        raise NotImplementedError

    def predict(self, us_data: np.ndarray) -> list[SegmentationResult]:
        """Segment a batch of frames.

        us_data: (nframes, H, W) — use us_data[np.newaxis] for a single frame.
        """
        if us_data.ndim != 3:
            raise ValueError(f"Expected (nframes, H, W), got {us_data.ndim}D")
        results = []
        for frame in us_data:
            tensor, orig_shape = self.preprocess(frame)
            mask = self.postprocess(self.infer(tensor), orig_shape)
            results.append(SegmentationResult(seg=mask, class_names=dict(self.class_names)))
        return results


class UKErUSSegAdapter(ModelAdapterBase):
    """
    Ultrasound segmentation adapter for scans taken at the university hospital of Erlangen
    using itheras Acuity Echo MSOT scanners. 
    Requires trained ONNX model files to be placed in the data/segmentation_models directory, and a config entry in segmentation_models.json.
    
    """

    def __init__(self, model_config: SegmentationModelConfig) -> None:
        super().__init__(model_config)
        self.model_path = model_config.model_path
        self.input_shape = (
            model_config.input_height,
            model_config.input_width,
        )
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model missing at {self.model_path}")

        self.session = ort.InferenceSession(
            str(self.model_path), providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

    def preprocess(
        self, us_2d: np.ndarray
    ) -> tuple[np.ndarray, tuple[int, int]]:
        orig_shape = us_2d.shape
        us_norm = us_2d.astype(np.float32)
        mean = us_norm.mean()
        std = us_norm.std()
        if std > 0:
            us_norm = (us_norm - mean) / std

        target_h, target_w = self.input_shape
        zoom_factors = (target_h / orig_shape[0], target_w / orig_shape[1])
        us_resized = zoom(us_norm, zoom_factors, order=1)

        us_tensor = np.expand_dims(us_resized, axis=(0, 1))
        return us_tensor, orig_shape

    def infer(self, input_tensor: np.ndarray) -> np.ndarray:
        outputs = self.session.run(
            [self.output_name], {self.input_name: input_tensor}
        )
        return np.asarray(outputs[0])

    def postprocess(
        self, model_output: np.ndarray, orig_shape: tuple[int, int]
    ) -> np.ndarray:
        """
        in the future, these can be moved to separate postprocessing utilities if needed, but for now we can keep it here
        since we only have one adapter anyways
        """
        logits = np.asarray(model_output)
        if logits.ndim != 4:
            raise ValueError(
                f"Expected 4D logits from model, got shape {logits.shape}"
            )

        if logits.shape[1] <= logits.shape[-1]:
            pred_mask = np.argmax(logits, axis=1).squeeze(0)
        else:
            pred_mask = np.argmax(logits, axis=-1).squeeze(0)

        zoom_factors = (
            orig_shape[0] / pred_mask.shape[0],
            orig_shape[1] / pred_mask.shape[1],
        )
        pred_mask_orig = zoom(
            pred_mask.astype(np.float32), zoom_factors, order=0
        )

        return pred_mask_orig.astype(np.int32)


def create_segmenter(
    model_config: SegmentationModelConfig,
) -> ModelAdapterBase:
    """Factory to create a segmentation adapter from a config."""
    adapter_cls = globals().get(model_config.adapter_class)
    if adapter_cls is None:
        raise ValueError(
            f"Unknown adapter class: {model_config.adapter_class}. "
            f"Available adapters: {[k for k in globals() if k.endswith('Adapter')]}"
        )
    logger.info(f"Creating segmenter with model {model_config.model_id} using adapter {model_config.adapter_class}")
    return adapter_cls(model_config)
