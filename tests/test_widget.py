def test_patari_controls_importable():
    from patari._widget import patari_controls

    assert callable(patari_controls)
