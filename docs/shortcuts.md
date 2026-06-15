# PATARI Keyboard Shortcuts Guide

Using keyboard shortcuts can significantly speed up your analysis workflow. This is a short list containing some of the most useful shortcuts for traditional MSOT analysis, like navigating the viewer and annotating ROIs. A complete list of built-in napari shortcuts can be found and modified by clicking **`napari` ➔ `Preferences` ➔ `Shortcuts`**. 

In the future, we can extend this list with custom shortcuts, depending on the analysis protocol.



## Navigation & Layer Control

Browse through scan data, frames, and toggle between different image layers.

| Action | Windows / Linux | macOS |
| :--- | :--- | :--- |
| **Step through Frames / Wavelengths** | `Left` / `Right` Arrow | `Left` / `Right` Arrow |
| **Switch Active Slider** (Frame vs. Wavelength) | `Alt` + `Up` / `Down` Arrow | `Option` + `Up` / `Down` Arrow |
| **Switch Layer (Sequential)** | `Ctrl` + `Up` / `Down` Arrow | `Cmd` + `Up` / `Down` Arrow |
| **Switch Layer & Hide All Others** (Solo View) | `Shift` + `Alt` + `Up` / `Down` Arrow | `Shift` + `Option` + `Up` / `Down` Arrow |
| **Toggle Active Layer Visibility** (Hide/Show) | `V` | `V` |
| **Toggle Grid Mode** | `Ctrl` + `G` | `Cmd` + `G` |
| **Reset View to Original State** | `Ctrl` + `R` | `Cmd` + `R` |
| **Undo Last Action** | `Ctrl` + `Z` | `Cmd` + `Z` |
| **Quick Select Layer by Initial** | `First Letter` of layer name *(Layer list must be selected)* | `First Letter` of layer name *(Layer list must be selected)* |


## ROI Annotation & Editing

> **Important:** The **ROIs layer** must be actively selected in your layers list for these annotation shortcuts to function.

| Action | Windows / Linux | macOS |
| :--- | :--- | :--- |
| **Draw Ellipse ROI** | `E` | `E` |
| **Draw Rectangle ROI** | `R` | `R` |
| **Draw Polygon ROI** | `P` | `P` |
| **Finish Drawing Polygon** | `Double-Click` | `Double-Click` |
| **Modify Polygon Vertices** | `D` | `D` |
| **Pan & Zoom Mid-Draw** (Hold key) | `Spacebar` | `Spacebar` |
| **Select a ROI** (Move/Resize mode) | `S` | `S` |
| **Select All ROIs** | `A` | `A` |
| **Copy Selected ROI(s)** | `Ctrl` + `C` | `Cmd` + `C` |
| **Paste Selected ROI(s)** | `Ctrl` + `V` | `Cmd` + `V` |
| **Delete Selected ROI(s)** | `Delete` or `Backspace` | `Delete` or `Backspace` |
| **Save ROI Data*** | `Shift` + `Ctrl` + `S` | `Shift` + `Cmd` + `S` |


## Image Processing

| Action | Windows / Linux | macOS |
| :--- | :--- | :--- |
| **Unmix using Default Preset*** | `Shift` + `Ctrl` + `U` | `Shift` + `Cmd` + `U` |

>*not napari native

