import pytest


def test_patari_controls_importable():
    # Minimal: ensure the napari widget entrypoint exists.
    from patari._widget import patari_controls

    assert callable(patari_controls)


@pytest.mark.usefixtures("make_napari_viewer")
def test_patari_controls_instantiates(make_napari_viewer):
    # Smoke-test: create the magicgui factory and call it.
    from pathlib import Path

    from patari._widget import patari_controls

    viewer = make_napari_viewer()
    widget = patari_controls()

    # Calling with a dummy path should not crash even if loading fails later.
    widget(viewer, Path("dummy.hdf5"))
