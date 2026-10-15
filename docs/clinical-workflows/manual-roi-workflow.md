# Clinical Study with Manual ROI Annotation

A simple workflow: extracting ROI intensities over multiple scans from manually drawn ROIs, saving ROI presets and exporting saved data to .xlsx files. No unmixing or segmentation.

**Target user:** A medical scientist conducting a typical clinical OA study, similar to [doi.org/10.1038/s43856-025-00801-1](https://doi.org/10.1038/s43856-025-00801-1). Study subjects are annotated scan by scan. On each scan, an ROI is drawn in the target tissue, often the muscle. The pixel intensities within this region are summarized using statistical features and collected across scans. Parameters like ROI shape and size should remain fixed throughout the analysis. Finally, the collected data is exported into a spreadsheet for subsequent analysis.

<div style="width: 100%; max-width: 100%; aspect-ratio: 16 / 9;">
  <iframe 
    src="https://www.youtube-nocookie.com/embed/_lAqpUNXjyA"
    title="OPTARI demo: manual ROI workflow"
    style="width: 100%; height: 100%; border: 0;"
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" 
    referrerpolicy="strict-origin-when-cross-origin" 
    allowfullscreen>
  </iframe>
</div>

**Related pages:** [ROI Annotation](../user-guide/roi-annotation.md) ·
[Keyboard Shortcuts](../user-guide/keyboard-shortcuts.md) · [Presets](../configuration/presets.md)
