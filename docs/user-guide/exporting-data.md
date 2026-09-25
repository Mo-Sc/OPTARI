# Exporting Data

Depending on the type of data that should be exported (scan data, tabular measurements, or single images/videos), OPTARI provides different export paths:


## Full Scan Export (HDF5)

Exports the loaded scan together with any drawn ROIs and derived layers (new reconstructions, unmixed chromophore maps, SO₂/THb)
into an HDF5 file that uses a custom, PATATO-inspired format carrying IPASC-conform metadata. This way, you can also convert proprietary vendor data (e.g. iThera `.msot`) into an open, shareable format by importing the scan into OPTARI and exporting it again. OPTARI cannot write back into the proprietary vendor format.

From the **Scan Browser** dock, click **Export HDF5** and choose a destination.

## IPASC Export

Click **Export IPASC** to write the scan's raw time series as a native
[IPASC](https://www.ipasc.science) file. After a successful export OPTARI reports how many IPASC minimal metadata fields the file contains.

!!! warning
    The IPASC format covers **raw time series data only**. Reconstructions, ultrasound, unmixed layers and ROIs are **not** included. Use the HDF5 export above to keep them.


!!! warning
    Both HDF5 exports always write to a **new** file. OPTARI never changes the source file, and if a file with the
    same name already exists at the destination, the export fails.

## Saved Analysis Table Import/Export (XLSX)

Click **Export XLSX** in the ROI dock to write the entire **Saved Analysis** table to a spreadsheet. The export always includes the full computed feature set, regardless of which columns are currently visible in the live view (see
[ROI Annotation](roi-annotation.md#roi-features)). The exported tables can be used for further statistical analysis.

The file contains two sheets: `roi_table` with the measurements, and `optari_meta` with additional info (tool version, operator, analysis ID, creation time, schema version), mirroring the `file_origin` attribute written by the HDF5 export.

The filename is `roi_data_<operator>_<analysis ID>_<timestamp>.xlsx`, built from the `OPERATOR` and `ANALYSIS_ID` settings (see [Configuration](../configuration/configuration-schema.md#general)) with timestamp matching the `creation_time` in the metadata sheet. 

The same file is written automatically as a backup after **every change** to the Saved Analysis table, one file per session: `~/.optari/autosave/roi_table_<date>T<time>_<pid>.xlsx`, named after the session's start time and process ID (the matching log file in `~/.optari/logs/` has the same name). If OPTARI closes unexpectedly, start it again and import the newest backup from before the crash. The newest 20 backups are kept.

Using the **Import XLSX** button, you can load a previously exported analysis file back into the **Saved Analysis** table, allowing you to continue an earlier analysis or continue on a different machine. Import **appends** to the current table, so analyses from several sessions or machines can be combined in one place. `roi_group_uid` keeps every row attributable to the ROI it was measured from. Identical rows are skipped. Files written by a OPTARI version with an incompatible table schema are rejected.

## ROI Analysis Plot Exports (PNG/...)

The **Analysis Plots** (histograms, spectra, time analysis) can be exported into PNG, CSV, or other image and data formats by right-clicking into the respective plot, choosing `Export`. The right-click menu also lets you configure the axes formatting and other plot options.

!!! tip
    To set the size and aspect ratio of the exported image, **undock the panel** using the button on the top left of the plot, left of the Refresh button. This allows you to freely resize the plot before exporting it. 

<!-- TODO screenshot: undocked analysis plot, with right click menu open -->

## Viewer Export (PNG/TIFF/MP4)

Clicking the **Export View** button in the **Scan Browser** dock exports whatever is currently displayed in the viewer, using the current settings regarding visibility, overlay, colormap, etc. 

Checking the `Include colorbars` box determines whether the colorbar should be displayed in the exported image. Views can be exported into `.png` or `.tiff` files.

Alternatively, the entire sequence of frames can be **exported into a `.mp4` video** by checking the `Video` box. You can also provide the frame rate (FPS) for the exported video. 

!!! tip
    To set the size and aspect ratio of the exported image or video, **resize the surrounding docks** on the left, right and bottom of the viewer using the 3 dots on each panel. These will determine the borders of the exported image / video.

!!! tip
    To set a specific, **fixed contrast limit for the exported video** instead of auto-scaling, see
    [FAQ](faq.md#how-do-i-set-a-fixed-contrast-limit-instead-of-auto-scaling).

<!-- TODO screenshot: export-viewer-dialog.png — viewer export dialog with contrast-limit and colorbar options -->
