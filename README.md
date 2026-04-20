# PATARI - Photoacoustic Analysis Plugin for NAPARI

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](LICENSE)
[![Python >=3.10](https://img.shields.io/badge/python-%3E%3D3.10-blue)](https://www.python.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
<!-- [![PyPI](https://img.shields.io/pypi/v/patari.svg?color=green)](https://pypi.org/project/patari)
[![tests](https://github.com/FAU/patari/workflows/tests/badge.svg)](https://github.com/FAU/patari/actions)
[![codecov](https://codecov.io/gh/FAU/patari/branch/main/graph/badge.svg)](https://codecov.io/gh/FAU/patari)
[![napari hub](https://img.shields.io/endpoint?url=https://api.napari-hub.org/shields/patari)](https://napari-hub.org/plugins/patari)
[![npe2](https://img.shields.io/badge/plugin-npe2-blue?link=https://napari.org/stable/plugins/index.html)](https://napari.org/stable/plugins/index.html) -->


PATARI is a python based analysis tool for clinical photoacoustic studies, based on the PATATO and NAPARI frameworks.

Main features (v0.2):

- Load native iThera scans (including ROIs) and HDF5 scans via PATATO.
- Browse studies and fast switching between scans.
- Visualize US + reconstructed PA layers.
- Seamless scrolling through frames and wavelengths.
- Draw, edit, and save ROIs, create a ROI Library.
- Extract statistical features from ROIs, auto-updating analysis table.
- Visualize ROI intensities over time and spectrum, plot histograms.
- Spectral unmixing, including chromophore spectra and THb / sO2 calculation.
- Export processed scans to HDF5 and ROI analysis results to XLSX.
- Detailed instructions: [PATARI v0.2 Usage PDF](docs/PATARIv02_Instructions.pdf)


## Installation 

### Option A: Source Installation (recommended)

Create a new python environment, clone this repository:

```
git clone git@github.com:Mo-Sc/PATARI.git
```

Install the package (-e for editable mode):
```
pip install -e .
```

If napari is not already installed, install with napari + Qt extras:

```
pip install -e ".[all]"
```

### Option B: napari Plugin Manager

1. Install the napari app:
    - https://napari.org/stable/getting_started/installation.html#installation-bundle-conda
    - Select the installer that corresponds to your OS (Mac / Windows) and follow the instructions
    - Launch napari from launchpad / start menu

2. Install the PATARI plugin:
    - In napari, click Plugins -> Install/Uninstall Plugins
    - Drag and drop the provided .whl file into the plugin manager window
    - Next to the Install button, select PyPI and click Install
    - After installation is done, restart napari, and select PATARI Controls under Plugins



## Run PATARI

### For Option A: Terminal

Open a terminal, start PATARI via module entrypoint:

```
python -m patari.launcher
```

There is also an installed launcher entry point:

```
patari
```

This opens napari and directly adds the PATARI dock widget. To quickly create a desktop shortcut, you can use the `create_macos_desktop_launcher.py` script (mac only).

### For Option B: standalone napari App

1. Start napari
2. Open Plugins → PATARI Controls




## Some Developer Notes

- PATARI currently depends on a custom PATATO fork:

    - `https://github.com/Mo-Sc/patato.git@b950b95e283b30f56cfca00bf6b1033d53ab496e`
    - Contains some minor adjustments and bug fixes. In the future, these will either be moved to PATARI or included in the public PATATO
    - Also ensures compatibility with some of my legacy hdf5 files
- Thoughts, bugs, and feature ideas are tracked in Issues.
- High-level architecture: PATARI follows a controller + dock-factory split; `PatariController` is the central state holder and delegates most things to domain controllers (`ScanController`, `RoiController`, `AnalysisController`, `UnmixingController`, `SegmentationController`).
- Plugin startup path: `_widget.py` initializes logging, resolves the active napari viewer, creates `PatariController`, and returns the Info dock widget.
- UI construction path: `UiManager.setup_docks` creates dock widgets once and `UiManager.connect_events` connects all signals.
- Rendering/data IO: `patato_bridge.py` handles PATATO <-> napari transformations, coordinate conversion, scale/FOV, and layer data construction.
- Layer metadata: PA layers rely on metadata keys such as `type`, `pa_kind`, `frames`, `timestamps`, `axis1_name`, `axis1_labels`, and `source_layer`. Many downstream features (info labels, analysis, export/reload symmetry) depend on these.
- ROI model: ROI stats are recomputed from `shapes_layer.events.data`. Initial ROI loading temporarily disconnects this handler to avoid repeated per-shape computation during initialization.
- Coordinate conventions: ROIs are represented in napari as `(y_mm, x_mm)` and converted to PATATO `(x_m, y_m)` at export/import. Conversion logic is in `patato_bridge.py`.
- Data loading: PATARI loads either iThera scan folders or HDF5 scans via PATATO readers and supports loading both individual scans and study folders.
- Scan preference rule: if both iThera and HDF5 exist for the same scan key, scan discovery prefers HDF5 (treated as previously converted version).
- Export model: HDF5 export is write-to-new-file only (no overwrite/append), cannot export back to iThera, and currently fails if target file already exists.
- Export implementation: export is a two-pass workflow (save base scan first, reopen, then write live ROIs and derived images). This is a workaround for PATATO reader/writer ownership where loaded data stays tied to its source file.
- Derived layers: unmixing outputs (unmixed, THb, sO2) are stored in `_derived_patato_objects` and exported with synchronized attributes so they can be reloaded as normal PA layers.
- Sparse layers: data data that only contain selected frames are expanded to acquisition-frame indexing for viewer consistency; Frame id is carried in metadata and used on reload.
- Current ROI position state: `roi_position` metadata for manual ROIs is not fully synchronized yet. Future work includes fully synchronized shape specific metadata dict
- Hidden features: Segmentation and Reconstruction docks are currently disabled.
- Logging behavior: `PATARI_LOG_LEVEL` controls terminal log. `PATARI_GUI_LOG_LEVEL` controls napari GUI notification.
- Compatibility note: custom PATATO fork and import/export workarounds are currently required for some personal legacy datasets.


## License

Distributed under the terms of the [BSD-3] license,
"patari" is free and open source software

## Issues

If you encounter any problems, please [file an issue] along with a detailed description.

