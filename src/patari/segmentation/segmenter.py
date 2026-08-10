from __future__ import annotations

import logging
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import onnxruntime as ort

from patari.utils.setup import get_user_seg_models_config_file, get_user_models_dir
from patari.segmentation.processing_utils import resize_img, resize_mask, normalize_img, combine_classes, keep_largest_region, reassign_freed_pixels_row_based, remove_small_objects, reassign_freed_pixels

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
        class_names = {
            int(k): str(v) for k, v in item["class_names"].items()
        }
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
        self.model_config = model_config
        self.class_names = model_config.class_names

    @abstractmethod
    def preprocess(
        self, frame_2d: np.ndarray
    ) -> tuple[np.ndarray, tuple[int, int]]:
        raise NotImplementedError

    @abstractmethod
    def infer(self, frame_2d: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    @abstractmethod
    def postprocess(
        self, mask_2d: np.ndarray)-> np.ndarray:
        raise NotImplementedError

    def predict(
        self,
        frames: np.ndarray,
        on_frame_complete: Callable[[int], None] | None = None,
    ) -> list[SegmentationResult]:
        """Segment a batch of frames.
        on_frame_complete: optional callback to report progress
        us_data: (nframes, H, W) — use us_data[np.newaxis] for a single frame.
        """
        results = []
        for frame_2d in frames:
            frame_2d_pre = self.preprocess(frame_2d)
            mask_2d = self.infer(frame_2d_pre)
            mask_2d_post = self.postprocess(mask_2d)
            results.append(SegmentationResult(seg=mask_2d_post, class_names=dict(self.class_names)))
            if on_frame_complete is not None:
                on_frame_complete(1)
        return results


class UKErUSSegAdapter(ModelAdapterBase):
    """
    Ultrasound segmentation adapter for scans taken at the university hospital of Erlangen
    using itheras Acuity Echo MSOT scanners. 
    Requires trained ONNX model file and a config entry in segmentation_models.json.
    
    """

    def __init__(self, model_config: SegmentationModelConfig) -> None:
        super().__init__(model_config)


        self.input_shape = (
            model_config.input_height,
            model_config.input_width,
        )

        model_path = get_user_models_dir() / model_config.filename

       # check if model exists in user dir, if not, try to download
        if not model_path.exists():
            if not model_config.url:
                raise FileNotFoundError(
                    f"Model file {model_config.filename} not found and no download URL provided in config."
                )
            
            logger.info(f"Model {model_config.filename} missing. Attempting auto-download from {model_config.url}")
            try:
                from patari.utils.misc import download_file
                download_file(model_config.url, model_path)
                logger.info(f"Successfully downloaded model {model_config.filename} to {model_path}")
            except Exception as e:
                msg = f"Failed to download model {model_config.filename} from {model_config.url}: {e}"
                logger.error(msg)
                raise RuntimeError(msg)

        self.session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

    def preprocess(
        self, frame_2d: np.ndarray
    ) -> tuple[np.ndarray, tuple[int, int]]:
        
        self.frame_orig_shape = frame_2d.shape

        # resize to model input shape
        # TODO: check resize vs padding
        frame_2d = resize_img(frame_2d, self.input_shape)

        # z score normalization
        # TODO: check global mean/std vs per-frame
        frame_2d = normalize_img(frame_2d)
        
        return frame_2d

    def infer(self, frame_2d: np.ndarray) -> np.ndarray:
        # add leading dim and run inference
        frame_tensor = np.expand_dims(frame_2d, axis=(0, 1))
        outputs = self.session.run(
            [self.output_name], {self.input_name: frame_tensor}
        )
        mask_2d = np.argmax(outputs[0], axis=1).squeeze() 

        return mask_2d

    def postprocess(self, mask_2d: np.ndarray) -> np.ndarray:
        """
        Perform custom postprocessing on the segmentation masks
        """
        post_cfg = self.model_config.postprocessing_config
        # resize back to original frame shape
        mask_2d = resize_mask(mask_2d, self.frame_orig_shape)
        # only keep the largest connected component for the given class ids
        mask_2d = keep_largest_region(mask_2d, post_cfg["keep_largest_per_class"])
        # reassign freed pixels row-wise to the nearest remaining class in that row
        mask_2d = reassign_freed_pixels_row_based(mask_2d)
        # combine given classes into one class (here fascia classes)
        mask_2d = combine_classes(mask_2d, post_cfg["combine_class_groups"])
        for class_id, max_size in post_cfg["remove_small_objects_config"]:
            class_mask = mask_2d == class_id
            processed_class = remove_small_objects(class_mask, max_size=max_size)
            mask_2d[class_mask & ~processed_class] = 0
        # reassign any remaining freed pixels to the nearest class
        mask_2d = reassign_freed_pixels(mask_2d)

        return mask_2d


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
