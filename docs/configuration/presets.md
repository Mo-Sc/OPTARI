# Presets

Reusable processing configuration, stored as one JSON file per preset under `~/.patari/config/presets/<category>/`.

Presets aren't part of the Settings dialog. Instead, each category is managed from its own dock's
**Save Preset** / **Remove Preset** controls.

## ROI presets (`presets/roi/`)

A saved ROI template. The `geometry` block is the same representation PATARI uses for the saved analysis table and for HDF5 export: vertices in PATATO coordinates, metres, origin at the image centre, so the shape does not depend on the field of view it was drawn on. `tissue_class` can be used for automatic placement, by setting it to the respective class in an available segmentation map.

`source_fov_m` records the field of view the template was drawn on, in metres. It is needed to re-place the template proportionally when it is applied to a scan with a different field of view,

```json title="clinical_ellipse_10x2mm.json"
{
  "description": "Ellipse of size 10x2mm similar to 2nd UK PAD study",
  "created": "2026-04-08T12:49:27.693948+00:00",
  "source_fov_m": [0.04, 0.04],
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
  "model_id": "unet_msot_2_ta",
  "selected_class_ids": [3],
  "roi_class_id": null,
  "roi_shape": "ellipse",
  "roi_width_mm": null,
  "roi_height_mm": null,
  "roi_top_margin_mm": null
}
```

## Sharing presets

Any preset is just a JSON file that can be copied into another machines `~/.patari/config/presets/<category>/` to reuse the same configuration across workstations.
