# _widget.py
from magicgui import magic_factory
from magicgui.widgets import Table, PushButton
from qtpy.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel

from napari import Viewer
from napari.layers import Image, Shapes
from pathlib import Path
import numpy as np
import pandas as pd
from skimage.draw import polygon
import cv2
from qtpy.QtGui import QColor

from patari._reader import patato_reader_function
from patari.roi_utils import compute_roi_stats

# TODO: currently cant add seperate ROI layers per wavelength/frame
# TODO: load and save of annotations (shapes) to file
# is this handled by napari already? (probably yes)
# cmd s saves ROI to csv. Can be added again by drag and drop.
# but need a way to connect any ROI (shape layer) to the table data
# maybe the following: right panel (PATARI controls) has a dropdown to select which Shapes layer to use for the table
# and maybe also shows the current info of the selected ROI (shape) in a table
# and only if a save button is pressed, the table info is saved to the main table
# which also has an export button to save to csv
# alternatively, the main table has a save and delete button for each entry

# TODO: In patari controls, dropdown to select which Shapes layer to use for ROI stats table
# also allow importing existing shapes from file (csv or napari shapes format)
# and another dropdown to select which Image layer to use for stats computation


# TODO: change order of layers to have US last
# change Recon blending to multiplicative

# TODO: add unmixed datasets as image layers


# configs and constants (move to separate file later)
DEFAULT_WAV_START_IDX = 0
DEFAULT_FRAME_START_IDX = 12

dtype_map = {
    "roi_index": int,
    "roi_type": str,
    "frame": int,
    "wavelength": int,
    "n_pixels": int,
    "area_mm2": float,
    "mean": float,
    "median": float,
    "std": float,
    "min": float,
    "max": float,
    # "name": str,
}

roi_colors = [
    "#8B0000",  # dark red
    "#B22222",
    "#DC143C",
    "#FF4500",
    "#FF6347",
    "#FF7F50",
    "#FF8C00",
    "#FFA500",
    "#FFD700",
    "#FFFF00",  # yellow
]


def setup_viewer(viewer: Viewer):
    """Configure basic viewer appearance; disable grid so shapes overlay images."""
    viewer.axes.visible = True
    viewer.axes.labels = True

    # Use single-view mode so annotations overlay the image (grid prevents overlay).
    viewer.grid.enabled = False

    viewer.scale_bar.visible = True
    viewer.scale_bar.unit = "mm"

    viewer.dims.axis_labels = ("Frame", "Wavelength", "z", "x")


