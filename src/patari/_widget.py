# _widget.py
from magicgui import magic_factory
from magicgui.widgets import Table, PushButton, ComboBox
from qtpy.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QFileDialog,
    QDockWidget,
)

from napari import Viewer
from napari.layers import Image, Shapes
from pathlib import Path
import numpy as np
import pandas as pd
from skimage.draw import polygon
import cv2
from qtpy.QtGui import QColor
from datetime import datetime, timedelta

from patari._reader import patato_reader_function, patari_reader_function_all
from patari.roi_utils import compute_roi_stats
from patari.config import (
    dtype_map,
    roi_colors,
    DEFAULT_FRAME_START_IDX,
    DEFAULT_WAV_START_IDX,
)


# TODO: for other recons that dont contain all frames, we should label the reconstructed frame, not simply frame 0. Otherwise it doesnt match with US and timestamp


# ---------- Controller class ----------
class PatariPlugin:
    def __init__(
        self, viewer: Viewer, path: Path, reader=patari_reader_function_all
    ):
        if reader is None:
            raise RuntimeError(
                "No default reader available. Provide reader function."
            )
        self.viewer = viewer
        self.path = Path(path)
        self.reader = reader

        # state
        self.live_table = None
        self.saved_table = None
        self.save_button = None
        self.delete_button = None
        self.csv_button = None
        self.hdf5_button = None
        self.tables_container = None
        self.info_label = None

        self.shapes_layer: Shapes | None = None
        self.active_layer: Image | None = None

        # run setup sequence
        self.setup_viewer()
        self.setup_info_widget()
        self.load_layers()
        self.add_shapes_layer()
        self.setup_tables()
        self.set_active_layer()
        self.connect_events()

        # initial dims point
        self.viewer.dims.point = (
            DEFAULT_FRAME_START_IDX,
            DEFAULT_WAV_START_IDX,
            0,
            0,
        )
        # initial update
        self.update_live_table()
        self.update_info_labels()

    # ---------------- viewer + loading ----------------
    def setup_viewer(self):
        self.viewer.axes.visible = True
        self.viewer.axes.labels = True
        self.viewer.grid.enabled = False
        self.viewer.scale_bar.visible = True
        self.viewer.scale_bar.unit = "mm"
        # default axis labels — will be updated to include wavelength
        self.viewer.dims.axis_labels = ("Frame", "Wavelength", "z", "x")

    def setup_info_widget(self):
        # create a small widget to hold the label
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.addWidget(QLabel("Slice Info:"))
        self.info_label = QLabel("")  # initialized empty
        info_layout.addWidget(self.info_label)

        # optionally add stretch so it stays compact
        info_layout.addStretch()

        # dock it in the viewer
        self.viewer.window.add_dock_widget(
            info_widget,
            name="Info",
            area="right",  # or "left", "top", etc.
        )

    def timestamp_for_slice(self, frame_idx, wav_idx):
        """
        Get timestamp for given frame and wavelength index from active layer metadata.
        timestamp in ithera is NET DateTime
        """
        if self.active_layer is None:
            return "N/A", 0.0

        ts = self.active_layer.metadata["timestamps"]
        if frame_idx >= ts.shape[0] or wav_idx >= ts.shape[1]:
            return "N/A", 0.0

        ts_seconds = self.active_layer.metadata["timestamps"][
            frame_idx, wav_idx
        ]  # * 1e-7
        ts_start_seconds = self.active_layer.metadata["timestamps"][
            0, 0
        ]  # * 1e-7
        dt = datetime(1, 1, 1) + timedelta(seconds=ts_seconds)
        return dt, ts_seconds - ts_start_seconds

    def snap_to_reconstructed_frame(self, frame_idx: int) -> int:
        """
        Snap a frame index to the nearest reconstructed acquisition frame.
        This is necessary for sparse reconstructions that dont contain all frames.
        """
        frames = self.active_layer.metadata.get("frames", None)
        if not frames:
            return frame_idx

        frames = np.asarray(frames, dtype=int)
        return int(frames[np.argmin(np.abs(frames - frame_idx))])

    def load_layers(self):
        """Call the reader and add image layers if viewer is empty."""
        if len(self.viewer.layers) > 0:
            # viewer not empty, skip loading
            return

        layers = self.reader(str(self.path))
        for data, kw, lt in layers:
            if lt == "image":
                # ensure metadata exists
                kw = dict(kw)
                if "metadata" not in kw:
                    kw["metadata"] = {}
                self.viewer.add_image(data, **kw)
            else:
                # untested, but can be used for patato ROIs or segmasks later
                self.viewer.add_labels(data, **kw)

    # ---------------- shapes + active layer ----------------
    def add_shapes_layer(self):
        """Create or reuse a shapes layer named ROIs (dim=2)."""
        if "ROIs" in self.viewer.layers and isinstance(
            self.viewer.layers["ROIs"], Shapes
        ):
            self.shapes_layer = self.viewer.layers["ROIs"]
        else:
            self.shapes_layer = self.viewer.add_shapes(
                name="ROIs",
                edge_color="#aa0000ff",
                face_color="transparent",
                edge_width=0.2,
                ndim=2,
                metadata={"type": "roi"},
            )

    def set_active_layer(self):
        """
        Pick the first image layer right below the shapes layer as active layer (used for ROIs).
        Set all other PA layers to invisible.
        Set multiplicative blending and auto contrast for all PA layers.
        """
        roi_layer_idx = self.viewer.layers.index(self.shapes_layer)
        if roi_layer_idx == 0:
            raise RuntimeError(
                "Shapes layer is first in stack; cannot find target below it."
            )

        for i, layer in enumerate(self.viewer.layers):
            if layer.metadata["type"] == "pa":
                layer.blending = "multiplicative"
                # auto contrast for each wavelength
                layer._keep_auto_contrast = True

                if i == roi_layer_idx - 1:
                    # target layer is the one right below shapes
                    if not isinstance(layer, Image):
                        raise RuntimeError(
                            "layer beneath ROI shape layer is not an Image layer."
                        )
                    layer.visible = True
                    self.active_layer = layer
                else:
                    layer.visible = False

        if self.active_layer is None:
            raise RuntimeError("Couldnt set active layer")

        # set active layer label in UI
        # self.active_layer_label.setText(
        #     f"<b>Active Layer:<br>{self.active_layer.name}</b>"
        # )

    # ---------------- tables UI ----------------
    def setup_tables(self):
        """Create / reuse the Live & Saved tables and control buttons, dock them at bottom."""
        if hasattr(PatariPlugin, "_tables_container_created"):
            # reuse stored widgets
            self.live_table = PatariPlugin._live_table
            self.saved_table = PatariPlugin._saved_table
            self.save_button = PatariPlugin._save_button
            self.delete_button = PatariPlugin._delete_button
            self.csv_button = PatariPlugin._csv_button
            self.hdf5_button = PatariPlugin._hdf5_button
            return

        # empty dataframe template with dtype mapping
        df_empty = pd.DataFrame(columns=list(dtype_map.keys())).astype(
            dtype_map
        )

        # create magicgui Table widgets
        self.live_table = Table(value=df_empty.copy())
        self.saved_table = Table(value=df_empty.copy())

        # buttons
        self.save_button = PushButton(text="Save ROI")
        self.delete_button = PushButton(text="Delete Saved")
        self.csv_button = PushButton(text="Export CSV")
        self.hdf5_button = PushButton(text="Export HDF5")

        # green text in saved table
        self.saved_table.native.setStyleSheet("QTableWidget { color: green; }")

        # build Qt container for the bottom dock
        container = QWidget()
        layout = QHBoxLayout(container)

        # live panel
        live_panel = QWidget()
        live_layout = QVBoxLayout(live_panel)
        live_layout.addWidget(QLabel("Live ROIs"))
        live_layout.addWidget(self.live_table.native)

        # button panel
        btn_panel = QWidget()
        btn_layout = QVBoxLayout(btn_panel)
        # Label to display current active layer
        # self.active_layer_label = QLabel("Active layer: None")
        # btn_layout.addWidget(self.active_layer_label)
        btn_layout.addWidget(QLabel(" "))  # spacer
        btn_layout.addWidget(self.save_button.native)
        btn_layout.addWidget(self.delete_button.native)
        btn_layout.addWidget(self.csv_button.native)
        btn_layout.addStretch()

        # saved panel
        saved_panel = QWidget()
        saved_layout = QVBoxLayout(saved_panel)
        saved_layout.addWidget(QLabel("Saved ROIs"))
        saved_layout.addWidget(self.saved_table.native)

        layout.addWidget(live_panel)
        layout.addWidget(btn_panel)
        layout.addWidget(saved_panel)

        container.setMinimumHeight(300)

        # dock it
        self.viewer.window.add_dock_widget(
            container, name="ROI Tables", area="bottom"
        )

        # store static references for reuse
        # todo: why PatariPlugin instead of self.?
        PatariPlugin._tables_container_created = True
        PatariPlugin._tables_container = container
        PatariPlugin._live_table = self.live_table
        PatariPlugin._saved_table = self.saved_table
        PatariPlugin._save_button = self.save_button
        PatariPlugin._delete_button = self.delete_button
        PatariPlugin._csv_button = self.csv_button
        PatariPlugin._hdf5_button = self.hdf5_button

    # ---------------- events wiring ----------------
    def connect_events(self):
        # shapes edits
        self.shapes_layer.events.data.connect(self.update_live_table)
        # dims changes (scrolling)
        self.viewer.dims.events.point.connect(self.on_dims_changed)
        # layer reorder -> recompute active layer
        self.viewer.layers.events.reordered.connect(self.on_layer_reordered)

        # buttons
        self.save_button.clicked.connect(self.on_save_clicked)
        self.delete_button.clicked.connect(self.on_delete_saved_clicked)
        self.csv_button.clicked.connect(self.on_csv_export_clicked)

    # ---------------- event handlers ----------------
    def on_layer_reordered(self, event=None):
        # update active layer dynamically and refresh table
        try:
            self.set_active_layer()
            self.update_live_table()
            self.update_info_labels()
        except Exception as e:
            print("on_layer_reordered:", e)

    def on_dims_changed(self, event=None):
        # clamp dims and update table + axis label
        try:
            self.update_info_labels()
            self.update_live_table()
        except Exception as e:
            print("on_dims_changed:", e)

    def on_dims_changed(self, event=None):
        try:
            pt = list(self.viewer.dims.point)
            frame_idx = int(round(pt[0]))

            # auto jump to nearest reconstructed frame
            snapped = self.snap_to_reconstructed_frame(frame_idx)
            if snapped != frame_idx:
                self.viewer.dims.set_point(0, snapped)
                return  # avoid recursion

            self.update_info_labels()
            self.update_live_table()

        except Exception as e:
            print("on_dims_changed:", e)

    # ---------------- update / UI methods ----------------
    def update_live_table(self, event=None):
        # recompute stats and write into live_table.value

        frame_idx = int(round(self.viewer.dims.point[0]))
        wav_idx = int(round(self.viewer.dims.point[1]))

        df = compute_roi_stats(
            self.shapes_layer,
            self.active_layer,
            frame_idx,
            wav_idx,
        )

        self.live_table.value = df

        # color ROIs in shapes layer to distinct colors
        num_shapes = len(self.shapes_layer.data)
        colors_for_shapes = [
            roi_colors[i % len(roi_colors)] for i in range(num_shapes)
        ]
        self.shapes_layer.edge_color = colors_for_shapes

        # color first column cells background to match colors
        for row_idx, color_hex in enumerate(colors_for_shapes):
            item = self.live_table.native.item(row_idx, 0)
            if item is not None:
                item.setBackground(QColor(color_hex))

    def update_info_labels(self, event=None):

        # refresh active layer (is necessary?)
        # self.set_active_layer()

        if self.active_layer is None:
            return

        # clamp dims to active layer bounds
        # shape = np.asarray(self.active_layer.data).shape
        # F, W = shape[:2]

        # # current viewer dims
        # pt = list(self.viewer.dims.point)
        # frame_idx = min(max(0, int(round(pt[0]))), F - 1)
        # wav_idx = min(max(0, int(round(pt[1]))), W - 1)

        pt = list(self.viewer.dims.point)
        frame_idx = int(round(pt[0]))
        wav_idx = int(round(pt[1]))

        # update axis label with actual wavelength (if present)
        # TODO: should be easily updated to handle chromos as well
        wavelengths = self.active_layer.metadata.get("wavelengths", None)
        wav_label = (
            f"{wavelengths[wav_idx]} nm"
            if isinstance(wavelengths, (list, tuple))
            and 0 <= wav_idx < len(wavelengths)
            else str(wav_idx)
        )
        frames = self.active_layer.metadata.get("frames", None)
        is_reconstructed = frames is None or frame_idx in frames

        frame_label = (
            f"Frame: {frame_idx} (reconstructed)"
            if is_reconstructed
            else f"Frame: {frame_idx} (missing)"
        )

        self.viewer.dims.axis_labels = (
            frame_label,
            f"Wavelength: {wav_label}",
            "z",
            "x",
        )

        # update the info section in the PATARI controls
        # get timestamp of current frame,wav
        ts, ts_delta = self.timestamp_for_slice(frame_idx, wav_idx)
        self.info_label.setText(
            f"Layer: {self.active_layer.name}\n"
            f"Frame: {frame_idx}\n"
            f"Timestamp: {ts} ({ts_delta:.2f} s)\n"
            f"Wavelength: {wav_label}"
        )

    # ---------------- button callbacks ----------------
    def on_save_clicked(self, event=None):
        selected = self.shapes_layer.selected_data
        if len(selected) != 1:
            print("Select one ROI to save")
            return
        roi_idx = list(selected)[0]
        # convert live_table.value to dataframe
        val = self.live_table.value
        # magicgui Table sometimes stores value as DataFrame already
        if isinstance(val, pd.DataFrame):
            df_live = val
        else:
            df_live = pd.DataFrame(val["data"], columns=val["columns"])

        row = df_live.iloc[[roi_idx]].astype(dtype_map)
        if row.empty:
            print("Nothing to save")
            return
        # append to saved_table
        sval = self.saved_table.value
        if isinstance(sval, pd.DataFrame):
            df_saved = sval
        else:
            df_saved = (
                pd.DataFrame(sval["data"], columns=sval["columns"])
                if isinstance(sval, dict)
                else pd.DataFrame()
            )
        if df_saved.empty:
            df_saved = row.copy()
        else:
            df_saved = pd.concat([df_saved, row], ignore_index=True)

        df_saved = df_saved.astype(dtype_map)

        self.saved_table.value = df_saved
        print(f"Saved ROI {roi_idx}")

    def on_delete_saved_clicked(self, event=None):
        selection_model = self.saved_table.native.selectionModel()
        selected_rows = selection_model.selectedRows()
        selected_indices = [idx.row() for idx in selected_rows]
        if not selected_indices:
            print("No row selected to delete.")
            return
        df_saved = pd.DataFrame(
            self.saved_table.value["data"],
            columns=self.saved_table.value["columns"],
        )
        df_saved = df_saved.drop(selected_indices).reset_index(drop=True)
        self.saved_table.value = df_saved
        print(f"Deleted {len(selected_indices)} saved rows")

    def on_csv_export_clicked(self, event=None):
        # convert saved table to df
        df_saved = pd.DataFrame(
            self.saved_table.value["data"],
            columns=self.saved_table.value["columns"],
        ).astype(dtype_map)

        if df_saved.empty:
            print("Saved table empty")
            return
        filename, _ = QFileDialog.getSaveFileName(
            None,
            "Save Saved ROIs as CSV",
            "saved_rois.csv",
            "CSV Files (*.csv)",
        )
        if filename:
            if not filename.endswith(".csv"):
                filename += ".csv"
            df_saved.to_csv(filename, index=False)
            print(f"Saved ROI table to {filename}")


# ---------- magicgui factory wrapper ----------
@magic_factory(auto_call=True, layout="vertical")
def patari_controls(viewer: Viewer, path: Path):
    """magicgui wrapper: instantiate the controller (and keep it attached to the widget function)."""
    if (
        not hasattr(patari_controls, "_plugin")
        or patari_controls._plugin.viewer is not viewer
        or patari_controls._plugin.path != Path(path)
    ):
        patari_controls._plugin = PatariPlugin(viewer, path)
    return None
