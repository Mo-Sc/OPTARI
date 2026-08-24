# Clinical Study with Automatic ROI Placement

Semi-automated workflow, including spectral unmixing and automatic ROI placement.

1. **Load the first scan** from the Scan Browser.
2. **Choose Presets**. Select or modify the presets in the Segmentation and Unmixing docks.
3. **Create a segmentation map.** Press `Shift+Ctrl+T` (`Shift+Cmd+T`) to run segmentation using the selected preset.
4. **Setup an automatic ROI.** From the Segmentation dock, generate an ROI from the segmentation mask by selecting class ID, shape and size. 
5. **Save the ROI.** Add the ROI to the ROI presets list by clicking `Save Preset` in the Annotation dock. Check the `Include all layers` and `Include all channels` boxes. 
6. **Unmix the scan.** Press `Shift+Ctrl+U` (`Shift+Cmd+U`) to run spectral unmixing with the selected preset.
7. **Save the measurement.** Press `Shift+Ctrl+S` (`Shift+Cmd+S`) to freeze this ROI's data across all layers and channels into the Saved Analysis table.
8. **Repeat.** Select the next scan from the Scan Browser (or open a new folder and select a scan); Press `Shift+Ctrl+T` (`Shift+Cmd+T`) to segment the target tissue; Double-click the saved ROI preset for automatic placement; Press `Shift+Ctrl+U` (`Shift+Cmd+U`) to add unmixed layers; Press `Shift+Ctrl+S` (`Shift+Cmd+S`) to save the ROI data to the Saved Analysis table.
9. **Export.** Once every scan has been annotated, export the full Saved Analysis table to XLSX (see [Exporting Data](../user-guide/exporting-data.md)).

<!-- TODO replace demo video by actual video -->

<div style="width: 100%; max-width: 100%; aspect-ratio: 16 / 9;">
  <iframe 
    src="https://www.youtube.com/embed/I473cUAly8A?si=T6Wb-d-fdZlnjBDF" 
    title="YouTube video player" 
    style="width: 100%; height: 100%; border: 0;"
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" 
    referrerpolicy="strict-origin-when-cross-origin" 
    allowfullscreen>
  </iframe>
</div>

!!! warning
    Placeholder video. Will be replaced.

**Related pages:** [Segmentation](../user-guide/segmentation.md) ·
[Unmixing](../user-guide/unmixing.md) ·
[Keyboard Shortcuts](../user-guide/keyboard-shortcuts.md)