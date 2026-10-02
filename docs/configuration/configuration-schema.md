# Configuration Schema

Full reference for `~/.optari/config/config.json`. All fields are required unless noted, and every edit needs an app restart.

## `general`

| Field | Type | GUI | Meaning |
|---|---|---|---|
| `LOG_LEVEL` | string | Settings ▸ General | Terminal log verbosity (e.g. `"INFO"` / `"WARNING"`). |
| `GUI_LOG_LEVEL` | string | Settings ▸ General | Verbosity of messages surfaced as in-app napari notifications (e.g. `"INFO"` / `"WARNING"`). |
| `DEFAULT_PA_LAYER` | string | Settings ▸ Viewer | Name of the OA reconstruction layer selected by default when a scan loads. |
| `PA_FALLBACK_SCALE` | `[frame, z, x]` | Settings ▸ Viewer | Fallback mm/pixel scale for OA layers when FOV metadata is missing. |
| `DEFAULT_US_LAYER` | string | *hidden* | Name of the default US layer (not implemented, no effect). |
| `US_FALLBACK_SCALE` | `[frame, z, x]` | Settings ▸ Viewer | Fallback mm/pixel scale for US layers. |
| `DEFAULT_FRAME_INDEX` | int or `"motion"` | Settings ▸ Viewer | Fixed starting frame index, or `"motion"` for automatic motion-based frame selection (see [Automatic Frame Selection](../user-guide/viewer-and-navigation.md#automatic-frame-selection)). |
| `DEFAULT_CHANNEL_INDEX` | int | Settings ▸ Viewer | Default acquisition channel (as integer index). |
| `DEFAULT_PLAYBACK_FPS` | int | Settings ▸ Viewer | Frame playback speed. |
| `OPERATOR` | string | Settings ▸ General | Who is running the analysis. Will be recorded in the exported HDF5 and Excel files. |
| `ANALYSIS_ID` | string | Settings ▸ General | Name of the analysis, e.g. a study or cohort name. Will be recorded in the exported HDF5 and Excel files. |
| `LAYER_COLOR_MAPS` | object | Settings ▸ Viewer | Colormap per layer type, e.g. `{"ultrasounds": "gray", "reconstructions": "viridis", "unmixed": "magma", "so2": "twilight_shifted", "thb": "inferno"}`. |
| `DEFAULT_VISIBLE_DOCKS` | object of `label → 0/1` | Settings ▸ Docks | Which panels are visible when OPTARI starts (see [OPTARI ▸ Docks](index.md)). A missing label defaults to visible. Applies on every launch, overriding napari's own remembered window layout. |

## `annotation`

| Field | Type | GUI | Meaning |
|---|---|---|---|
| `roi_colors` | list of hex strings | Settings ▸ ROI Table | Color palette cycled through for ROI shape colors in the viewer. |
| `roi_features` | object of `name → 0/1` | Settings ▸ ROI Table | Which ROI features are shown in the **Live Analysis table** (The saved/exported data always includes the full feature set regardless of this setting, see [ROI Annotation](../user-guide/roi-annotation.md#roi-features). |
| `show_track_id` | bool | Settings ▸ Viewer | Label ROI shapes as `roi_id/track_id` instead of just `roi_id`. |
| `roi_label_size` | int | Settings ▸ Viewer | Text size of the ROI shape labels in the viewer. |

Available feature names:

`roi_id`, `track_id`, `roi_group_uid`, `mean`, `median`, `std`, `p10`, `p90`, `iqr`, `min`, `max`, `snr`,
`n_pixels`, `size_mm`, `intensity_filter`, `filter_min`, `filter_max`, `src_layer`, `kind`, `study_folder`, `scan_folder`, `scan_name`, `frame`, `channel`,
`roi_ts`, `scan_ts`, `roi_centroid`, `roi_geometry`, `filepath`.

A fixed set of columns (`roi_id`, `track_id`, `roi_group_uid`, `study_folder`, `scan_folder`, `scan_name`,
`frame`, `channel`, `src_layer`, `roi_ts`, `kind`, `scan_ts`, `filepath`) is always included in the **Saved Analysis table**, independent of the live-visibility settings here, so saved records are always fully identifiable.

OPTARI identifies an ROI at three scopes. `roi_id` is one shape on one frame, a per-session counter, and it is the number drawn on the shape in the viewer. `track_id` links the copies of one ROI across frames within a session. `roi_group_uid` is the group's unique identity.

`src_layer` names the image layer an ROI was measured on. `roi_geometry` is a JSON dictionary holding the ROI
vertices in PATATO coordinates (metres, origin at the image centre) together with its shape kind, tissue class
and source. It uses the same field of view-independent representation as [ROI presets](presets.md#roi-presets-presetsroi) and the HDF5 ROI export, so a saved ROI should stay anatomically correct if it is later restored onto a reconstruction with a different FOV. It is
exported by default but hidden from the tables unless enabled here.

## `analysis`

| Field | Type | GUI | Meaning |
|---|---|---|---|
| `histogram_bins` | int | Settings ▸ General | Bin count for the [Histogram](../user-guide/temporal-and-spectral-analysis.md#histogram) plot. |

## `segmentation`

| Field | Type | GUI | Meaning |
|---|---|---|---|
| `default_model` | string | Settings ▸ Models | Model `id` (from `segmentation_models.json`) selected by default. See [Segmentation Models](segmentation-models.md). |



## Schema versioning

`config.json` contains a `schema_version` field.  If OPTARI detects that your existing configuration was written by
an incompatible older version, it automatically:

1. Renames your existing `~/.optari` folder to a timestamped backup, `~/.optari_old_<timestamp>`.
2. Creates a fresh `~/.optari` from the packaged defaults.

Your previous settings, presets, downloaded models, and logs remain intact in the backup folder.