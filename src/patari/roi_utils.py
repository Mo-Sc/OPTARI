# roi_utils.py
import numpy as np
from skimage.draw import polygon
import cv2
import pandas as pd
from patari.config import dtype_map
from pathlib import Path


def polygon_mask(verts_px, image_shape):
    """Rasterize a polygon (verts in pixel coords) to a boolean mask."""
    ys = np.round(verts_px[:, 0]).astype(int)
    xs = np.round(verts_px[:, 1]).astype(int)
    rr, cc = polygon(ys, xs, image_shape)
    mask = np.zeros(image_shape, dtype=bool)
    mask[rr, cc] = True
    return mask


def ellipse_mask(verts_px, image_shape):
    """Rasterize a 4-point ellipse vertex representation to a boolean mask."""
    p0, p1, p2, p3 = verts_px
    cx, cy = verts_px.mean(axis=0)[::-1]  # (x,y)

    v01 = p1 - p0
    v12 = p2 - p1
    width = np.linalg.norm(v01)
    height = np.linalg.norm(v12)

    rx, ry = width / 2.0, height / 2.0
    angle = np.degrees(np.arctan2(v01[0], v01[1]))

    # OpenCV ellipse mask
    mask = np.zeros(image_shape, dtype=np.uint8)
    cv2.ellipse(
        mask,
        center=(int(cx), int(cy)),
        axes=(int(rx), int(ry)),
        angle=angle,
        startAngle=0,
        endAngle=360,
        color=1,
        thickness=-1,
    )
    return mask.astype(bool)


def compute_roi_stats(
    shapes_layer,
    active_layer,
    frame_idx: int,
    wav_idx: int,
):
    """
    Compute ROI statistics for all shapes in shapes_layer
    for the given active_layer and specific frame/wavelength.

    Returns a DataFrame with correct dtype. Skips zero-padded frames.
    """

    if active_layer is None:
        return pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)

    # check for reconstructed frames
    frames = active_layer.metadata.get("frames", None)
    if frames is not None and frame_idx not in frames:
        # this frame was zero-padded → return empty stats
        return pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)

    # clamp wavelength to valid range
    W = np.asarray(active_layer.data).shape[1]
    wav_idx = min(max(0, wav_idx), W - 1)

    # extract slice
    img2d = np.asarray(active_layer.data)[frame_idx, wav_idx]

    # scale from metadata (.scale)
    scale = active_layer.scale
    sy, sx = scale[-2], scale[-1]

    rows = []
    for i, verts in enumerate(shapes_layer.data):
        verts_arr = np.asarray(verts)
        if verts_arr.ndim != 2:
            continue

        # convert mm→px
        verts_pixels = verts_arr / np.array([sy, sx])

        shape_type = (
            shapes_layer.shape_type[i]
            if hasattr(shapes_layer, "shape_type")
            else "polygon"
        )

        # rasterize
        try:
            if shape_type == "ellipse":
                mask = ellipse_mask(verts_pixels, img2d.shape)
            else:
                mask = polygon_mask(verts_pixels, img2d.shape)
        except Exception:
            continue

        vals = img2d[mask]
        if vals.size == 0:
            stats = dict(
                roi_index=i,
                n_pixels=0,
                area_mm2=np.nan,
                mean=np.nan,
                median=np.nan,
                std=np.nan,
                min=np.nan,
                max=np.nan,
            )
        else:
            stats = dict(
                roi_index=i,
                n_pixels=int(vals.size),
                area_mm2=float(vals.size * sy * sx),
                mean=float(np.nanmean(vals)),
                median=float(np.nanmedian(vals)),
                std=float(np.nanstd(vals)),
                min=float(np.nanmin(vals)),
                max=float(np.nanmax(vals)),
            )

        # wavelength metadata
        wavelengths = active_layer.metadata.get("wavelengths", None)
        if isinstance(wavelengths, (list, tuple)) and 0 <= wav_idx < len(
            wavelengths
        ):
            wav_val = wavelengths[wav_idx]
        else:
            wav_val = wav_idx

        filepath = active_layer.metadata.get("filepath", "")
        scan_id = Path(filepath).stem.split("_")[0] if filepath else ""
        stats["source_layer"] = active_layer.name
        stats["roi_type"] = shape_type
        stats["scan_id"] = scan_id
        stats["frame"] = frame_idx
        stats["wavelength"] = wav_val
        stats["filepath"] = filepath

        rows.append(stats)

    df = pd.DataFrame(rows, columns=list(dtype_map.keys()))
    try:
        df = df.astype(dtype_map)
    except Exception:
        pass
    return df
