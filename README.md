# PATARI - Photoacoustic Analysis Plugin for NAPARI

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](LICENSE)
[![Python >=3.10](https://img.shields.io/badge/python-%3E%3D3.10-blue)](https://www.python.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
<!-- [![PyPI](https://img.shields.io/pypi/v/patari.svg?color=green)](https://pypi.org/project/patari)
[![tests](https://github.com/FAU/patari/workflows/tests/badge.svg)](https://github.com/FAU/patari/actions)
[![codecov](https://codecov.io/gh/FAU/patari/branch/main/graph/badge.svg)](https://codecov.io/gh/FAU/patari)
[![napari hub](https://img.shields.io/endpoint?url=https://api.napari-hub.org/shields/patari)](https://napari-hub.org/plugins/patari)
[![npe2](https://img.shields.io/badge/plugin-npe2-blue?link=https://napari.org/stable/plugins/index.html)](https://napari.org/stable/plugins/index.html) -->


PATATO is a python based analysis tool for clinical photoacoustic studies, based on the PATATO and NAPARI frameworks.

Main features:

s- Load iThera scan folders (including ROIs) and HDF5 scans via PATATO.
- Browse complete studies and switch between scans.
- Visualize US + reconstructed PA layers.
- Draw, edit, and save ROIs with live statistics (frame/wavelength aware).
- Visualize intensities over time and spectrum.
- Use segmentation-assisted ROI placement presets for faster annotation.
- Export processed scans and ROI results (XLSX/HDF5).
- Demo: [PATARI v0.1 PDF](PATARIv01DEMO.pdf)





## Installation


For local development:

```
pip install -e .
```

If napari is not already installed, install with napari + Qt extras:

```
pip install -e ".[all]"
```

## Run PATARI

For development/debugging, the dedicated launcher script is the easiest:

```
python launch_patari.py
```

This opens napari and directly adds the PATARI dock widget.

Alternative (standard napari workflow):

1. Start napari (`napari`)
2. Open Plugins → PATARI Controls


Note: PATARI currently depends on a custom PATATO fork:

- `patato @ git+https://github.com/Mo-Sc/patato.git@279481c6682e6869197ddfae3a003a0af25c2fe5`
- Contains some minor adjustments and bug fixes. In the future, these will either be moved to PATARI or included in the public PATATO
- Also ensures compatibility with some of my legacy hdf5 files

## Developer Notes

Set `PATARI_LOG_LEVEL=DEBUG` for verbose development logging; the default is `INFO`.


TODO


### Data Loading

- PATARI loads either iThera scan folders or HDF5 scans through PATATO readers.
- Can load individual scans as well as study folders
- When native ithera and hdf5 versions are available for the same scan key, the scan browser prefers the HDF5 file, assuming it is an already converted version of the ithera scan.
- HDF5 export is always to a new HDF5 file, cant export back to iThera.
- Export uses PATATO export functionality, so all new data that is part of pa_data will be exported
- Currently no overwrite / append functionality (PATARI fails if file exists already)
- Export is a two-pass operation: First the loaded scan is exported, then re-opens the new file and writes the live napari ROIs back through PATATO.
    - Necessary because PATATOs PAData doesnt really own a copy of the scan, but just wraps reader and writer
    - so for loaded hdf5 scan, data stays tied to underlying file
    - therefore adding data always mutates the source file, not to some internal memory which can later be exported to a new target file
    - But I still think there should be a better way of doing this (is also relevant for future recon / unmixing features)
- For compatibility with some previous versions of ithera import frameworks, there are some custom changes to dataset names etc. (for example `name` or `scan_name`)


## License

Distributed under the terms of the [BSD-3] license,
"patari" is free and open source software

## Issues

If you encounter any problems, please [file an issue] along with a detailed description.

