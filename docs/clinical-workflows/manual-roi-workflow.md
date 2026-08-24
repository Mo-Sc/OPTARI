# Clinical Study with Manual ROI Annotation

Simple workflow: extracting ROI intensities over multiple scans from manually drawn ROIs. No unmixing, just one wavelength.

1. **Load the first scan** you want to annotate from the Scan Browser.
2. **Navigate** to the frame/wavelength you want to measure, or trust the default motion-based frame selection.
3. **Draw the ROI.** Select the ROIs layer, press `E` for an ellipse (or `R`/`P` for a rectangle/polygon), and
   drag it over the target area.
4. **Check the Live Analysis table** — it updates immediately with mean intensity and the other configured
   statistics for the region you just drew.
5. **Adjust** the ROI's position or size if needed; the table keeps recomputing live.
6. **Save it as a template.** In the Annotation dock's ROI Presets list, click **Save Preset** and name it (e.g. by
   anatomical region or study name) so the same shape can be reused on other scans in the study.
7. **Save the measurement.** Press `Shift+Ctrl+S` (`Shift+Cmd+S`) to freeze this ROI's data into the Saved Analysis table.
8. **Repeat.** Select the next scan from the Scan Browser (or open a new folder and select a scan). Reuse the saved ROI preset by double-clicking it in the ROI Presets list.
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

**Related pages:** [ROI Annotation](../user-guide/roi-annotation.md) ·
[Keyboard Shortcuts](../user-guide/keyboard-shortcuts.md) · [Presets](../configuration/presets.md)
