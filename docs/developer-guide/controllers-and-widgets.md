# Controllers & Widgets

## Widgets (`widgets/`)

- Each dock is created by a `create_*_dock()` factory returning a dataclass of widget
  references (`QLineEdit`, `QComboBox`, pyqtgraph `PlotWidget`, `magicgui.widgets.Table`, ...).
- Widgets hold no logic and doesnt wire their own signals, which is done by `UiManager.connect_events()`

## `TaskControllerBase`

Controllers share one base class: `controllers/base.py`:

1. `_params_from_ui()` — reads the dock into a `*Params` dataclass, raising `ValueError` if the run cannot be set up.
2. `prepare(params) -> BackgroundStep`: validates and returns the work to run.
3. `publish(result, params)`: adds the resulting layer(s) and returns the "Finished: ..." text.

Batch mode builds `params` from a preset instead of the dock and calls the same `prepare`/`publish`.

## Controllers

| Controller | Owns |
| --- | --- |
| `ScanController` | Study/scan discovery, loading a scan (iThera/HDF5/IPASC), building napari layers, frame selection (incl. motion scoring). |
| `RoiController` | The ROI shapes layer, live/saved analysis tables, ROI presets and placement. See [The ROI System](roi-system.md). |
| `SegmentationController` | The ONNX model registry, running inference, the segmentation `Labels` layer, and automatic ROI-from-mask placement. |
| `ReconstructionController` | Reconstruction presets and running PATATO's backprojection/DeepMB pipelines. |
| `UnmixingController` | Unmixing presets and running PATATO's spectral unmixing (+ THb/sO2). |
| `AnalysisController` | Time-series, histogram and spectral plots (pyqtgraph) over selected ROIs. |
| `ViewerExportController` | Rendering a layer or the current view to PNG/TIFF/video. |

A controller reaches another only through `self.patari_controller.<name>_ctrl`, never by
holding a direct reference to it.

## `patato_bridge.py`

Handles conversion between PATATO objects and napari layers/coordinates. No controller
reads a PATATO array or writes an HDF5 attribute directly outside `patato_bridge.py` and
`io/export_pipeline.py`.

!!! note "Export always creates a new file"
    Exporting a hdf5 always creates a new file and cannot append to an existing file.
    Therefore the export has to have a different filename or location.

!!! note "Export always overwrites"
    `pa_data.save_hdf5()` already copies whatever the *source* file had (ROIs, segmentation) into the export, but a live patari edit this session (a new/edited ROI shape, a run segmentation) is never part of `pa_data`'s reader, so it can't be part of that automatic copy. `_write_rois` and `_write_derived_data` (`io/export_pipeline.py`) run *after* `save_hdf5()` and explicitly delete+rewrite those datasets from the current state. In the common case (nothing changed since load) this rewrites identical data.
