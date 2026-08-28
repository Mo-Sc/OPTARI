# Configuration

PATARI's settings are stored in `~/.patari/config/` as human-readable JSON.

## Editing settings from the GUI

Most application settings are editable from **PATARI → Settings…** in the menu bar: operator name,
log levels, viewer defaults, layer colormaps, Live Analysis table columns and ROI colors The dialog also shows where the config, presets, models and logs are stored, and whether each segmentation model's weights are installed.

Settings are read once at startup, so **changes take effect after restarting PATARI**.

Reconstruction, unmixing, ROI and segmentation presets are not edited here. This is done from the respective docks.

## Menu bar (TODO: This goes into developer guide notes somewhere)

PATARI hides the napari menu entries it cannot support: the Layers and Plugins menus, and the
File entries that load arbitrary data into the viewer, which would bypass the Scan Browser.
Set `PATARI_FULL_MENUS=1` before launching to restore the complete napari menu bar.

!!! warning "Coming soon"
    This section is being rewritten and isn't ready yet. In the meantime, PATARI's configuration lives in
    `~/.patari/config/` as plain, human-readable JSON files — browse the
    [source on GitHub](https://github.com/Mo-Sc/PATARI) for the current config schema.
