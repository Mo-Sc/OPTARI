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

Key features (v0.3):

- Load native iThera scans (including ROIs), PATATO HDF5 scans and more.
- Browse studies and fast switching between scans.
- Visualize US + reconstructed PA layers.
- Seamless scrolling through frames and wavelengths.
- Draw, edit, and save ROIs, create a ROI Library.
- Extract customizable statistical features from ROIs, auto-updating analysis table, export to XLSX.
- Fast intensity extraction over multiple layers, frames, wavelengths or chromophores.
- Visualize ROI intensities over time and spectrum, plot histograms.
- AI-based tissue segmentation and automatic ROI placement in target class.
- Spectral unmixing, including chromophore spectra and THb / sO2 calculation.
- Export processed scans to HDF5.
- Usage instructions: [PATARI v0.2 Usage PDF](docs/PATARIv02_Instructions.pdf) (TODO: update)
- Keyboard shortcuts: [PATARI Keyboard Shortcuts Guide](docs/shortcuts.md)


## Installation 

### Option A: Executable (recommended for clinical use)

1. Download the executable file of the [current release (v3)](tbd) for your operating system (macOS or windows).
2. Unpack the zip folder and run the patari file.
3. [Optional, on first run] If you get an error, stating PATARI could not be verified, give your OS permission to run it:
    * For windows: Click `More Info` -> `Run Anyways`
    * For macOS: Open `System Settings` -> `Privacy & Security` -> Scroll down to Security -> “patari was blocked” -> `Open Anyway`
4. At first run, PATARI will download all the required files, so make sure your computer is connected to the internet. The installation can take a few minutes.
5. Once the installation is done, PATARI launches automatically. If patari is closed, you can simply launch it again by clicking on the same patari file.


### Option B: Installation from source (recommended for development)

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

To run patari, open a terminal, start PATARI via module entrypoint:

```
python -m patari.launcher
```

There is also an installed launcher entry point:

```
patari
```

This opens napari and directly adds the PATARI dock widget. To quickly create a desktop shortcut, you can use the `create_macos_desktop_launcher.py` script (mac only).

## Configuration

At installation, PATARI creates a `.patari` folder in the users home directory and copies all the relevant configuration files into it. It also contains a `models` folder, where PATARI auto-downloads pretrained segmentation models, once the segmentation adapter is run for the first time. 

To change settings in PATARI, edit the respective json file (requires restart):
- `config.json`: main configuration file. Contains general settings, as well as task-specific settings for the different modules.
- `roi_library.json`: Contains all the ROIs in the ROI Library. Entries can be manually added or deleted.
- `segmentation_models.json`: Configuration for the automatic segmentation. See segmentation reference for more info (tbd)

In a future version, these settings will be editable from the GUI as well.

## Development Stuff 


- PATARI currently depends on a custom PATATO fork:

    - `https://github.com/Mo-Sc/patato.git@b950b95e283b30f56cfca00bf6b1033d53ab496e`
    - Contains some minor adjustments and bug fixes. In the future, these will either be moved to PATARI or included in the public PATATO
    - Also ensures compatibility with some of my legacy hdf5 files

### Architecture Notes (v0.2, todo: update)

- **High-level design**: PATARI follows a controller + dock split with a task-controller pattern (see [architecture diagram](architecture.md))
  - `PatariController`: central session/app controller holding viewer state, scan data, and ROI geometry. Instantiates and coordinates feature controllers.
  - **Task Controllers** (all inherit from `TaskControllerBase`): domain-specific controllers that own their UI state, behavior, and signal lifecycle:
    - `ScanController`: scan lifecycle, loading, discovery, export, scan browser signals
    - `RoiController`: ROI table, shapes layer, labeling, colors, library management signals
    - `SegmentationController`: tissue segmentation, model selection, ROI-from-mask signals (+ model cleanup via `teardown()`)
    - `AnalysisController`: time analysis, histograms, spectra signals
    - `UnmixingController`: spectral unmixing, chromophore derived layers signals
  - `UIManager`: factory for dock creation and delegation to task controller signal wiring
- **Plugin startup path**: `_widget.py` initializes logging, resolves the active napari viewer, creates `PatariController`, and returns the Info dock widget.
- **UI construction path**: `UiManager.setup_docks()` creates dock widgets; `UiManager.connect_events()` delegates signal wiring to each controller's `bind_events()`.
- **Rendering/data IO**: `patato_bridge.py` handles PATATO <-> napari transformations, coordinate conversion, scale/FOV, and layer data construction.
- **Layer metadata**: PA layers rely on metadata keys such as `type`, `pa_kind`, `frames`, `timestamps`, `axis1_name`, `axis1_labels`, and `source_layer`. Many downstream features (info labels, analysis, export/reload symmetry) depend on these.
- **ROI model**: ROI stats are recomputed from `shapes_layer.events.data`. Initial ROI loading temporarily disconnects this handler to avoid repeated per-shape computation during initialization.
- **ROI feature configuration**: available ROI metrics and source fields are defined in a central feature registry and can be toggled in `config.json` via `annotation.roi_features`.
- **Visible columns**: the live and saved table views are column-filtered from that feature map, while saved/source columns keep a fixed order for consistent export schemas.
- **Live vs save computation**: for interactivity, live updates compute only currently visible live columns; on save/export, PATARI always computes the full feature set.
- **Coordinate conventions**: ROIs are represented in napari as `(y_mm, x_mm)` and converted to PATATO `(x_m, y_m)` at export/import. Conversion logic is in `patato_bridge.py`.
- **Data loading**: PATARI loads either iThera scan folders or HDF5 scans via PATATO readers and supports loading both individual scans and study folders.
- **Scan preference rule**: if both iThera and HDF5 exist for the same scan key, scan discovery prefers HDF5 (treated as previously converted version).
- **Export model**: HDF5 export is write-to-new-file only (no overwrite/append), cannot export back to iThera, and currently fails if target file already exists.
- **Export implementation**: export is a two-pass workflow (save base scan first, reopen, then write live ROIs and derived images). This is a workaround for PATATO reader/writer ownership where loaded data stays tied to its source file.
- **Derived layers**: unmixing outputs (unmixed, THb, sO2) are stored in `_derived_patato_objects` and exported with synchronized attributes so they can be reloaded as normal PA layers.
- **Sparse layers**: data that only contain selected frames are expanded to acquisition-frame indexing for viewer consistency; Frame id is carried in metadata and used on reload.
- **Current ROI position state**: `roi_position` metadata for manual ROIs is not fully synchronized yet. Future work includes fully synchronized shape specific metadata dict.
- **Segmentation models**: configured in `src/patari/data/segmentation_models.json` (ONNX path + model IO metadata).
- **Segmentation model training**: Code for training and evaluating different segmentation models can be found in [this repo](https://github.com/Mo-Sc/OA-US-Segmentation-Public/tree/us_segmentation_algos) (private, access after request).
- **Hidden features**: Reconstruction dock is currently disabled.
- **Logging behavior**: `PATARI_LOG_LEVEL` controls terminal log. `PATARI_GUI_LOG_LEVEL` controls napari GUI notification.
- **Compatibility note**: custom PATATO fork and import/export workarounds are currently required for some personal legacy datasets.


## License

Distributed under the terms of the [BSD-3] license,
"patari" is free and open source software

## Issues

If you encounter any problems, please [file an issue] along with a detailed description.

