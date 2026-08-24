# FAQ

## My `config.json` edits aren't taking effect

Configuration is loaded once at startup — restart PATARI after editing any file under
`~/.patari/config/`. See [Configuration](../configuration/index.md).

## PATARI reset my settings after an update

If a new version ships an incompatible configuration schema, PATARI automatically archives your existing
`~/.patari` folder (to `~/.patari_old_<timestamp>`) and starts fresh from the new defaults, rather than crashing
on an incompatible file. Nothing is deleted — copy specific presets or settings back over from the backup folder
if needed. See [Configuration](../configuration/index.md#schema-versioning-and-migration).

## Deleting an ROI with the keyboard isn't working

Delete/Backspace only deletes an ROI when it's selected **in the viewer**, not when a row is selected in an
analysis table. See [ROI Annotation](roi-annotation.md#drawing-and-editing-rois).

## HDF5 export fails with a "file exists" error

Export always writes to a **new** file — it can't overwrite or append to an existing one. Choose a different
filename. See [Exporting Data](exporting-data.md#full-scan-export-hdf5).

## Automatic ROI placement looks wrong for my scan

Segmentation quality depends on how close your data is to the model's training distribution. New anatomical sites
or scanner types may need a fine-tuned model — see [Segmentation Models](../configuration/segmentation-models.md)
for how models are registered, and consider filing an issue with an example scan.

## Can I measure distances in PATARI?

Yes — select the line shape (shortcut `L`) and draw it along the distance you want to measure. The `size_mm`
feature in the Live Analysis table shows its length in millimeters. See
[ROI Annotation](roi-annotation.md#drawing-and-editing-rois).

## How do I set a fixed contrast limit instead of auto-scaling?

Select the layer in the Layer List, click the auto-contrast `continuous` button in the layer controls panel, then
click `once`. The contrast limits are now constant for that layer — useful for consistent viewing across
frames/channels, and for exported images or video. To set specific values manually instead, right-click the
`contrast limits` slider.

## Something else

Search or open an issue on [GitHub](https://github.com/Mo-Sc/PATARI/issues) — bug report, feature request, and
documentation-gap templates are all available there.
