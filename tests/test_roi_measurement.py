"""ROI statistics on synthetic images whose correct values are known exactly."""

import numpy as np
import pytest

from patari.roi.roi_records import ROIRecord
from patari.roi.roi_shapes import Polygon, Rectangle, ROIPlacementConfig
from patari.roi.roi_utils import (
    IntensityClamp,
    compute_roi_spectra,
    compute_roi_stats,
    compute_roi_time_series,
    compute_roi_track_time_series,
)

SCALE = 0.1  # mm per pixel


def block_image(value=5.0, n_frames=1, n_channels=1):
    """100x100 frames that are *value* inside rows 20:40, cols 30:60 and 0 elsewhere."""
    data = np.zeros((n_frames, n_channels, 100, 100), dtype=np.float32)
    data[:, :, 20:40, 30:60] = value
    return data


def rectangle_over_block(roi_id=0, track_id=0, frame_id=0):
    """World-mm rectangle covering exactly the block above (pixels [20:40, 30:60]).

    Rasterization fills boundary pixels, so the outline runs through the centres of
    the block's edge pixels (rows 20 and 39), not around them.
    """
    return ROIRecord(
        roi_id=roi_id, track_id=track_id, frame_id=frame_id, kind="rectangle",
        verts=np.array([[2.0, 3.0], [2.0, 5.9], [3.9, 5.9], [3.9, 3.0]]),
    )


def test_rectangle_stats_are_exact(image_layer):
    layer = image_layer(block_image(), SCALE)
    rows = compute_roi_stats([rectangle_over_block()], layer, frame_idx=0, channel_idx=0)

    assert len(rows) == 1
    row = rows.iloc[0]
    assert (row["mean"], row["median"], row["min"], row["max"], row["std"]) == (5, 5, 5, 5, 0)
    assert row["n_pixels"] == 20 * 30
    assert row["size_mm"] == pytest.approx(600 * SCALE * SCALE)
    assert (row["frame"], row["channel"], row["kind"], row["src_layer"]) == (0, 700, "rectangle", "Recon: test")


def test_ellipse_area_is_close_to_analytic(image_layer):
    layer = image_layer(np.ones((1, 1, 200, 200)), SCALE)
    # 10 x 4 mm bounding box: semi-axes 50 and 20 pixels.
    ellipse = ROIRecord(
        roi_id=0, track_id=0, frame_id=0, kind="ellipse",
        verts=np.array([[5.0, 4.0], [5.0, 14.0], [9.0, 14.0], [9.0, 4.0]]),
    )
    rows = compute_roi_stats([ellipse], layer, frame_idx=0, channel_idx=0)

    assert rows.iloc[0]["n_pixels"] == pytest.approx(np.pi * 50 * 20, rel=0.03)
    assert rows.iloc[0]["size_mm"] == pytest.approx(np.pi * 5 * 2, rel=0.03)


def test_clamp_clip_keeps_pixels_exclude_drops_them(image_layer):
    data = np.zeros((1, 1, 100, 100), dtype=np.float32)
    data[0, 0, 20:40, 30:60] = np.arange(600).reshape(20, 30) % 10  # values 0..9, 60 each
    layer = image_layer(data, SCALE)
    roi = [rectangle_over_block()]

    unclamped = compute_roi_stats(roi, layer, 0, 0).iloc[0]
    clipped = compute_roi_stats(roi, layer, 0, 0, clamp=IntensityClamp(maximum=4, mode="clip")).iloc[0]
    excluded = compute_roi_stats(roi, layer, 0, 0, clamp=IntensityClamp(maximum=4, mode="exclude")).iloc[0]

    assert unclamped["mean"] == pytest.approx(4.5)
    assert clipped["n_pixels"] == 600 and clipped["max"] == 4 and clipped["mean"] < 4.5
    assert excluded["n_pixels"] == 300 and excluded["mean"] == pytest.approx(2.0)
    assert excluded["size_mm"] == pytest.approx(clipped["size_mm"] / 2)


def test_layer_translate_shifts_mask(image_layer):
    # Layer content sits 1 mm down and 2 mm right of an untranslated one, like DeepMB output.
    layer = image_layer(block_image(), SCALE)
    layer.translate = (0, 0, 1.0, 2.0)
    shifted_roi = rectangle_over_block()
    shifted_roi.verts += (1.0, 2.0)

    assert compute_roi_stats([shifted_roi], layer, 0, 0).iloc[0]["mean"] == 5
    assert compute_roi_stats([rectangle_over_block()], layer, 0, 0).iloc[0]["mean"] < 5


def test_time_series_fixed_and_tracked(image_layer):
    data = block_image(n_frames=4)
    data *= np.arange(4, dtype=np.float32)[:, None, None, None]  # frame f has value 5f
    timestamps = 100.0 + np.arange(4)[:, None] * 2.0 + np.zeros((4, 1))
    layer = image_layer(data, SCALE, timestamps=timestamps)

    x, series = compute_roi_time_series([rectangle_over_block()], layer, channel_idx=0, feature_id="mean")
    np.testing.assert_allclose(x, [0, 2, 4, 6])  # referenced to scan start
    np.testing.assert_allclose(series[0], [0, 5, 10, 15])

    track = [rectangle_over_block(roi_id=i, track_id=1, frame_id=f) for i, f in enumerate([0, 2, 3])]
    _, tracked = compute_roi_track_time_series(1, track, layer, channel_idx=0, feature_id="mean")
    np.testing.assert_allclose(tracked[1], [0, np.nan, 10, 15])


def test_spectrum_uses_wavelength_axis(image_layer):
    data = block_image(n_channels=3)
    data *= np.array([0, 2, 4], dtype=np.float32)[None, :, None, None]  # channel c has value 10c
    layer = image_layer(data, SCALE)

    x, series, labels = compute_roi_spectra([rectangle_over_block()], layer, frame_idx=0)
    np.testing.assert_allclose(x, [0, 1, 2])
    assert labels == ["700", "710", "720"]
    np.testing.assert_allclose(series[0], [0, 10, 20])


def test_roi_shape_from_mask_is_exact():
    mask = np.zeros((100, 100), dtype=bool)
    mask[30:60] = True  # tissue band from row 30 to 59

    rect = Rectangle(ROIPlacementConfig(width_mm=4.0, height_mm=2.0, depth_mm=None))
    verts = rect.to_napari_verts_world(class_mask=mask, sy=SCALE, sx=SCALE)
    assert sorted(set(verts[:, 0])) == [3.0, 5.0]  # anchored to the band's top edge
    assert sorted(set(verts[:, 1])) == [3.0, 7.0]  # centred on column 50

    poly = Polygon(ROIPlacementConfig(width_mm=4.0, height_mm=2.0, depth_mm=None))
    poly_verts = poly.to_napari_verts_world(class_mask=mask, sy=SCALE, sx=SCALE)
    assert poly_verts[:, 0].min() >= 3.0 and poly_verts[:, 0].max() <= 5.0
    assert poly_verts[:, 1].min() >= 3.0 and poly_verts[:, 1].max() <= 7.0

    too_tall = Rectangle(ROIPlacementConfig(width_mm=4.0, height_mm=5.0, depth_mm=None))
    with pytest.raises(ValueError, match="exceeds class depth"):
        too_tall.to_napari_verts_world(class_mask=mask, sy=SCALE, sx=SCALE)
