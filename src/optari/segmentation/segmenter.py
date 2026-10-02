"""Segmentation model adapters.

ModelAdapterBase is the extension point for a new segmentation model: a subclass
implements preprocess(), infer() and postprocess() for its own model format, and the
model registry references it by class name in adapter_class.
"""

from __future__ import annotations

import logging
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import onnxruntime as ort

from optari.utils.setup import (
    get_user_seg_models_config_file,
    get_user_models_dir,
)
from optari.segmentation.processing_utils import (
    resize_img,
    resize_mask,
    normalize_img,
    combine_classes,
    keep_largest_region,
    reassign_freed_pixels_row_based,
    remove_small_objects,
    reassign_freed_pixels,
)

logger = logging.getLogger(__name__)

MASK_DTYPE = np.uint8


@dataclass(frozen=True)
class SegmentationResult:
    """Result of segmenting a single 2D US frame.

    seg:
        (H, W) integer class id map.
    class_names:
        Mapping of class id -> display name.
    blank:
        The frame was constant (e.g. a zero-padded frame that was never acquired) and
        got an empty mask instead of a prediction.
    """

    seg: np.ndarray
    class_names: dict[int, str]
    blank: bool = False


@dataclass(frozen=True)
class SegmentationModelConfig:
    """Config for a segmentation model."""

    model_id: str
    filename: str
    input_height: int
    input_width: int
    class_names: dict[int, str]
    default_class: str
    adapter_class: str
    postprocessing_config: dict | None = None
    url: str | None = None


def load_model_registry() -> dict[str, SegmentationModelConfig]:
    """Load model configs and return a mapping of model_id -> config."""

    model_config = json.loads(get_user_seg_models_config_file().read_text())
    models: dict[str, SegmentationModelConfig] = {}
    for item in model_config["models"]:
        model_id = str(item["id"])
        class_names = {int(k): str(v) for k, v in item["class_names"].items()}
        if max(class_names) > np.iinfo(MASK_DTYPE).max:
            raise ValueError(
                f"Segmentation model '{model_id}': class ids must be below "
                f"{np.iinfo(MASK_DTYPE).max + 1}"
            )
        models[model_id] = SegmentationModelConfig(
            model_id=model_id,
            filename=str(item["filename"]),
            class_names=class_names,
            input_height=int(item["input_height"]),
            input_width=int(item["input_width"]),
            default_class=str(item["default_class"]),
            adapter_class=str(item["adapter_class"]),
            postprocessing_config=item.get("postprocessing_config", None),
            url=item.get("url", None),
        )

    return models


class ModelAdapterBase(ABC):
    """
    Base class for the segmentation adapters.
    Adapters have to implement preprocess, infer and postprocess methods,
    operating on single 2D grayscale frames.
    """

    def __init__(self, model_config: SegmentationModelConfig) -> None:
        """Store the model config and its class id -> name mapping."""
        self.model_config = model_config
        self.class_names = model_config.class_names

    @abstractmethod
    def preprocess(self, frame_2d: np.ndarray) -> np.ndarray:
        """Prepare a single 2D grayscale frame for infer().

        Implementations resize and normalize the frame to the model's expected
        input shape.
        """
        raise NotImplementedError

    @abstractmethod
    def infer(self, frame_2d: np.ndarray) -> np.ndarray:
        """Run the model on a preprocessed frame and return the raw predicted mask."""
        raise NotImplementedError

    @abstractmethod
    def postprocess(
        self, mask_2d: np.ndarray, frame_shape: tuple[int, int]
    ) -> np.ndarray:
        """Turn the raw predicted mask into the final class id map for the original frame.

        Implementations resize the mask back to *frame_shape* and clean up the class
        predictions.
        """
        raise NotImplementedError

    def predict(self, frames: np.ndarray) -> list[SegmentationResult]:
        """Segment a batch of frames.

        Args:
            frames: (nframes, H, W), use frames[np.newaxis] for a single frame.
        """
        results = []
        for frame_2d in frames:
            # A constant frame has nothing to segment, and its z-score normalization would divide
            # by a zero std and feed NaN to the model, which returns a meaningless mask.
            if np.ptp(frame_2d) == 0:
                results.append(
                    SegmentationResult(
                        seg=np.zeros(frame_2d.shape, dtype=MASK_DTYPE),
                        class_names=dict(self.class_names),
                        blank=True,
                    )
                )
            else:
                mask_2d = self.postprocess(
                    self.infer(self.preprocess(frame_2d)), frame_2d.shape
                )
                results.append(
                    SegmentationResult(
                        seg=mask_2d.astype(MASK_DTYPE),
                        class_names=dict(self.class_names),
                    )
                )
        return results


