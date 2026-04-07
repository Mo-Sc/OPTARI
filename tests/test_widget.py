import pytest


def test_patari_controls_importable():
    # Minimal: ensure the napari widget entrypoint exists.
    from patari._widget import patari_controls

    assert callable(patari_controls)


@pytest.mark.usefixtures("make_napari_viewer")
def test_patari_controls_instantiates(make_napari_viewer):
    # Smoke-test: calling the widget entrypoint returns a QWidget.
    from patari._widget import patari_controls
    from qtpy.QtWidgets import QWidget

    viewer = make_napari_viewer()
    widget = patari_controls(viewer)
    assert isinstance(widget, QWidget)
