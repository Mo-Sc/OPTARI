# FAQ

## On Windows, the first start fails with "Could not install packages due to an OSError"

The error ends with a hint about **Windows Long Path support**. On its first start, OPTARI installs its packages
into your user folder, and one of them contains a file whose full path exceeds the 260 characters Windows allows
by default. This happens more often with long user names.

The quickest fix moves the installation to a shorter folder and needs no administrator rights. First run
`UNINSTALL_WINDOWS.bat` from the OPTARI folder to remove the half-finished installation. Then open a Command Prompt
and run:

```bat
setx PYAPP_INSTALL_DIR_OPTARI "%USERPROFILE%\optari"
```

Start OPTARI again by double-clicking it. It now installs into `C:\Users\<your name>\optari`.

Alternatively, an administrator can lift the path limit for the whole computer. In PowerShell, opened with
**Run as administrator**:

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

## My `config.json` edits or settings changes aren't taking effect

Configuration is loaded once at startup — restart OPTARI after editing any file under
`~/.optari/config/`. See [Configuration](../configuration/index.md).

## Deleting an ROI with the keyboard isn't working

On MacOS, Delete/Backspace only deletes an ROI when it's selected **in the viewer**, not when a row is selected in an
analysis table. See [ROI Annotation](roi-annotation.md#drawing-and-editing-rois).

## HDF5 export fails with a "file exists" error

Export always writes to a **new** file, it can't overwrite or append to an existing one. Choose a different
filename. See [Exporting Data](exporting-data.md#full-scan-export-hdf5).

## Can I measure distances in OPTARI?

Yes — select the line shape (shortcut `L`) and draw it along the distance you want to measure. The `size_mm`
feature in the Live Analysis table shows its length in millimeters. See
[ROI Annotation](roi-annotation.md#drawing-and-editing-rois).

## How do I set a fixed contrast limit instead of auto-scaling?

OA layers open with the auto-contrast `continuous` button switched on, which rescales every frame and channel
to its own range. Select the layer in the Layer List and click `once` in the layer controls panel. This switches
`continuous` off and keeps the current contrast limits constant for that layer. To set specific values manually instead, right-click the
`contrast limits` slider.

## Why can't I see ROIs overlaid on images in grid mode?

In grid mode napari draws every cell as a separate view, and a layer can only live in one cell. OPTARI shows one layer per cell,
so the ROIs layer gets a cell of its own and can't be drawn on top of the images next to it. This is a napari limitation: there is
currently no way to show one layer in several cells.

**Workaround:** right-click the grid mode icon below the layer list and set `stride` to `2` (or `-2`). Every cell then overlays
two consecutive layers of the layer list. Move the ROIs layer directly above the image you want to annotate. Keep in mind that the
pairs are counted over the whole layer list, including hidden layers, so they shift whenever a layer is added (for example after
unmixing) and only one image can be paired with the ROIs. OPTARI resets the stride to one layer per cell on the next start.

**Known issue with napari 0.9.1:** with a stride other than `1`/`-1`, unhiding a layer while grid mode is on can raise
`TypeError: unsupported operand type(s) for /: 'float' and 'NoneType'`, and the layer may not appear even though it is ticked in
the layer list. In this mode napari detaches the colorbar of a hidden layer from the canvas. When the layer is shown again, napari
refreshes the image before it reattaches the colorbar, and the `continuous` auto-contrast of OA layers changes the contrast limits
during that refresh. The colorbar then tries to redraw its tick labels without a canvas and fails. To avoid it, leave grid mode
(`Ctrl+G` / `Cmd+G`), unhide the layer and switch grid mode back on, or click `once` in the auto-contrast controls of the layer
before unhiding it.
