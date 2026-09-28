# Contributing

Issues and pull requests are welcome on [GitHub](https://github.com/Mo-Sc/OPTARI). 

## Development install

```bash
git clone git@github.com:Mo-Sc/OPTARI.git
cd OPTARI
pip install -e ".[test,docs,dev]"
```


### Test data

The tests use two scans, recorded by the iThera MSOT Acuity Scanner, taken from [doi.org/10.5281/zenodo.22044239](https://doi.org/10.5281/zenodo.22044239). They can be downloaded [here](https://faubox.rrze.uni-erlangen.de/dl/fi3spvKzSi48ZeCS8d2Yom/Study_19.zip).


```
Study_19/
  Scan_2/          # iThera MSOT folder (Scan_2.msot, .bin, .us, ...)
  Scan_3.hdf5      # OPTARI HDF5
```

## Running the tests

Unzip the archive, put the test folder under tests/testdata/ and run:

```bash
python -m pytest
```

Segmentation tests additionally need the ONNX weights of `unet_msot_2_ta` and skip when they are not in `~/.optari/models`. Run segmentation once from the GUI to download them.


### Tests overview

The tests are headless, so they dont cover publishing layers into the viewer, the Qt event loop, etc.

| Module | Checks |
| --- | --- |
| `test_roi_geometry.py` | PATATO ↔ napari coordinate transforms, `RoiGeometry` round trips, FOV repositioning, ROI presets |
| `test_roi_measurement.py` | ROI statistics on synthetic images with known values, intensity clamping, layer translate, time series, spectra, ROI shapes from masks |
| `test_roi_table.py` | Saved Analysis table: stamping, autosave, XLSX export/import, de-duplication, rejected files |
| `test_scan_loading.py` | Study discovery, format detection, layer building from iThera and HDF5 scans, motion-based frame selection |
| `test_processing.py` | Backprojection, unmixing (THb, sO2), segmentation, automatic ROI placement, parameter resolution from presets |
| `test_export.py` | OPTARI HDF5 round trip with ROIs and derived images, IPASC export, batch report |
| `test_batch.py` | Batch preset → plan resolution, plan validation, the per-scan run loop, source and overlay layer selection |
