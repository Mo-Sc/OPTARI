# Configuration Schema

Full reference for `~/.patari/config/config.json`. All fields are required unless noted, and every edit needs an app restart.

## `general`

| Field | Type | GUI | Meaning |
|---|---|---|---|
| `LOG_LEVEL` | string | Settings ▸ General | Terminal log verbosity (e.g. `"INFO"` / `"WARNING"`). |
| `GUI_LOG_LEVEL` | string | Settings ▸ General | Verbosity of messages surfaced as in-app napari notifications (e.g. `"INFO"` / `"WARNING"`). |
| `DEFAULT_PA_LAYER` | string | Settings ▸ Viewer | Name of the PA reconstruction layer selected by default when a scan loads. |
| `PA_FALLBACK_SCALE` | `[frame, z, x]` | Settings ▸ Viewer | Fallback mm/pixel scale for PA layers when FOV metadata is missing. |
| `DEFAULT_US_LAYER` | string | *hidden* | Name of the default US layer (not implemented, no effect). |
| `US_FALLBACK_SCALE` | `[frame, z, x]` | Settings ▸ Viewer | Fallback mm/pixel scale for US layers. |
| `DEFAULT_FRAME_INDEX` | int or `"motion"` | Settings ▸ Viewer | Fixed starting frame index, or `"motion"` for automatic motion-based frame selection (see [Automatic Frame Selection](../user-guide/viewer-and-navigation.md#automatic-frame-selection)). |
| `DEFAULT_CHANNEL_INDEX` | int | Settings ▸ Viewer | Default acquisition channel (as integer index). |
| `DEFAULT_PLAYBACK_FPS` | int | Settings ▸ Viewer | Frame playback speed. |
| `OPERATOR` | string | Settings ▸ General | Recorded in the `file_origin` attribute of exported HDF5 files. |
| `LAYER_COLOR_MAPS` | object | Settings ▸ Viewer | Colormap per layer type, e.g. `{"ultrasounds": "gray", "reconstructions": "viridis", "unmixed": "magma", "so2": "twilight_shifted", "thb": "inferno"}`. |

## `annotation`

| Field | Type | GUI | Meaning |
|---|---|---|---|
| `roi_colors` | list of hex strings | Settings ▸ ROI Table | Color palette cycled through for ROI shape colors in the viewer. |
| `roi_features` | object of `name → 0/1` | Settings ▸ ROI Table | Which ROI features are shown in the **Live Analysis table** (The saved/exported data always includes the full feature set regardless of this setting, see [ROI Annotation](../user-guide/roi-annotation.md#roi-features). |

Available feature names:

`roi_index`, `roi_group_id`, `mean`, `median`, `std`, `p10`, `p90`, `iqr`, `min`, `max`, `snr`, `n_pixels`,
`size_mm`, `src_layers`, `roi_type`, `study_folder`, `scan_folder`, `scan_name`, `frame`, `channel`, `roi_ts`,
`scan_ts`, `roi_centroid`, `filepath`.

A fixed set of columns (`roi_index`, `roi_group_id`, `study_folder`, `scan_folder`, `scan_name`,
`frame`, `channel`, `src_layers`, `roi_ts`, `roi_type`, `scan_ts`, `filepath`) is always included in the **Saved Analysis table**, independent of the live-visibility settings here, so saved records are always fully identifiable.

## `analysis`

| Field | Type | GUI | Meaning |
|---|---|---|---|
| `histogram_bins` | int | Settings ▸ General | Bin count for the [Histogram](../user-guide/temporal-and-spectral-analysis.md#histogram) plot. |

## `segmentation`

| Field | Type | GUI | Meaning |
|---|---|---|---|
| `default_model` | string | Settings ▸ Models | Model `id` (from `segmentation_models.json`) selected by default. See [Segmentation Models](segmentation-models.md). |



## Schema versioning

`config.json` contains a `schema_version` field.  If PATARI detects that your existing configuration was written by
an incompatible older version, it automatically:

1. Renames your existing `~/.patari` folder to a timestamped backup, `~/.patari_old_<timestamp>`.
2. Creates a fresh `~/.patari` from the packaged defaults.

Your previous settings, presets, downloaded models, and logs remain intact in the backup folder.