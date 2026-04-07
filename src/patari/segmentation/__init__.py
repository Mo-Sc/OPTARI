"""Segmentation utilities and model wrappers."""

from patari.segmentation.segmenter import DummySegmenter, SegmentationResult
from patari.segmentation.napari import (
    ensure_segmentation_labels_layer,
    set_segmentation_2d,
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
    "DummySegmenter",
    "SegmentationResult",
    "ensure_segmentation_labels_layer",
    "set_segmentation_2d",
    # "class_mask",
    # "keep_largest_component",
    # "mask_to_largest_contour_polygon_rc",
    # "polygon_rc_to_world_yx",
]
