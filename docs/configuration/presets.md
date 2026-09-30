# Presets

Reusable processing configuration, stored as one JSON file per preset under `~/.optari/config/presets/<category>/`.

Presets aren't part of the Settings dialog. Instead, each category is managed from its own dock's
**Save Preset** / **Remove Preset** controls.

## ROI presets (`presets/roi/`)

A saved ROI template. The `geometry` block is the same representation OPTARI uses for the saved analysis table and for HDF5 export: vertices in PATATO coordinates, metres, origin at the image centre, so the shape does not depend on the field of view it was drawn on. `tissue_class` can be used for automatic placement, by setting it to the respective class in an available segmentation map.

`source_fov_m` records the field of view the template was drawn on, in metres. It is needed to re-place the template proportionally when it is applied to a scan with a different field of view,

`placement` describes the way the template is positioned:

| Value | Meaning |
| --- | --- |
| `static` | Put it at its saved coordinates, scaled to the scan's field of view. |
| `auto` | Anchor it onto the segmentation class named by `geometry.tissue_class`. Needs a segmentation map. |

Selecting an `auto` preset in the Annotation dock falls back to `static` when the current scan has no matching segmentation, so it never arms a placement bound to fail. A batch run takes the preset at its word and records the failure instead.

```json title="clinical_ellipse_10x2mm.json"
{
  "description": "Ellipse of size 10x2mm similar to 2nd UK PAD study",
  "created": "2026-04-08T12:49:27.693948+00:00",
  "source_fov_m": [0.04, 0.04],
  "placement": "static",
  "geometry": {
    "verts_m": [[-0.005, 0.0], [0.005, 0.0], [0.005, -0.002], [-0.005, -0.002]],
    "kind": "ellipse",
    "tissue_class": "muscle"
  }
}
```

See [ROI Annotation](../user-guide/roi-annotation.md#roi-presets) for how to create these from the GUI.

## Reconstruction presets (`presets/reconstruction/`)

Reconstruction algorithm and filtering parameters, passed through to PATATO and DeepMB.

```json title="backproject_clinical.json"
{
  "FILTER_HIGH_PASS": null,
  "FILTER_LOW_PASS": 7500000.0,
  "IRF": true,
  "HILBERT_TRANSFORM": true,
  "ENVELOPE_DETECTION": false,
  "INTERPOLATE_TIME": 3,
  "INTERPOLATE_DETECTORS": 2,
  "PREPROCESSING_ALGORITHM": "Standard Preprocessor",
  "RECONSTRUCTION_FIELD_OF_VIEW_X": 0.04,
  "RECONSTRUCTION_FIELD_OF_VIEW_Z": 0.04,
  "RECONSTRUCTION_NX": 400,
  "RECONSTRUCTION_NZ": 400,
  "RECONSTRUCTION_PARAMS": {},
  "RECONSTRUCTION_ALGORITHM": "Reference Backprojection",
  "RECONSTRUCTION_SPEED_OF_SOUND": 1500
}
```

## Unmixing presets (`presets/unmixing/`)

Wavelength range, chromophore selection, and derived-parameter options.

```json title="haemoglobin.json"
{
  "RESOLUTION_REDUCE": 1,
  "WAVELENGTH_RANGE": [700, 900],
  "SPECTRA": ["Hb", "HbO2"],
  "SO2": true,
  "THB": true,
  "SUFFIX": ""
}
```

`SPECTRA` entries reference PATATO's reference chromophore spectra (`H2O`, `HbO2`, `Hb`, `ICG`, `Lipid`,
`Melanin`) for a wavelength range from 700 to 1000nm. (Upcoming: Spectra up to 1300nm)

## Segmentation presets (`presets/segmentation/`)

Which model/class to run, and how to place an ROI from the resulting mask (see
[Segmentation Models](segmentation-models.md) for the model registry referenced by `model_id`).

```json title="muscle.json"
{
  "model_id": "c_unet_gastrocnemius-transverse",
  "selected_class_ids": [3],
  "roi_class_id": null,
  "roi_shape": "ellipse",
  "roi_width_mm": null,
  "roi_height_mm": null,
  "roi_top_margin_mm": null
}
```

## Batch presets (`presets/batch/`)

An entire analysis applied to a whole dataset. Unlike the other categories a batch preset holds no processing settings of its own, and isntead it **references** the presets above. See the [Batch Processing](../user-guide/batch-processing.md).

