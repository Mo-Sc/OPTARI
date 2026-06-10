"""Segmentation utilities and model wrappers."""

from patari.segmentation.segmenter import (
    ModelAdapterBase,
    OnnxSegmentationAdapter,
    SegmentationResult,
    SegmentationModelConfig,
    load_model_registry,
    create_segmenter,
    # dummy_mask,
)
# TODO: check what postprocessing functions are still needed
# Should be same as in pipeline
# from patari.segmentation.postprocessing import (
#     class_mask,
#     keep_largest_component,
#     mask_to_largest_contour_polygon_rc,
#     polygon_rc_to_world_yx,
# )

__all__ = [
    "ModelAdapterBase",
    "OnnxSegmentationAdapter",
    "SegmentationResult",
    "SegmentationModelConfig",
    "load_model_registry",
    "create_segmenter",
    # "dummy_mask",
    # "class_mask",
    # "keep_largest_component",
    # "mask_to_largest_contour_polygon_rc",
    # "polygon_rc_to_world_yx",
]
