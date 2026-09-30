"""Reconstruction, spectral unmixing, segmentation and automatic ROI placement on testdata."""

import json
from types import SimpleNamespace

import numpy as np
import pytest
from napari.layers import Labels

from optari.controllers.reconstruction_controller import (
    ReconParams,
    _reconstruct_frames,
)
from optari.controllers.roi_controller import RoiController
from optari.controllers.unmixing_controller import (
    UnmixParams,
    _unmix_frames,
    resolve_unmixing_wavelengths,
)
from optari.patato_bridge import display_data_from_patato_obj
from optari.roi.roi_shapes import class_top_at_center_column
from optari.segmentation.segmenter import create_segmenter
from optari.utils.presets import PresetStore
from optari.utils.setup import (
    get_user_reconstruction_presets_dir,
    get_user_unmixing_presets_dir,
)
from tests.conftest import HDF5_SCAN, needs_study, run_to_end

pytestmark = needs_study

FRAME = 15  # lowest-motion frame of Scan_3
WAVELENGTHS = [
    700,
    730,
    760,
    800,
    850,
    910,
    930,
    950,
    980,
    1030,
    1080,
    1100,
    1210,
]


def brightest_pixel(image_2d):
    return np.unravel_index(np.argmax(image_2d), image_2d.shape)


@pytest.fixture(scope="module")
def backprojection(hdf5_scan):
    preset = PresetStore(get_user_reconstruction_presets_dir()).load(
        "backproject_ithera"
    )
    (recon, _), steps = run_to_end(
        _reconstruct_frames(
            preset, hdf5_scan[FRAME : FRAME + 1], 1525.0, chunk_frames=1
        )
    )
    return recon, steps


def test_backprojection_single_frame(backprojection, vendor_recon):
    recon, steps = backprojection
    ours = display_data_from_patato_obj(recon)[0]
    vendor = display_data_from_patato_obj(vendor_recon[FRAME : FRAME + 1])[0]

    assert steps == 2  # one setup tick plus one chunk
    assert recon.shape == (1, 13, 400, 1, 400) and np.isfinite(ours).all()
    assert recon.fov == pytest.approx((0.04, 0.04))
    assert [int(w) for w in recon.ax_1_labels] == WAVELENGTHS
    # The vendor image is processed differently, so compare where the
    # strongest absorber sits rather than pixel values: the skin line at 800 nm.
    assert (
        np.abs(
            np.subtract(brightest_pixel(ours[3]), brightest_pixel(vendor[3]))
        ).max()
        <= 3
    )


def test_recon_params_from_preset(hdf5_scan):
    preset = PresetStore(get_user_reconstruction_presets_dir()).load(
        "backproject_ithera"
    )
    controller = SimpleNamespace(
        pa_data=hdf5_scan,
        path=HDF5_SCAN,
        timestamps=None,
        scan_ctrl=SimpleNamespace(scan_name=lambda: "DEMO_SCAN_3"),
    )

    params = ReconParams.from_settings(preset, controller, frame_id=FRAME)
    assert params.output_frames == [FRAME] and params.source_frame_count == 26
    assert params.pa_data_for_run.shape[0] == 1
    assert (
        params.layer_name == "Recon: Reference Backprojection_F15"
        and params.speed_of_sound == 1525
    )

    with pytest.raises(ValueError, match="not available"):
        ReconParams.from_settings(preset, controller, frame_id=26)
    with pytest.raises(ValueError, match="speed of sound"):
        ReconParams.from_settings(
            {
                k: v
                for k, v in preset.items()
                if k != "RECONSTRUCTION_SPEED_OF_SOUND"
            },
            controller,
        )


def test_resolve_unmixing_wavelengths():
    assert resolve_unmixing_wavelengths(
        {"WAVELENGTH_RANGE": [700, 900]}, WAVELENGTHS
    ) == [700, 730, 760, 800, 850]
    assert resolve_unmixing_wavelengths(
        {"WAVELENGTHS": [850, 800, 999]}, WAVELENGTHS
    ) == [800, 850]
    assert resolve_unmixing_wavelengths({}, WAVELENGTHS) == []


