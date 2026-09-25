"""ROI coordinates: PATATO meters (origin at the image centre) vs napari world mm."""

import numpy as np
import pytest

from optari.roi.roi_geometry import RoiGeometry, napari_to_patato, patato_to_napari
from optari.roi.roi_presets import RoiPreset, RoiPresetStore

FOV = (0.04, 0.03)  # (fov_x_m, fov_y_m)


def test_patato_napari_round_trip():
    verts_m = np.random.default_rng(0).uniform(-0.015, 0.015, size=(6, 2))
    np.testing.assert_allclose(napari_to_patato(patato_to_napari(verts_m, *FOV), *FOV), verts_m)
    # PATATO origin is the image centre, napari's the top-left corner, PATATO y points up.
    np.testing.assert_allclose(patato_to_napari(np.zeros((1, 2)), *FOV), [[15.0, 20.0]])
    assert patato_to_napari(np.array([[0.0, 0.01]]), *FOV)[0, 0] < 15.0


def test_geometry_record_and_json_round_trip():
    geometry = RoiGeometry(verts_m=[[-0.005, 0.0], [0.005, 0.0], [0.005, -0.002], [-0.005, -0.002]],
                           kind="ellipse", tissue_class="Muskel1")
    record = geometry.to_record(roi_id=3, track_id=1, frame_id=7, fov_x_m=FOV[0], fov_y_m=FOV[1])
    restored = RoiGeometry.from_record(record, *FOV)

    np.testing.assert_allclose(restored.verts_m, geometry.verts_m, atol=1e-9)
    assert (restored.kind, restored.tissue_class) == ("ellipse", "Muskel1")
    assert RoiGeometry.from_json(geometry.to_json()).to_dict() == geometry.to_dict()


def test_repositioned_keeps_size_scales_centre():
    box = RoiGeometry(verts_m=[[-0.005, 0.012], [0.005, 0.012], [0.005, 0.010], [-0.005, 0.010]])
    moved = box.repositioned(source_fov=(0.04, 0.04), target_fov=(0.03, 0.03))

    np.testing.assert_allclose(np.ptp(moved.verts_m, axis=0), np.ptp(box.verts_m, axis=0))
    np.testing.assert_allclose(moved.verts_m.mean(axis=0), box.verts_m.mean(axis=0) * 0.75)


def test_roi_preset_store_round_trip(tmp_path):
    store = RoiPresetStore(tmp_path)
    geometry = RoiGeometry(verts_m=[[0, 0], [0.001, 0], [0.001, 0.001]])
    store.save_preset(name="tri", description="d", geometry=geometry, source_fov_m=(0.04, 0.04), placement="auto")

    preset = store.get("tri")
    assert preset.geometry.to_dict() == geometry.to_dict()
    assert (preset.placement, preset.source_fov_m) == ("auto", (0.04, 0.04))
    with pytest.raises(ValueError, match="placement"):
        RoiPreset.from_dict("x", {**preset.to_dict(), "placement": "sideways"})
