import numpy as np
from itertools import combinations
from skimage.metrics import structural_similarity as ssim


def _min_max_scale(arr: np.ndarray) -> np.ndarray:
    ptp = np.ptp(arr)
    return (arr - arr.min()) / ptp if ptp > 0 else np.zeros_like(arr)


def spectral_motion_scores(
    us_data: np.ndarray, mask_transducer: int = 60
) -> np.ndarray | None:
    """
    adapted from:
    Kukačka, J., Bader, M., Jüstel, D. et al. Motion score for spectral quality control of optoacoustic-ultrasound data. Sci Rep 16, 1325 (2026).
    https://doi.org/10.1038/s41598-025-33753-6
    Highly optimized SSIM + ZNCC motion scores for structured, padded US data.
    Speedup: ~25x

    Scores motion *within* each frame's wavelength set, comparing the ultrasound
    images of its wavelengths with each other. That is the motion that misaligns
    spectra and corrupts unmixing. Frames are not compared with each other, only
    scaled against each other at the end.

    Returns None when no frame has two distinct images to compare (a single
    wavelength, or a scanner repeating one US image per wavelength set): every frame would
    score the same, and an all-zero result would read as "no motion".

    Input shape: (n_frames, n_wavelengths, height, width)
    mask_transducer: int, number of pixels to mask out from the top of the image (transducer)
    """
    n_frames = us_data.shape[0]

    raw_ssim = np.zeros(n_frames)
    raw_zncc = np.zeros(n_frames)

    us_data = us_data[:, :, mask_transducer:, :]
    # Counted after cropping
    num_pixels = us_data.shape[2] * us_data.shape[3]

    # Constant peak-to-peak data range for stable SSIM, taken over the compared pixels
    global_range = np.ptp(us_data)

    any_sweep_compared = False
    for i in range(n_frames):
        block = us_data[i]

        # Identify indices where adjacent frames actually differ.
        # This replaces slow lexicographical sorting via np.unique.
        changes = np.any(block[1:] != block[:-1], axis=(1, 2))
        unique_indices = np.concatenate(([0], np.where(changes)[0] + 1))
        unique_frames = block[unique_indices]

        n_unique = len(unique_frames)

        if n_unique <= 1:
            # check static match
            # to instantly skip heavy skimage structural processing loops.
            raw_ssim[i] = -1.0  # SSIM of identical images is always 1.0
            raw_zncc[i] = -num_pixels  # ZNCC dot-product of self is always -N
        else:
            any_sweep_compared = True
            # Standardize all unique frames in one vectorized step.
            # Avoids recalculating the mean and std inside the pairwise combinations loop.
            means = unique_frames.mean(axis=(1, 2), keepdims=True)
            stds = unique_frames.std(axis=(1, 2), keepdims=True)
            stds = np.where(
                stds == 0, 1.0, stds
            )  # Guard against zero division
            std_frames = (unique_frames - means) / stds

            s_pairs, z_pairs = [], []
            for idx1, idx2 in combinations(range(n_unique), 2):
                # Calculate structural similarity with the constant global dynamic range
                s_pairs.append(
                    -ssim(
                        unique_frames[idx1],
                        unique_frames[idx2],
                        data_range=global_range,
                    )
                )

                # dot-product matrix multiplication on pre-standardized arrays
                z_pairs.append(-np.sum(std_frames[idx1] * std_frames[idx2]))

            raw_ssim[i] = np.mean(s_pairs)
            raw_zncc[i] = np.mean(z_pairs)

    if not any_sweep_compared:
        return None
    return (_min_max_scale(raw_ssim) + _min_max_scale(raw_zncc)) / 2.0


def frame_motion_scores(
    us_data: np.ndarray, mask_transducer: int = 60
) -> np.ndarray:
    """Motion *between* frames: how much each frame's ultrasound differs from the
    previous and the next frame, e.g. from breathing or probe movement.

    The same SSIM + ZNCC dissimilarity as `spectral_motion_scores`, on each frame's
    ultrasound averaged over its sweep, so it also works for a single wavelength.
    Like the spectral score it is min-max scaled within the scan: it shows where
    motion happens, not how much.

    Some scanners refresh the ultrasound only every few frames, repeating the same
    image in between. Comparing those repeats would make every frame inside a run
    look perfectly still, so distinct images are compared with their distinct
    neighbours, and each frame gets the score of the image it shows.

    Input shape: (n_frames, n_wavelengths, height, width)
    """
    frame_images = us_data[:, :, mask_transducer:, :].mean(axis=1)
    changes = np.any(frame_images[1:] != frame_images[:-1], axis=(1, 2))
    # Index of the distinct image each frame shows
    image_of_frame = np.concatenate(([0], np.cumsum(changes)))
    images = frame_images[np.concatenate(([0], np.flatnonzero(changes) + 1))]
    n_images = images.shape[0]
    if n_images < 2:
        return np.zeros(len(frame_images))

    global_range = np.ptp(images)
    means = images.mean(axis=(1, 2), keepdims=True)
    stds = images.std(axis=(1, 2), keepdims=True)
    std_images = (images - means) / np.where(stds == 0, 1.0, stds)

    # Dissimilarity of each consecutive pair (i, i + 1)
    pair_ssim = np.array(
        [
            -ssim(images[i], images[i + 1], data_range=global_range)
            for i in range(n_images - 1)
        ]
    )
    pair_zncc = -np.sum(std_images[:-1] * std_images[1:], axis=(1, 2))

    # An image scores the mean of its pairs; the first and last have one neighbour.
    def per_image(pairs: np.ndarray) -> np.ndarray:
        padded = np.concatenate(([np.nan], pairs, [np.nan]))
        return np.nanmean(np.stack([padded[:-1], padded[1:]]), axis=0)

    return (
        (
            _min_max_scale(per_image(pair_ssim))
            + _min_max_scale(per_image(pair_zncc))
        )
        / 2.0
    )[image_of_frame]
