# User Guide Overview

PATARI's window is built from napari's dock system around a central image viewer:

| Position | Docks |
|---|---|
| Left | **Layer List** and **Layer Controls** — napari's built-in docks for the loaded US, PA, and annotation layers |
| Right (tabbed) | **Scan Browser**, **Annotation**, **Segmentation**, **Unmixing**, **Reconstruction** |
| Bottom (tabbed) | **ROI Tables**, **Time Analysis**, **Histogram**, **Spectrum** |
| Center | The napari viewer — displays US, PA, and annotation layers |

In addition, there is an **Info** dock (showing metadata for the current scan/slice) that floats as its own window rather than docking to a fixed position.

You can drag dock tabs to rearrange them, and napari remembers your layout between sessions.

![UI Overview](../assets/screenshots/placeholders/ss_overview.png)

## Pages in this guide

1. [Viewer & Navigation](viewer-and-navigation.md) — the Scan Browser, Layer List, and moving through frames and
   wavelengths.
2. [ROI Annotation](roi-annotation.md) — drawing ROIs, the Live/Saved tables, and the ROI Library.
3. [Temporal & Spectral Analysis](temporal-and-spectral-analysis.md) — plotting ROI intensity over time and
   wavelength, and viewing intensity histograms.
4. [Segmentation](segmentation.md) — automatic tissue detection and automated ROI placement.
5. [Reconstruction](reconstruction.md) — running PATATO reconstruction presets from the GUI.
6. [Unmixing](unmixing.md) — spectral unmixing and derived SO₂/THb parameters.
7. [Exporting Data](exporting-data.md) — HDF5, spreadsheet, and image/video export.
8. [Keyboard Shortcuts](keyboard-shortcuts.md) — the full shortcut reference.
9. [FAQ](faq.md) — common questions about everyday usage.

For examples of how we used PATARI in clinical PA studies, see [Sample Workflow](../clinical-workflows/manual-roi-workflow.md).