class UKErUSSegAdapter(ModelAdapterBase):
    """
    Ultrasound segmentation adapter for scans taken at the university hospital of Erlangen
    using itheras Acuity Echo MSOT scanners.
    Requires trained ONNX model file and a config entry in segmentation_models.json.

    """

    def __init__(self, model_config: SegmentationModelConfig) -> None:
        """Load the ONNX model weights and open an inference session.

        Raises:
            FileNotFoundError: The model weights have not been downloaded yet.
        """
        super().__init__(model_config)

        self.input_shape = (
            model_config.input_height,
            model_config.input_width,
        )

        model_path = get_user_models_dir() / model_config.filename

        if not model_path.is_file():
            raise FileNotFoundError(
                f"Segmentation model not downloaded: {model_path}"
            )

        # CUDA is only available with onnxruntime-gpu (Linux). Elsewhere this resolves to CPU.
        providers = [
            p
            for p in ("CUDAExecutionProvider", "CPUExecutionProvider")
            if p in ort.get_available_providers()
        ]
        self.session = ort.InferenceSession(
            str(model_path), providers=providers
        )
        logger.info(
            "segmentation running on %s", self.session.get_providers()[0]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

    def preprocess(self, frame_2d: np.ndarray) -> np.ndarray:
        """Resize the frame to the model's input shape and apply z-score normalization."""
        # resize to model input shape
        # TODO: check resize vs padding
        frame_2d = resize_img(frame_2d, self.input_shape)

        # z score normalization
        # TODO: check global mean/std vs per-frame
        frame_2d = normalize_img(frame_2d)

        return frame_2d

    def infer(self, frame_2d: np.ndarray) -> np.ndarray:
        """Run the ONNX session on the frame and return the per-pixel class id map."""
        # add leading dim and run inference
        frame_tensor = np.expand_dims(frame_2d, axis=(0, 1))
        outputs = self.session.run(
            [self.output_name], {self.input_name: frame_tensor}
        )
        mask_2d = np.argmax(outputs[0], axis=1).squeeze()

        return mask_2d

    def postprocess(
        self, mask_2d: np.ndarray, frame_shape: tuple[int, int]
    ) -> np.ndarray:
        """
        Perform custom postprocessing on the segmentation masks
        """
        post_cfg = self.model_config.postprocessing_config
        # resize back to original frame shape
        mask_2d = resize_mask(mask_2d, frame_shape)
        # only keep the largest connected component for the given class ids
        mask_2d = keep_largest_region(
            mask_2d, post_cfg["keep_largest_per_class"]
        )
        # give freed pixels the most frequent remaining class in their row
        mask_2d = reassign_freed_pixels_row_based(mask_2d)
        # combine given classes into one class (here fascia classes)
        mask_2d = combine_classes(mask_2d, post_cfg["combine_class_groups"])
        for class_id, max_size in post_cfg["remove_small_objects_config"]:
            class_mask = mask_2d == class_id
            processed_class = remove_small_objects(
                class_mask, max_size=max_size
            )
            mask_2d[class_mask & ~processed_class] = 0
        # The row-wise step hands a row's majority class to pixels anywhere in that row,
        # which can recreate fragments of a class reduced to its largest component above.
        # Enforce that again last, then give the gaps their nearest class.
        mask_2d = keep_largest_region(
            mask_2d, post_cfg["keep_largest_per_class"]
        )
        mask_2d = reassign_freed_pixels(mask_2d)

        return mask_2d


def create_segmenter(
    model_config: SegmentationModelConfig,
) -> ModelAdapterBase:
    """Factory to create a segmentation adapter from a config."""
    # Every adapter defined here is available by class name
    adapters = {cls.__name__: cls for cls in ModelAdapterBase.__subclasses__()}
    adapter_cls = adapters.get(model_config.adapter_class)
    if adapter_cls is None:
        raise ValueError(
            f"Unknown adapter class: {model_config.adapter_class}. "
            f"Available adapters: {sorted(adapters)}"
        )
    logger.info(
        "creating segmenter with model %s using adapter %s",
        model_config.model_id,
        model_config.adapter_class,
    )
    return adapter_cls(model_config)