def test_unmix_haemoglobin_single_frame(hdf5_scan, vendor_recon):
    wavelengths = [700, 730, 760, 800, 850]
    (unmixed, thb, so2), steps = run_to_end(
        _unmix_frames(
            vendor_recon[FRAME : FRAME + 1],
            hdf5_scan,
            wavelengths,
            ["Hb", "HbO2"],
            reduce_factor=1,
            suffix="",
            generate_thb=True,
            generate_so2=True,
            chunk_frames=4,
        )
    )

    assert steps == 1
    assert list(unmixed.ax_1_labels) == ["Hb", "HbO2"]
    assert unmixed.shape == (1, 2, 400, 1, 400) and thb.shape == so2.shape == (
        1,
        1,
        400,
        1,
        400,
    )
    hb, hbo2 = (
        np.asarray(unmixed.raw_data)[0, 0],
        np.asarray(unmixed.raw_data)[0, 1],
    )
    thb_img, so2_img = (
        np.asarray(thb.raw_data)[0, 0],
        np.asarray(so2.raw_data)[0, 0],
    )

    np.testing.assert_allclose(thb_img, hb + hbo2, rtol=1e-5)
    valid = np.isfinite(so2_img)
    assert (
        valid.any() and not valid.all()
    )  # nan_invalid=True blanks non-physical pixels
    np.testing.assert_allclose(
        so2_img[valid], (hbo2 / thb_img)[valid], rtol=1e-5
    )
    assert so2_img[valid].min() >= 0 and so2_img[valid].max() <= 1


def test_unmix_params_from_preset(vendor_recon, image_layer):
    layer = image_layer(
        np.zeros((26, 13, 4, 4)),
        name="Recon: iThera BP",
        wavelengths=WAVELENGTHS,
    )
    controller = SimpleNamespace(
        active_recon_layer=layer, _patato_objects={layer.name: vendor_recon}
    )
    preset = PresetStore(get_user_unmixing_presets_dir()).load("haemoglobin")

    params = UnmixParams.from_preset(preset, controller, frame_id=FRAME)
    assert params.wavelengths == [700, 730, 760, 800, 850]
    assert (
        params.chromophores == ["Hb", "HbO2"]
        and params.generate_thb
        and params.generate_so2
    )
    assert (
        params.output_frames == [FRAME] and params.recon_for_run.shape[0] == 1
    )
    assert params.name_stem == "iThera BP_F15"

    hb_only = UnmixParams.from_preset(
        {**preset, "SPECTRA": ["Hb"]}, controller
    )
    assert (
        not hb_only.generate_thb
        and not hb_only.generate_so2
        and hb_only.frame_mode == "all"
    )

    with pytest.raises(ValueError, match="not reconstructed"):
        UnmixParams.from_preset(preset, controller, frame_id=26)
    with pytest.raises(ValueError, match="wavelengths were acquired"):
        UnmixParams.from_preset(
            {**preset, "WAVELENGTH_RANGE": [1300, 1400]}, controller
        )


@pytest.fixture(scope="module")
def segmentation(hdf5_scan, seg_model):
    """Segmentation of the analysis frame's ultrasound image."""
    us = display_data_from_patato_obj(hdf5_scan.get_ultrasound())[FRAME, 0]
    return create_segmenter(seg_model).predict(us[np.newaxis])[0]


def test_segmentation_of_us_frame(segmentation, seg_model):
    seg, class_names = segmentation.seg, segmentation.class_names
    ids = {int(i) for i in np.unique(seg)}
    by_name = {name: class_id for class_id, name in class_names.items()}

    assert seg.shape == (210, 210) and class_names == seg_model.class_names
    assert (
        ids <= set(class_names)
        and by_name["Muskel1"] in ids
        and by_name["Haut"] in ids
    )
    # Anatomy: skin lies above the muscle in the image.
    rows = lambda class_id: np.nonzero(seg == class_id)[0].mean()
    assert rows(by_name["Haut"]) < rows(by_name["Muskel1"])


def test_auto_roi_anchors_to_segmented_muscle(segmentation, roi_presets):
    preset = roi_presets.get("clinical_ellipse_10x2mm_Muskel1")
    assert (
        preset.placement == "auto"
        and preset.geometry.tissue_class == "Muskel1"
    )
    muscle = segmentation.seg == 3
    seg_layer = Labels(
        segmentation.seg[np.newaxis, np.newaxis],
        scale=(1, 1, 40 / 210, 40 / 210),
    )

    verts = preset.geometry.verts_mm(0.04, 0.04)
    anchored = RoiController._anchor_verts_to_mask(verts, muscle, seg_layer)
    top_row, centre_col = class_top_at_center_column(muscle)

    np.testing.assert_allclose(
        np.ptp(anchored, axis=0), np.ptp(verts, axis=0)
    )  # size kept
    assert anchored[:, 0].min() == pytest.approx(top_row * 40 / 210)
    assert (anchored[:, 1].min() + anchored[:, 1].max()) / 2 == pytest.approx(
        centre_col * 40 / 210
    )
    assert muscle[int(anchored[:, 0].min() / (40 / 210)), centre_col]

    with pytest.raises(ValueError, match="not present"):
        RoiController._anchor_verts_to_mask(
            verts, np.zeros_like(muscle), seg_layer
        )
