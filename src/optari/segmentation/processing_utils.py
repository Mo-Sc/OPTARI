# collect image processing utilities for segmentation masks
# must operate on 2d np arrays (single frame)
import cv2
import numpy as np
from scipy.ndimage import convolve
from skimage.measure import label, regionprops
from skimage.morphology import remove_small_objects


# --- processing functions for images ---

def resize_img(image: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    return cv2.resize(image, target_size, interpolation=cv2.INTER_LINEAR)

def normalize_img(image: np.ndarray, mean: float | None = None, std: float | None = None) -> np.ndarray:
    """
    z score normalization, with optional pre-computed mean and std
    """
    image = image.astype(np.float32)
    if mean is None or std is None:
         mean = image.mean()
         std = image.std()
    
    image = (image - mean) / std
    return image


# --- processing functions for segmentation masks ---

def resize_mask(mask: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    return cv2.resize(mask, target_size, interpolation=cv2.INTER_NEAREST)

def combine_classes(mask: np.ndarray, class_groups: list[list[int]]) -> np.ndarray:
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
    """Give freed pixels (0) the majority class of their 3x3 neighbourhood."""
    classes = np.unique(mask[mask > 0])
    if not classes.size:
        return mask
    votes = np.stack([convolve((mask == c).astype(int), np.ones((3, 3), dtype=int), mode="constant") for c in classes])
    freed = (mask == 0) & (votes.sum(axis=0) > 0)
    mask[freed] = classes[votes.argmax(axis=0)][freed]
    return mask