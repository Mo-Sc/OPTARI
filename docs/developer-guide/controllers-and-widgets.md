# Controllers & Widgets

## Widgets (`widgets/`)

- Each dock is created by a `create_*_dock()` factory returning a dataclass of widget
  references (`QLineEdit`, `QComboBox`, pyqtgraph `PlotWidget`, `magicgui.widgets.Table`, ...).
- Docks hold no application logic, only behaviour local to their widgets (remembering checked scans,
  formatting a table, etc)

## `TaskControllerBase`

Controllers share one base class: `controllers/base.py`:

1. `_params_from_ui()` — reads the dock into a `*Params` dataclass, raising `ValueError` if the run cannot be set up.
2. `prepare(params) -> BackgroundStep`: validates and returns the work to run.
3. `publish(result, params)`: adds the resulting layer(s) and returns the "Finished: ..." text.

Batch mode builds `params` from a preset instead of the dock and calls the same `prepare`/`publish`.

## Controllers

| Controller | Owns |
| --- | --- |
| `ScanController` | The Scan Browser's study, loading a scan (iThera/HDF5/IPASC), building napari layers, frame selection (incl. motion scoring). Finding studies and scans is in `optari/io/discovery.py`, shared with batch mode. |
| `RoiController` | The ROI shapes layer, live/saved analysis tables, ROI presets and placement. See [The ROI System](roi-system.md). |
| `SegmentationController` | The ONNX model registry, running inference, the segmentation `Labels` layer, and automatic ROI-from-mask placement. |
| `ReconstructionController` | Reconstruction presets and running PATATO's backprojection/DeepMB pipelines. |
| `UnmixingController` | Unmixing presets and running PATATO's spectral unmixing (+ THb/sO2). |
| `AnalysisController` | Time-series, histogram and spectral plots (pyqtgraph) over selected ROIs. |
| `ViewerExportController` | Rendering a layer or the current view to PNG/TIFF/video. |

A controller reaches another only through `self.optari_controller.<name>_ctrl`, never by
holding a direct reference to it.

## `patato_bridge.py`

Handles conversion between PATATO objects and napari layers/coordinates. HDF5 attributes are
written only there and in `io/export_pipeline.py`. Controllers read PATATO arrays through `patato_bridge.py`

!!! note "Export creates a new file, unless it is the loaded scan"
    `export_scan_to_hdf5` always creates a new file. When the destination chosen for **Save HDF5** is the loaded
    scan file itself (confirmed through the file dialog's overwrite prompt), `ScanController` calls
    `save_scan_into_source` instead. It opens the loaded OPTARI HDF5 read-write and runs the same `_write_rois` and
    `_write_derived_data` on it, so the session's `derived_patato_objects` are added, each replacing a stored
    dataset of the same layer name, and nothing else is deleted. h5py cannot reopen a file read-write that this
    process holds read-only, so `ScanController` resets the scan before writing and reloads it afterwards.

!!! note "Exports run in the background"
    `export_scan_to_hdf5`, `save_scan_into_source` and `export_scan_to_ipasc` are generators run as background
    steps (`start_task` in the GUI, a yielded `BackgroundStep` in batch mode). They never read the viewer or a
    controller: `ScanController.export_snapshot()` copies what they write (OPTARI ROIs, derived images, segmentation mask,
    clinical metadata edits) on the main thread first, so ROIs edited during a running export do not leak into it.

!!! note "Export always overwrites"
    `pa_data.save_hdf5()` already copies whatever the *source* file had (ROIs, segmentation, clinical metadata) into the export, but a live optari edit this session (a new/edited ROI shape, a run segmentation, an edited clinical metadata field) is never part of `pa_data`'s reader, so it can't be part of that automatic copy. `_write_rois` and `_write_derived_data` (`io/export_pipeline.py`) run *after* `save_hdf5()` and explicitly delete+rewrite those datasets from the current state. In the common case (nothing changed since load) this rewrites identical data.