@magic_factory(auto_call=True, layout="vertical")
def patari_controls(
    viewer: Viewer,
    path: Path,
):
    """
    PATARI plugin controls with ROI annotation + feature table (minimal).
    - loads image(s) via your reader (if viewer empty)
    - ensures a Shapes layer 'ROIs' exists
    - creates a docked magicgui Table widget for ROI features (kept on viewer)
    - updates table when shapes change or when dims point changes (so table follows scrolling)
    """
    # 1) viewer setup
    setup_viewer(viewer)

    # 2) load layers using your reader if viewer empty
    if len(viewer.layers) == 0:
        layers = patato_reader_function(str(path))
        for data, kw, lt in layers:
            if lt == "image":
                viewer.add_image(data, **kw)
            else:
                viewer.add_labels(data, **kw)

    # viewer.dims.axis_labels = ("Frame", "Wavelength", "z", "x")
    # 3) find the PA image layer (named 'Reconstruction' by your reader)
    if "Reconstruction" not in viewer.layers:
        print("Reconstruction layer not found; load an HDF5 file first.")
        return
    recon_layer = viewer.layers["Reconstruction"]
    recon_layer._keep_auto_contrast = True  # auto contrast for each wavelength (maybe precompute in case of perf issues)
    recon_layer.blending = "multiplicative"

    wavelengths = recon_layer.metadata["wavelengths"]

    # 4) ensure a Shapes layer 'ROIs' exists (create if needed)
    if "ROIs" in viewer.layers and isinstance(viewer.layers["ROIs"], Shapes):
        shapes_layer = viewer.layers["ROIs"]
    else:
        # create a new 2D shapes layer where users can draw ellipses/polygons
        shapes_layer = viewer.add_shapes(
            name="ROIs",
            edge_color="#aa0000ff",  # red border (#550000ff for darker)
            # face_color=None,  # transparent fill
            face_color="transparent",  # transparent fill
            edge_width=0.2,  # thin border
            ndim=2,
        )

    # --- 5) Create LIVE + SAVED tables + Save button in a horizontal layout ---

    if not hasattr(patari_controls, "_tables_container"):

        # Empty DF template
        df_empty = pd.DataFrame(columns=dtype_map.keys()).astype(dtype_map)

        # Actual Tables
        live_table = Table(value=df_empty.copy())
        saved_table = Table(value=df_empty.copy())
        save_roi_button = PushButton(text="Save ROI")
        delete_roi_button = PushButton(text="Delete Saved ROI")
        csv_export_button = PushButton(text="Export CSV")
        hdf5_export_button = PushButton(
            text="Export HDF5"
        )  # placeholder for future

        # Styling
        saved_table.native.setStyleSheet("QTableWidget { color: green; }")

        # ----- Create Qt widgets for layout -----
        container = QWidget()
        layout = QHBoxLayout(container)

        # Live panel (title + table)
        live_panel = QWidget()
        live_layout = QVBoxLayout(live_panel)
        live_layout.addWidget(QLabel("Live ROIs"))
        live_layout.addWidget(live_table.native)  # native = actual Qt widget

        # Button panel
        btn_panel = QWidget()
        btn_layout = QVBoxLayout(btn_panel)
        btn_layout.addWidget(QLabel(" "))  # spacer
        btn_layout.addWidget(save_roi_button.native)
        btn_layout.addWidget(delete_roi_button.native)
        btn_layout.addWidget(csv_export_button.native)
        btn_layout.addStretch()

        # Saved panel (title + table)
        saved_panel = QWidget()
        saved_layout = QVBoxLayout(saved_panel)
        saved_layout.addWidget(QLabel("Saved ROIs"))
        saved_layout.addWidget(saved_table.native)

        # Add to main horizontal layout
        layout.addWidget(live_panel)
        layout.addWidget(btn_panel)
        layout.addWidget(saved_panel)

        # Make bottom area taller
        container.setMinimumHeight(300)

        # Dock the whole panel once
        viewer.window.add_dock_widget(
            container, name="ROI Tables", area="bottom"
        )

        # store widgets on function for reuse
        patari_controls._tables_container = container
        patari_controls._live_table = live_table
        patari_controls._saved_table = saved_table
        patari_controls._save_roi_button = save_roi_button
        patari_controls._delete_roi_button = delete_roi_button
        patari_controls._csv_export_button = csv_export_button
        patari_controls._hdf5_export_button = hdf5_export_button

    else:
        live_table = patari_controls._live_table
        saved_table = patari_controls._saved_table
        save_roi_button = patari_controls._save_roi_button
        delete_roi_button = patari_controls._delete_roi_button
        csv_export_button = patari_controls._csv_export_button
        hdf5_export_button = patari_controls._hdf5_export_button

    def update_live_table(event=None):
        """
        Compute and update *only* the LIVE table.
        """
        shapes_layer.face_color = "transparent"  # workaround for polygon lasso

        try:
            df = compute_roi_stats(shapes_layer, recon_layer, viewer)
        except Exception as e:
            print("Error computing ROI stats:", e)
            return

        df = df.astype(dtype_map)

        try:
            live_table.value = df
        except Exception as e:
            print("Error updating live table:", e)

        # Update Shapes layer edge colors to match ROIs
        num_shapes = len(shapes_layer.data)
        colors_for_shapes = [
            roi_colors[i % len(roi_colors)] for i in range(num_shapes)
        ]
        shapes_layer.edge_color = colors_for_shapes

        # Ensure live_table has enough rows
        # for row_idx, color_hex in enumerate(colors_for_shapes):
        #     qcolor = QColor(color_hex)
        #     for col_idx in range(live_table.native.model().columnCount()):
        #         item = live_table.native.item(row_idx, col_idx)
        #         if item is not None:
        #             item.setForeground(qcolor)

        for row_idx, color_hex in enumerate(colors_for_shapes):
            qcolor = QColor(color_hex)
            item = live_table.native.item(row_idx, 0)  # 0 = roi_index column
            if item is not None:
                item.setBackground(qcolor)

    def update_axis_slider_label(event=None):
        """Update the wavelength axis label to show current wavelength value."""
        dims_point = [round(p) for p in viewer.dims.point]
        frame_idx = dims_point[0]
        wav_idx = dims_point[1]

        viewer.dims.axis_labels = (
            f"Frame: {frame_idx}",
            f"Wavelength: {wavelengths[wav_idx]} nm",
            "z",
            "x",
        )

    # --- Callback function for saving ROI ---
    def on_save_clicked(event=None):

        selected = shapes_layer.selected_data
        if len(selected) != 1:
            print("Select one ROI to save")
            return

        roi_idx = list(selected)[0]

        # Convert MagicGUI Table to a proper DataFrame
        df_live = pd.DataFrame(
            live_table.value["data"], columns=live_table.value["columns"]
        )

        if roi_idx >= len(df_live):
            print("ROI index out of range")
            return

        # Get the row to freeze
        # row = df_live.iloc[[roi_idx]]
        row = df_live.iloc[[roi_idx]].astype(dtype_map)

        if row.empty:
            print("Nothing to save")
            return

        # Append into saved table
        df_saved = pd.DataFrame(
            saved_table.value["data"], columns=saved_table.value["columns"]
        )

        if df_saved.empty:
            # If df_saved is empty, just assign row directly
            df_saved = row.copy()
        else:
            df_saved = pd.concat([df_saved, row], ignore_index=True)

        df_saved = df_saved.astype(dtype_map)
        saved_table.value = df_saved

        print(f"Saved ROI {roi_idx} to Saved Table")

    # --- Callback function for deletion ---
    def on_delete_saved_clicked(event=None):
        # Get indices of selected rows in the Saved Table
        selection_model = saved_table.native.selectionModel()
        selected_rows = selection_model.selectedRows()
        selected_indices = [idx.row() for idx in selected_rows]

        if not selected_indices:
            print("No row selected in Saved Table to delete.")
            return

        # Convert current Saved Table to DataFrame
        df_saved = pd.DataFrame(
            saved_table.value["data"], columns=saved_table.value["columns"]
        )

        # Drop the selected rows
        df_saved = df_saved.drop(selected_indices).reset_index(drop=True)

        # Update Saved Table
        saved_table.value = df_saved

        print(f"Deleted {len(selected_indices)} row(s) from Saved Table.")

    # --- Callback function for CSV export ---
    def on_csv_export_clicked(event=None):

        df_saved = pd.DataFrame(
            saved_table.value["data"], columns=saved_table.value["columns"]
        ).astype(dtype_map)

        if df_saved.empty:
            print("Saved table is empty. Nothing to save.")
            return

        # Ask user where to save (optional: or hardcode path)
        from qtpy.QtWidgets import QFileDialog

        filename, _ = QFileDialog.getSaveFileName(
            None, "Save Saved Table", "saved_rois.csv", "CSV Files (*.csv)"
        )
        if filename:
            if not filename.endswith(".csv"):
                filename += ".csv"
            df_saved.to_csv(filename, index=False)
            print(f"Saved ROI table to {filename}")

    # --- Connect buttons ---
    delete_roi_button.clicked.connect(on_delete_saved_clicked)
    csv_export_button.clicked.connect(on_csv_export_clicked)
    save_roi_button.clicked.connect(on_save_clicked)

    viewer.dims.point = (DEFAULT_FRAME_START_IDX, DEFAULT_WAV_START_IDX, 0, 0)

    # datasource change events to trigger table update
    shapes_layer.events.data.connect(update_live_table)
    # dims point changes (user scrolled through sliders)
    viewer.dims.events.point.connect(update_live_table)

    viewer.dims.events.point.connect(update_axis_slider_label)

    update_live_table()
    update_axis_slider_label()
