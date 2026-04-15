import pytest


def test_patari_controls_importable():
    # Minimal: ensure the napari widget entrypoint exists.
    from patari._widget import patari_controls

    assert callable(patari_controls)
