# collect image processing utilities for segmentation masks
# must operate on 2d np arrays (single frame)
import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt
from skimage.measure import label, regionprops
from skimage.morphology import remove_small_objects

# --- processing functions for images ---


def resize_img(image: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Resize to *shape* ``(H, W)``; cv2 itself takes ``(W, H)``."""
    return cv2.resize(image, shape[::-1], interpolation=cv2.INTER_LINEAR)


def normalize_img(image: np.ndarray) -> np.ndarray:
    """z-score normalization over the frame."""
    image = image.astype(np.float32)
    return (image - image.mean()) / image.std()


# --- processing functions for segmentation masks ---


def resize_mask(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Resize to *shape* ``(H, W)``; cv2 itself takes ``(W, H)``."""
    return cv2.resize(mask, shape[::-1], interpolation=cv2.INTER_NEAREST)


def combine_classes(
    mask: np.ndarray, class_groups: list[list[int]]
) -> np.ndarray:
    """
    Combine multiple class ids into one class id, by reassigning all classes in a group to the first class in that group.
    """
    for group in class_groups:
        target = group[0]
        for cls in group[1:]:
            mask[mask == cls] = target
    return mask


def keep_largest_region(mask: np.ndarray, class_ids: list[int]) -> np.ndarray:
    """
    For each class id, keep only the largest connected component and reassign the rest to background (0).
    """
    for class_id in class_ids:
        binary_mask = mask == class_id
        labeled_mask, num_labels = label(binary_mask, return_num=True)

        if num_labels > 1:
            regions = regionprops(labeled_mask)
            largest_region = max(regions, key=lambda r: r.area)
            largest_label = largest_region.label

            mask[(labeled_mask != largest_label) & binary_mask] = 0
    return mask


def reassign_freed_pixels_row_based(mask: np.ndarray) -> np.ndarray:
    """Give freed pixels (0) the majority class of their row."""
    for row in mask:
        labelled = row[row > 0]
        if labelled.size:
            row[row == 0] = np.bincount(labelled).argmax()
    return mask


def reassign_freed_pixels(mask: np.ndarray) -> np.ndarray:
    """Give each freed pixel (0) the class of its nearest labelled pixel.

    A filled pixel joins the class of the labelled pixel it is closest to, so no class
    gets a new disconnected component.
    """
    freed = mask == 0
    if freed.all():
        return mask
    rows, cols = distance_transform_edt(
        freed, return_distances=False, return_indices=True
    )
    return mask[rows, cols]
