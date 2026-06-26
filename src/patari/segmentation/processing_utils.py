# collect image processing utilities for segmentation masks
# must operate on 2d np arrays (single frame)
import numpy as np
from typing import List
from skimage.measure import label, regionprops
from skimage.morphology import remove_small_objects
import cv2


# --- processing functions for images ---

def resize_img(image: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    return cv2.resize(image, target_size, interpolation=cv2.INTER_LINEAR)

def normalize_img(image: np.ndarray, mean: float = None, std: float = None) -> np.ndarray:
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

def combine_classes(mask: np.ndarray, class_groups: List[List[int]]) -> np.ndarray:
    """
    Combine multiple class ids into one class id, by reassigning all classes in a group to the first class in that group.
    """
    for group in class_groups:
        target = group[0]
        for cls in group[1:]:
            mask[mask == cls] = target
    return mask

def keep_largest_region(mask: np.ndarray, class_ids: List[int]) -> np.ndarray:
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
    """
    Reassign freed pixels (0) to the majority class in that row.
    """
    for i in range(mask.shape[0]):
        row = mask[i, :]
        freed_pixels = np.where(row == 0)[0]
        non_zero = row[row > 0]
        if len(non_zero) > 0:
            majority = np.bincount(non_zero).argmax()
            for j in freed_pixels:
                mask[i, j] = majority
    return mask

def reassign_freed_pixels(mask: np.ndarray) -> np.ndarray:
    """
    Reassign freed pixels (0) to the majority class in their neighborhood.
    """
    freed_pixels = np.where(mask == 0)
    for i, j in zip(*freed_pixels):
        neighbors = mask[max(0, i - 1) : i + 2, max(0, j - 1) : j + 2].flatten()
        neighbors = neighbors[neighbors > 0]
        if len(neighbors) > 0:
            mask[i, j] = np.bincount(neighbors).argmax()
    return mask