"""Shared fixtures."""

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

# OPTARI reads ~/.optari on import, so the run gets a user directory of its own.
# Segmentation weights are large downloads and are linked in from the real one.
_user_dir = tempfile.TemporaryDirectory(prefix="optari-test-")
os.environ["OPTARI_USER_DIR"] = _user_dir.name
from optari.utils.setup import (
    get_user_models_dir,
    get_user_roi_presets_dir,
)  # noqa: E402

for weights in (Path.home() / ".optari" / "models").glob("*.onnx"):
    (get_user_models_dir() / weights.name).symlink_to(weights)

import patato as pat  # noqa: E402
from napari.layers import Image  # noqa: E402
from patato.io.ithera.read_ithera import iTheraMSOT  # noqa: E402

from optari.roi.roi_presets import RoiPresetStore  # noqa: E402
from optari.segmentation.segmenter import load_model_registry  # noqa: E402

STUDY_DIR = Path(__file__).parent / "testdata" / "Study_19"
ITHERA_SCAN = STUDY_DIR / "Scan_2"
HDF5_SCAN = STUDY_DIR / "Scan_3.hdf5"

needs_study = pytest.mark.skipif(
    not STUDY_DIR.exists(), reason="Study_19 test data not present"
)


def run_to_end(generator):
    """Drain a background-step generator the way the worker would; return (result, ticks)."""
    ticks = 0
    while True:
        try:
            next(generator)
            ticks += 1
        except StopIteration as done:
            return done.value, ticks


@pytest.fixture(scope="session")
def hdf5_scan():
    scan = pat.PAData.from_hdf5(str(HDF5_SCAN), mode="r")
    yield scan
    scan.close()


@pytest.fixture(scope="session")
def ithera_scan():
    return pat.PAData(iTheraMSOT(str(ITHERA_SCAN)))


@pytest.fixture(scope="session")
def vendor_recon(hdf5_scan):
    return next(iter(hdf5_scan.get_scan_reconstructions().values()))


@pytest.fixture(scope="session")
def seg_model():
    config = load_model_registry()["c_unet_gastrocnemius-transverse"]
    if not (get_user_models_dir() / config.filename).is_file():
        pytest.skip(f"segmentation weights {config.filename} not downloaded")
    return config


@pytest.fixture
def roi_presets():
    return RoiPresetStore(get_user_roi_presets_dir())


@pytest.fixture
def image_layer():
    """A PA image layer as the app builds it: (frames, channels, y, x) with mm scale."""

    def make(data, scale_mm=0.1, name="Recon: test", **metadata):
        data = np.asarray(data)
        wavelengths = list(range(700, 700 + 10 * data.shape[1], 10))
        metadata = {
            "type": "pa",
            "wavelengths": wavelengths,
            "axis1_labels": wavelengths,
            "frames": list(range(data.shape[0])),
            **metadata,
        }
        return Image(
            data,
            name=name,
            scale=(1, 1, scale_mm, scale_mm),
            metadata=metadata,
        )

    return make
