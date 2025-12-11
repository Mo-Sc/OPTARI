import numpy as np
from skimage.draw import polygon
import cv2
import pandas as pd

from napari import Viewer
from napari.layers import Image, Shapes


def polygon_mask(verts_px, image_shape):
    """Rasterize general polygon vertices"""
    ys = np.round(verts_px[:, 0]).astype(int)
    xs = np.round(verts_px[:, 1]).astype(int)
    rr, cc = polygon(ys, xs, image_shape)
    mask = np.zeros(image_shape, dtype=bool)
    mask[rr, cc] = True
    return mask


def ellipse_mask(verts_px, image_shape, scale=(1, 1)):
    """Rasterize ellipse stored as 4-vertex bounding box."""
    # rectangle corners
    p0, p1, p2, p3 = verts_px

    # center is midpoint average
    cx, cy = verts_px.mean(axis=0)[::-1]  # switch to (x, y)

    # axis vectors
    v01 = p1 - p0
    v12 = p2 - p1

    # lengths (width, height)
    width = np.linalg.norm(v01)
    height = np.linalg.norm(v12)

    # ellipse radii
    rx, ry = width / 2, height / 2

    # rotation angle in degrees (OpenCV uses degrees)
    angle = np.degrees(np.arctan2(v01[0], v01[1]))  # careful ordering

    # create empty mask
    mask = np.zeros(image_shape, dtype=np.uint8)

    # draw ellipse into mask
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
    shapes_layer: Shapes, image_layer: Image, viewer: Viewer
) -> pd.DataFrame:
    """
    Compute statistics for each ROI in shapes_layer against the currently displayed 2D slice of image_layer.
    Returns a pandas DataFrame with columns: roi_index, name, frame, wavelength, n_pixels, area_mm2, mean, median, std, min, max
    """

    assert (
        hasattr(image_layer, "scale") and image_layer.scale is not None
    ), "Image layer must have scale defined."
    assert hasattr(viewer, "dims"), "Viewer must have dims defined."

    wavelengths = image_layer.metadata["wavelengths"]

    # scale
    sz, sx = image_layer.scale[-2], image_layer.scale[-1]

    # current location in data
    dims_point = [round(p) for p in viewer.dims.point]

    assert (
        len(dims_point) == 4
    ), "Viewer dims must have 4 dimensions (Frame, Wavelength, z, x)."

    # Determine frame and wavelength indices to record in the table.
    frame_idx = dims_point[0]
    wavelength_idx = dims_point[1]

    img2d = np.asarray(image_layer.data)[frame_idx, wavelength_idx]
    rows = []

    for i, verts in enumerate(shapes_layer.data):
        # verts = np.asarray(verts)
        # if verts.ndim != 2 or verts.shape[1] < 2:
        #     continue
        # verts2d = verts[:, -2:]  # use last two coords (y,x) (necessary?)

        # convert data coords to pixel coords
        verts_pixels = np.asarray(verts) / np.array([sz, sx])

        shape_type = shapes_layer.shape_type[i]

        try:
            if shape_type == "ellipse":
                mask = ellipse_mask(verts_pixels, img2d.shape)
            else:
                mask = polygon_mask(verts_pixels, img2d.shape)
        except Exception as e:
            print(f"Failed to rasterize ROI {i}: {e}")
            continue

        vals = img2d[mask]

        if vals.size == 0:
            stats = dict(
                roi_index=int(i),
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
                roi_index=int(i),
                n_pixels=int(vals.size),
                area_mm2=float(int(vals.size) * sz * sx),
                mean=float(np.nanmean(vals)),
                median=float(np.nanmedian(vals)),
                std=float(np.nanstd(vals)),
                min=float(np.nanmin(vals)),
                max=float(np.nanmax(vals)),
            )

        # attempt to get a shape 'name' if shapes_layer.properties exist
        # name = ""
        # try:
        #     props = getattr(shapes_layer, "properties", None)
        #     if props is not None:
        #         if hasattr(props, "iloc"):
        #             # pandas DataFrame
        #             name = props.iloc[i].get("name", "")
        #         else:
        #             name = props.get("name", [""] * len(shapes_layer.data))[i]
        # except Exception:f
        #     name = ""

        # stats["name"] = name
        stats["roi_type"] = shape_type
        stats["frame"] = frame_idx
        stats["wavelength"] = wavelengths[wavelength_idx]

        rows.append(stats)

    df = pd.DataFrame(
        rows,
        columns=[
            "roi_index",
            # "name",
            "roi_type",
            "frame",
            "wavelength",
            "n_pixels",
            "area_mm2",
            "mean",
            "median",
            "std",
            "min",
            "max",
        ],
    )
    return df