Batch presets are edited in their own window (**OPTARI → Batch Processing…**), which shows the JSON, an **Apply** button to re-check it, and **Save Preset** / **Remove Preset**.

```json title="clinical_muscle_roi.json"
{
  "description": "Reconstruct, segment, unmix and place the clinical muscle ROI.",
  "steps": {
    "reconstruction": "backproject_ithera",
    "segmentation": "muscle_poly",
    "unmixing": "haemoglobin",
    "roi": "clinical_ellipse_10x2mm_Muskel1"
  },
  "source": null,
  "frame": "motion",
  "measure": {
    "layers": "analysis",
    "all_channels": true,
    "all_frames": false
  },
  "outputs": {
    "xlsx": true,
    "hdf5": false,
    "overlay_png": true,
    "overlay_layer": null
  }
}
```

### `steps`

Each entry is a **preset name only**. Omit a step to skip it.

| Key | Preset category | Notes |
| --- | --- | --- |
| `reconstruction` | `presets/reconstruction/` | Runs first. Omit to work on a reconstruction already in the file. |
| `segmentation` | `presets/segmentation/` | Required by an ROI preset whose `placement` is `auto`. |
| `unmixing` | `presets/unmixing/` | Wavelengths resolve per scan, so a scan missing them fails on its own. |
| `roi` | `presets/roi/` | The ROI placed and measured. Its `placement` decides static or auto. |

An empty `"steps": {}` with `outputs.hdf5` on is a pure vendor-to-OPTARI-HDF5 converter.

### `source`

A layer-name **prefix** picking the one reconstruction the run analyses. One batch run works on one reconstruction, which produces one unmixing, so a scan holding several reconstructions still produces one analysis.

| Value | Meaning |
| --- | --- |
| `null` with a `reconstruction` step | The reconstruction this plan just produced. |
| `null` with no `reconstruction` step | The scan's default OA layer (see `DEFAULT_PA_LAYER`). Flagged as a warning, since it is implicit. |
| `"Recon: iThera"` | The layer whose name starts with this. A scan without one fails and the run continues. |

### `frame`

The anchor frame: where a `static` ROI's shape is drawn, and which frame the overlay PNG and the report's `analysis_frame` column come from. It does **not** decide how many frames get analysed, which is selected by `measure.all_frames` below.

| Value | Meaning |
| --- | --- |
| `"motion"` (default) | That scan's lowest-motion frame. Requires ultrasound. A raw time series (eg. IPASC) has none and falls back to frame 0. |
| an integer | That frame number. A scan without it fails. |

### `measure`

How wide the measurement reaches. Mirrors the **Include all …** boxes in the Annotation dock.

| Key | Values | Meaning |
| --- | --- | --- |
| `layers` | `"analysis"` (default), `"all_pa"` | `analysis` measures the `source` reconstruction plus what this run unmixed from it. `all_pa` measures every OA layer in the scan, including reconstructions the plan did not make. |
| `all_channels` | `true` (default), `false` | Every channel, or just the default one. |
| `all_frames` | `false` (default), `true` | Every frame, overriding `frame` above. Reconstruction, segmentation and measurement all run over every frame instead of just the anchor frame. The ROI is placed on each frame (re-anchored per frame for `auto` placement) and measured there. `frame` still picks the overlay/report anchor. |

### `outputs`

| Key | Values | Meaning |
| --- | --- | --- |
| `xlsx` | `true` (default), `false` | Write `batch_roi_table.xlsx`, the measurement table. |
| `hdf5` | `false` (default), `true` | Write each scan to `hdf5/<Study>/<Scan>.hdf5`. |
| `ipasc` | `false` (default), `true` | Write each scan's raw time series to `ipasc/<Study>/<Scan>_ipasc.hdf5` (see [Exporting Data](../user-guide/exporting-data.md#ipasc-export)). |
| `overlay_png` | `true` (default), `false` | Write one viewer screenshot per scan to `overlays/`. |
| `overlay_layer` | `null` (default), a layer-name prefix | Which layer the overlay shows. `null` uses the last one the run produced (sO₂ if unmixing made it, else Unmixed, else the reconstruction). A prefix matching nothing fails that scan. |

`batch_report.xlsx` and the run log are always written.

## Sharing presets

Any preset is just a JSON file that can be copied into another machines `~/.optari/config/presets/<category>/` to reuse the same configuration across workstations.
