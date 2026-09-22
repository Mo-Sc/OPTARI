"""Finding scans on disk, turning them into napari layers and picking the analysis frame."""

import h5py
import numpy as np
import pytest
from patato.io.attribute_tags import HDF5Tags, IPASCTags

from patari.controllers.scan_controller import ScanController
from patari.patato_bridge import build_napari_layers, display_data_from_patato_obj, fov_from_objects
from patari.utils.motion import k_motion_scores_optimized
from tests.conftest import HDF5_SCAN, ITHERA_SCAN, STUDY_DIR, needs_study

pytestmark = needs_study


def test_discover_studies_finds_both_scans(tmp_path):
    studies = ScanController.discover_studies(STUDY_DIR.parent)
    assert list(studies) == [STUDY_DIR]
    scans = studies[STUDY_DIR]
    assert list(scans) == [ITHERA_SCAN, HDF5_SCAN]
    assert [(info.kind, info.internal_name) for info in scans.values()] == [
        ("ithera", "Study_19_2PRE"),
        ("hdf5", "Study_19_3PRE"),
    ]

    # Numeric ordering, not lexical: Scan_10 comes after Scan_2.
    keys = sorted([tmp_path / "Scan_10.hdf5", tmp_path / "Scan_2", tmp_path / "other"], key=ScanController.scan_sort_key)
    assert [ScanController.scan_key(k) for k in keys] == ["Scan_2", "Scan_10", "other"]

    # Format detection looks inside the file, not at the name.
    (tmp_path / "Scan_1").mkdir()
    (tmp_path / "Scan_1" / "Scan_1.msot").touch()
    for name, group in [("patato.hdf5", HDF5Tags.RAW_DATA), ("ipasc.hdf5", IPASCTags.BINARY_DATA), ("empty.hdf5", None)]:
        with h5py.File(tmp_path / name, "w") as file:
            if group:
                file.create_group(group)
    assert ScanController.scan_type(tmp_path / "Scan_1") == "ithera"
    assert ScanController.scan_type(tmp_path / "patato.hdf5") == "hdf5"
    assert ScanController.scan_type(tmp_path / "ipasc.hdf5") == "ipasc"
    assert ScanController.scan_type(tmp_path / "empty.hdf5") is None


def test_build_layers_from_hdf5_scan(hdf5_scan, vendor_recon):
    layers, objects = build_napari_layers(hdf5_scan)
    (us, us_kw, _), (recon, recon_kw, _) = layers

    assert us_kw["name"] == "US" and us.shape == (26, 13, 210, 210)
    assert us_kw["scale"] == pytest.approx((1, 40 / 210, 40 / 210), rel=1e-6)
    assert us_kw["metadata"]["type"] == "us"
    assert us_kw["metadata"]["motion_scores"].shape == (26,)  # DEFAULT_FRAME_INDEX is "motion"

    assert recon_kw["name"] == "Recon: iThera BP-40mm(res:100μm)_0" and recon.shape == (26, 13, 400, 400)
    assert recon_kw["scale"] == pytest.approx((1, 0.1, 0.1))
    meta = recon_kw["metadata"]
    assert meta["type"] == "pa" and meta["pa_kind"] == "recon"
    assert meta["wavelengths"] == [700, 730, 760, 800, 850, 910, 930, 950, 980, 1030, 1080, 1100, 1210]
    assert meta["frames"] == list(range(26)) and meta["timestamps"].shape == (26, 13)

    # Display data is the PATATO array flipped so depth increases downwards.
    np.testing.assert_array_equal(recon[3, 2], np.flipud(np.asarray(vendor_recon.da[3, 2, :, 0, :])))
    assert fov_from_objects(objects) == pytest.approx((0.04, 0.04), rel=1e-6)


def test_ithera_scan_builds_the_same_layer_structure(ithera_scan, hdf5_scan):
    def structure(layers):
        return [(data.shape, kw["name"], tuple(kw["scale"]), sorted(kw["metadata"])) for data, kw, _ in layers]

    assert structure(build_napari_layers(ithera_scan)[0]) == structure(build_napari_layers(hdf5_scan)[0])
    assert ithera_scan.get_scan_name() == "Study_19_2PRE"


def test_motion_frame_selection(hdf5_scan, ithera_scan):
    rng = np.random.default_rng(0)
    us = rng.normal(size=(5, 3, 64, 64))
    us[2] = us[2, 0]  # all wavelengths of frame 2 see the same image: no motion
    assert int(np.argmin(k_motion_scores_optimized(us, mask_transducer=0))) == 2

    # Regression values for the shipped test scans.
    def lowest_motion_frame(scan):
        return int(np.argmin(k_motion_scores_optimized(display_data_from_patato_obj(scan.get_ultrasound()))))

    assert lowest_motion_frame(hdf5_scan) == 15
    assert lowest_motion_frame(ithera_scan) == 24
