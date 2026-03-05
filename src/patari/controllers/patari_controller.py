from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from napari.layers import Image, Labels, Shapes
from napari.viewer import Viewer
from qtpy.QtGui import QColor
from qtpy.QtWidgets import QFileDialog
import pyqtgraph as pg


from patari.config import (
    DEFAULT_FRAME_START_IDX,
    DEFAULT_WAV_START_IDX,
    dtype_map,
    ROI_LABELS,
    DEFAULT_PA_LAYER,
    ROI_PLACEMENT_PRESETS,
)
from patari.roi.roi_utils import (
    compute_roi_stats,
    compute_roi_time_series,
    extract_roi_pixels_for_slice,
)
from patari.roi.roi_shapes import EllipseConfig, ShapeFactory
from patari.segmentation.service import DummySegmenter
from patari.utils.misc import parse_float_input, roi_color_for_index
from patari.segmentation.napari import (
    ensure_segmentation_labels_layer,
    set_segmentation_2d,
)

# from patari.utils.napari_layers import resolve_active_image_layer
from patari.widgets.info_dock import InfoDock, create_info_dock
from patari.widgets.roi_dock import RoiDock, create_roi_dock
from patari.widgets.scan_browser_dock import (
    ScanBrowserDock,
    create_scan_browser_dock,
)
from patari.widgets.annotation_dock import (
    AnnotationDock,
    create_annotation_dock,
)
from patari.widgets.reconstruction_dock import (
    ReconstructionDock,
    create_reconstruction_dock,
)
from patari.widgets.time_analysis_dock import (
    TimeAnalysisDock,
    create_time_analysis_dock,
)
from patari.widgets.unmixing_dock import UnmixingDock, create_unmixing_dock
from patari.widgets.histogram_dock import HistogramDock, create_histogram_dock


class PatariController:
    def __init__(
        self,
        viewer: Viewer,
        path: Path | None,
        *,
        reader,
    ):
        self.viewer = viewer
        self.path = Path(path) if path is not None else Path()
        self.reader = reader

        self._scan_paths: list[Path] = []

        self.shapes_layer: Shapes | None = None
        self.active_layer: Image | None = None

        # --- left elements ---
        self.info: InfoDock | None = None
        # Info widget is the plugin-provided dock widget; controller does not dock it.

        # --- right elements ---
        self.scan_browser: ScanBrowserDock | None = None
        self.annotation: AnnotationDock | None = None
        self.unmixing: UnmixingDock | None = None
        self.reconstruction: ReconstructionDock | None = None
        self._scan_browser_dock_widget = None
        self._annotation_dock_widget = None
        self._unmixing_dock_widget = None
        self._reconstruction_dock_widget = None

        self.roi_intensity_min: float | None = None
        self.roi_intensity_max: float | None = None
        self.roi_intensity_mode: str | None = "clip"

        # segmentation
        self._segmenter = DummySegmenter()
        self._placed_roi_index: int | None = None
        self._pending_preset_class: str | None = None

        # -- bottom elements --
        self.roi: RoiDock | None = None
        self.time_analysis: TimeAnalysisDock | None = None
        self.histograms: HistogramDock | None = None
        self._roi_dock_widget = None
        self._time_analysis_dock_widget = None
        self._histograms_dock_widget = None

        self._setup_viewer()
        self._ensure_shapes_layer()
        self._ensure_docks()
        self._connect_events()
        self._init_dims_point()

        # If a path is provided, populate scan browser / load scan.
        # Otherwise, the Scan Browser dock drives loading.
        if path is not None:
            self._init_path(self.path)
        elif self.scan_browser is not None:
            # Show an empty folder field instead of defaulting to '.'
            self.scan_browser.folder_lineedit.setText("")

        self.refresh_all()

    # ---------------- setup ----------------
    def _setup_viewer(self) -> None:
        self.viewer.axes.visible = True
        self.viewer.axes.labels = True
        self.viewer.grid.enabled = False
        self.viewer.scale_bar.visible = True
        self.viewer.scale_bar.unit = "mm"
        self.viewer.dims.axis_labels = ("Frame", "Wavelength", "z", "x")

    def _ensure_shapes_layer(self) -> None:
        if "ROIs" in self.viewer.layers and isinstance(
            self.viewer.layers["ROIs"], Shapes
        ):
            self.shapes_layer = self.viewer.layers["ROIs"]
            self._ensure_roi_on_top()
            return

        self.shapes_layer = self.viewer.add_shapes(
            name="ROIs",
            edge_color=roi_color_for_index(0),
            face_color="transparent",
            edge_width=0.1,
            ndim=2,
            metadata={"type": "roi"},
        )

        # this is not necessary if shape layer is initially empty
        # self._apply_roi_colors()
        # if ROI_LABELS:
        #     self._apply_roi_labels()
        self._ensure_roi_on_top()

    def _ensure_roi_on_top(self) -> None:
        """
        Necessary because ROI layer should persist across different scans and will therefore
        end up below newly added image layers. This ensures it is always on top.
        TODO: could be extended to full ordering: ROIs > PA images > US images
        """

        if self.shapes_layer is None:
            return
        try:
            self.shapes_layer.visible = True
        except Exception:
            pass

        # Keep ROIs above newly-added image layers.
        try:
            layers = self.viewer.layers
            idx = list(self.viewer.layers).index(self.shapes_layer)
            # Put ROIs at the very top of the stack.
            if idx != len(layers) - 1:
                layers.move(idx, len(layers))
        except Exception:
            print("PATARI: failed to move ROIs layer to top")
            pass

    def _ensure_docks(self) -> None:
        # Create docks once per controller instance.
        if self.scan_browser is None:
            self.scan_browser = create_scan_browser_dock()
            self._scan_browser_dock_widget = (
                self.viewer.window.add_dock_widget(
                    self.scan_browser.widget,
                    name="Scan Browser",
                    area="right",
                )
            )

        if self.info is None:
            self.info = create_info_dock()

        if self.roi is None:
            self.roi = create_roi_dock()
            self._roi_dock_widget = self.viewer.window.add_dock_widget(
                self.roi.widget,
                name="Tabular",
                area="bottom",
            )

        if self.time_analysis is None:
            self.time_analysis = create_time_analysis_dock()
            self._time_analysis_dock_widget = (
                self.viewer.window.add_dock_widget(
                    self.time_analysis.widget,
                    name="Time Analysis",
                    area="bottom",
                )
            )

        if self.histograms is None:
            self.histograms = create_histogram_dock()
            self._histograms_dock_widget = self.viewer.window.add_dock_widget(
                self.histograms.widget,
                name="Histograms",
                area="bottom",
            )

        if self.annotation is None:
            self.annotation = create_annotation_dock()
            self._annotation_dock_widget = self.viewer.window.add_dock_widget(
                self.annotation.widget,
                name="Annotation",
                area="right",
            )

        if self.unmixing is None:
            self.unmixing = create_unmixing_dock()
            self._unmixing_dock_widget = self.viewer.window.add_dock_widget(
                self.unmixing.widget,
                name="Unmixing",
                area="right",
            )

        if self.reconstruction is None:
            self.reconstruction = create_reconstruction_dock()
            self._reconstruction_dock_widget = (
                self.viewer.window.add_dock_widget(
                    self.reconstruction.widget,
                    name="Reconstruction",
                    area="right",
                )
            )

        # make sure some docks are tabified
        qt_window = getattr(self.viewer.window, "_qt_window", None)
        if qt_window is not None:
            # Bottom: ROI, Time Analysis and Histogram
            qt_window.tabifyDockWidget(
                self._roi_dock_widget, self._time_analysis_dock_widget
            )
            qt_window.tabifyDockWidget(
                self._roi_dock_widget, self._histograms_dock_widget
            )
            # Right: Scan Browser + Annotation
            qt_window.tabifyDockWidget(
                self._scan_browser_dock_widget,
                self._annotation_dock_widget,
            )
            qt_window.tabifyDockWidget(
                self._scan_browser_dock_widget,
                self._unmixing_dock_widget,
            )
            qt_window.tabifyDockWidget(
                self._scan_browser_dock_widget,
                self._reconstruction_dock_widget,
            )

    def _connect_events(self) -> None:
        if self.shapes_layer is not None:
            self.shapes_layer.events.data.connect(self._on_shapes_data_changed)

        self.viewer.dims.events.point.connect(self.on_dims_changed)

        # TODO: should reordering / adding / removing layers trigger anything?
        # self.viewer.layers.events.reordered.connect(self.on_layers_changed)
        # self.viewer.layers.events.inserted.connect(self.on_layers_changed)
        # self.viewer.layers.events.removed.connect(self.on_layers_changed)
        self.viewer.layers.selection.events.changed.connect(
            self.on_selection_changed
        )

        if self.roi is not None:
            self.roi.save_button.clicked.connect(self.on_save_clicked)
            self.roi.delete_button.clicked.connect(
                self.on_delete_saved_clicked
            )
            self.roi.csv_button.clicked.connect(self.on_csv_export_clicked)
            self.roi.hdf5_button.clicked.connect(self.on_hdf5_export_clicked)

        if self.time_analysis is not None:
            self.time_analysis.generate_button.clicked.connect(
                self.on_generate_time_analysis_clicked
            )

        if self.histograms is not None:
            self.histograms.refresh_button.clicked.connect(
                self.on_refresh_histograms_clicked
            )

        if self.annotation is not None:
            for edit in (
                self.annotation.roi_clip_min_edit,
                self.annotation.roi_clip_max_edit,
                self.annotation.roi_exclude_min_edit,
                self.annotation.roi_exclude_max_edit,
            ):
                edit.editingFinished.connect(
                    self._on_roi_intensity_settings_changed
                )
                # required for reset via 'unset' clear button
                edit.textChanged.connect(
                    lambda t, _e=edit: (
                        self._on_roi_intensity_settings_changed()
                        if (t or "").strip() == ""
                        else None
                    )
                )

            self.annotation.roi_clipping_box.toggled.connect(
                lambda checked: self._on_roi_intensity_settings_changed()
            )
            self.annotation.roi_exclusion_box.toggled.connect(
                lambda checked: self._on_roi_intensity_settings_changed()
            )

            self.annotation.generate_tissue_segmentation_button.clicked.connect(
                self.on_generate_tissue_segmentation_clicked
            )
            self.annotation.place_roi_button.clicked.connect(
                self.on_place_roi_clicked
            )

            for btn in getattr(self.annotation, "roi_preset_buttons", []):
                btn.clicked.connect(
                    lambda checked=False, b=btn: self.on_roi_preset_clicked(b)
                )

        if self.scan_browser is not None:
            self.scan_browser.browse_button.clicked.connect(
                self.on_browse_folder_clicked
            )
            self.scan_browser.scans_list.currentRowChanged.connect(
                self.on_scan_selected
            )

    def _apply_roi_colors(self) -> None:
        """
        Assign distinct colors to each ROI shape based on its index.
        """
        if self.shapes_layer is None:
            return

        self.shapes_layer.edge_color = [
            roi_color_for_index(i) for i in range(len(self.shapes_layer.data))
        ]

    def _apply_roi_labels(self) -> None:
        """
        show ROI index labels next to shapes.
        TODO: this is a bit hacky
        """
        if self.shapes_layer is None:
            return

        try:
            props = dict(getattr(self.shapes_layer, "properties", {}) or {})
            props["roi_id"] = np.arange(len(self.shapes_layer.data), dtype=int)
            self.shapes_layer.properties = props
            # napari text supports formatting from properties.
            self.shapes_layer.text = {"string": "{roi_id}", "size": 8}
            # self.shapes_layer.text.visible = True # default

        except Exception:
            print("PATARI: failed to apply ROI labels")
            pass

    def _on_shapes_data_changed(self, event=None) -> None:
        if self.shapes_layer is None:
            return

        self._apply_roi_colors()
        if ROI_LABELS:
            self._apply_roi_labels()

        self.update_live_table()

    # ---------------- scans / loading ----------------
    def _init_path(self, path: Path) -> None:
        if path.is_dir():
            self.set_scan_folder(path)
            return

        if path.is_file():
            self.load_scan(path)
            return

        # Not a real path yet (e.g. in tests). Leave UI usable.
        if self.scan_browser is not None:
            self.scan_browser.set_folder(path)

    def set_scan_folder(self, folder: Path) -> None:
        folder = Path(folder)
        self.path = folder
        self._scan_paths = sorted(
            folder.glob("Scan_*.hdf5"), key=lambda p: int(p.stem.split("_")[1])
        )

        if self.scan_browser is not None:
            self.scan_browser.set_folder(folder)
            self.scan_browser.set_scans(self._scan_paths)

        # Auto-select first scan if available.
        if self._scan_paths and self.scan_browser is not None:
            self.scan_browser.scans_list.setCurrentRow(0)

    def load_scan(self, scan_path: Path) -> None:
        scan_path = Path(scan_path)
        self.path = scan_path

        # Remove existing data layers but keep ROI shapes and docks.
        self._clear_data_layers(keep_layers={self.shapes_layer})

        if not scan_path.exists():
            print(f"PATARI: scan not found: {scan_path}")
            self.refresh_all()
            return

        try:
            layers = self.reader(str(scan_path))
        except Exception as e:
            print(f"PATARI: failed to load '{scan_path}': {e}")
            self.refresh_all()
            return

        for data, kw, lt in layers:
            if lt == "image":
                kw = dict(kw)
                kw.setdefault("metadata", {})
                kw["metadata"].setdefault("filepath", str(scan_path))
                self.viewer.add_image(data, **kw)
            else:
                kw = dict(kw)
                kw.setdefault("metadata", {})
                kw["metadata"].setdefault("filepath", str(scan_path))
                self.viewer.add_labels(data, **kw)

        # After adding layers, pick a sensible default selected layer.
        self._select_default_pa_layer()
        self._ensure_roi_on_top()
        self._init_dims_point()

        # Fit view to the newly loaded data (prevents "zoomed out" state).
        try:
            self.viewer.reset_view()
        except Exception:
            pass
        self.refresh_all()

    def _clear_data_layers(self, keep_layers: set[object]) -> None:
        # Copy list of layers first (napari list is live).
        to_remove = []
        for layer in list(self.viewer.layers):
            if layer in keep_layers:
                continue
            # Prefer removing layers that look like PATARI data layers.
            layer_type = getattr(layer, "metadata", {}).get("type")
            if layer_type in {"pa", "us"}:
                to_remove.append(layer)
            # Also remove labels layers created by our reader.
            elif layer.__class__.__name__.lower().startswith("labels"):
                to_remove.append(layer)

        for layer in to_remove:
            try:
                self.viewer.layers.remove(layer)
            except Exception:
                pass

    def _select_default_pa_layer(self) -> None:

        # Find layer named DEFAULT_PA_LAYER, otherwise pick first PA layer found
        first_pa = None
        for layer in self.viewer.layers:
            if not isinstance(layer, Image):
                continue
            if layer.name == DEFAULT_PA_LAYER:
                self.viewer.layers.selection.select_only(layer)
                return
            if first_pa is None and layer.metadata.get("type") == "pa":
                first_pa = layer

        if first_pa is not None:
            self.viewer.layers.selection.select_only(first_pa)
            return

        raise RuntimeError(
            f"No PA image layer found (looking for '{DEFAULT_PA_LAYER}')"
        )

    def on_browse_folder_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            None,
            "Select folder with HDF5 scans",
            str(self.path if self.path.exists() else Path.cwd()),
        )
        if folder:
            self.set_scan_folder(Path(folder))

    def on_scan_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._scan_paths):
            return
        self.load_scan(self._scan_paths[row])

    def _init_dims_point(self) -> None:
        # Only set if viewer has at least 2 dims (frame/wavelength)
        try:
            pt = list(self.viewer.dims.point)
        except Exception:
            return

        if len(pt) < 2:
            return

        pt[0] = DEFAULT_FRAME_START_IDX
        pt[1] = DEFAULT_WAV_START_IDX
        self.viewer.dims.point = tuple(pt)

    # ---------------- layer selection ----------------
    def _resolve_active_layer(self) -> None:
        """
        Docstring for _resolve_active_layer

        :param self: Description
        """

        selection = self.viewer.layers.selection

        if len(selection) != 1:
            # no layer selected or multiple layers selected
            return

        selected_layer = getattr(selection, "active", None)

        # only change active layer if selected layer is a PA image layer
        if (
            isinstance(selected_layer, Image)
            and selected_layer.metadata.get("type") == "pa"
        ):
            self.active_layer = selected_layer
            print(f"active layer set to {self.active_layer.name}")
            # keep PA layers visually consistent; show only the active PA layer
            # set all other PA layers to invisible
            # set blending and auto contrast for all PA layers
            for layer in self.viewer.layers:
                if (
                    isinstance(layer, Image)
                    and layer.metadata.get("type") == "pa"
                ):
                    layer.blending = "multiplicative"
                    layer._keep_auto_contrast = True
                    layer.visible = layer is self.active_layer

    # ---------------- events ----------------
    # def on_layers_changed(self, event=None) -> None:
    #     # TODO: relevant?
    #     self._ensure_roi_on_top()
    #     self.refresh_all()

    def _on_roi_intensity_settings_changed(self) -> None:
        if self.annotation is None:
            return

        if self.annotation.roi_exclusion_box.isChecked():
            self.roi_intensity_mode = "exclude"
            self.roi_intensity_min = parse_float_input(
                self.annotation.roi_exclude_min_edit.text()
            )
            self.roi_intensity_max = parse_float_input(
                self.annotation.roi_exclude_max_edit.text()
            )
        elif self.annotation.roi_clipping_box.isChecked():
            self.roi_intensity_mode = "clip"
            self.roi_intensity_min = parse_float_input(
                self.annotation.roi_clip_min_edit.text()
            )
            self.roi_intensity_max = parse_float_input(
                self.annotation.roi_clip_max_edit.text()
            )
        else:
            self.roi_intensity_mode = None
            self.roi_intensity_min = None
            self.roi_intensity_max = None
        self.update_live_table()

    # ---------------- segmentation ----------------
    def _resolve_us_layer(self) -> Image | None:
        """Find US Image layer for segmentation (always runs on US)."""
        for layer in self.viewer.layers:
            if isinstance(layer, Image) and layer.metadata.get("type") == "us":
                return layer
        return None

    def _us_slice_2d(self, us_layer: Image) -> np.ndarray | None:
        data = np.asarray(us_layer.data)
        if data.ndim == 2:
            return data

        # Use current frame index if available.
        try:
            pt = list(self.viewer.dims.point)
            frame_idx = int(round(pt[0])) if len(pt) >= 1 else 0
        except Exception:
            frame_idx = 0

        frame_idx = int(np.clip(frame_idx, 0, max(0, data.shape[0] - 1)))

        if data.ndim == 3:
            return data[frame_idx]
        if data.ndim >= 4:
            # e.g. (frame, channel, y, x)
            return data[frame_idx, 0]

        return None

    def _remove_previous_placed_roi(self) -> None:
        if self.shapes_layer is None:
            return
        if self._placed_roi_index is None:
            return
        idx = int(self._placed_roi_index)
        if idx < 0 or idx >= len(self.shapes_layer.data):
            self._placed_roi_index = None
            return
        try:
            self.shapes_layer.selected_data = {idx}
            self.shapes_layer.remove_selected()
        except Exception:
            pass
        self._placed_roi_index = None

    def _set_roi_class_choices(self, class_names: dict[int, str]) -> None:
        if self.annotation is None:
            return
        combo = self.annotation.roi_class_combo
        combo.blockSignals(True)
        try:
            combo.clear()
            for class_id, name in sorted(
                class_names.items(), key=lambda kv: int(kv[0])
            ):
                combo.addItem(str(name), userData=int(class_id))
            combo.setEnabled(combo.count() > 0)
        finally:
            combo.blockSignals(False)

        # Apply pending preset class selection once classes are available.
        if self._pending_preset_class:
            self._select_roi_class_by_name(self._pending_preset_class)
            self._pending_preset_class = None

    def _select_roi_class_by_name(self, class_name: str) -> None:
        if self.annotation is None:
            return
        combo = self.annotation.roi_class_combo
        target = (class_name or "").strip().lower()
        if not target:
            return
        for i in range(combo.count()):
            txt = (combo.itemText(i) or "").strip().lower()
            if txt == target:
                combo.setCurrentIndex(i)
                return

    def on_roi_preset_clicked(self, button) -> None:
        if self.annotation is None:
            return

        try:
            preset_index = int(button.property("roi_preset_index"))
        except Exception:
            return

        if not (0 <= preset_index < len(ROI_PLACEMENT_PRESETS)):
            return

        preset = ROI_PLACEMENT_PRESETS[preset_index]
        roi_type = str(preset.get("roi_type", "ellipse"))

        # ROI type dropdown (currently only ellipse).
        for i in range(self.annotation.roi_type_combo.count()):
            if self.annotation.roi_type_combo.itemData(i) == roi_type:
                self.annotation.roi_type_combo.setCurrentIndex(i)
                break

        # Numeric fields
        self.annotation.roi_width_edit.setText(str(preset.get("width_mm", "")))
        self.annotation.roi_height_edit.setText(
            str(preset.get("height_mm", ""))
        )
        self.annotation.roi_depth_edit.setText(str(preset.get("depth_mm", "")))

        # Segmentation class selection (may be unavailable until segmentation exists).
        seg_class = str(preset.get("segmentation_class", "")).strip()
        if not seg_class:
            return
        if (
            self.annotation.roi_class_combo.isEnabled()
            and self.annotation.roi_class_combo.count() > 0
        ):
            self._select_roi_class_by_name(seg_class)
        else:
            self._pending_preset_class = seg_class

    def on_generate_tissue_segmentation_clicked(self) -> None:
        if self.annotation is None:
            return

        us_layer = self._resolve_us_layer()
        if us_layer is None:
            self.annotation.segmentation_status_label.setText(
                "No US layer found"
            )
            return

        us_2d = self._us_slice_2d(us_layer)
        if us_2d is None:
            self.annotation.segmentation_status_label.setText(
                "US layer has unsupported shape"
            )
            return

        self.annotation.segmentation_status_label.setText(
            "Running segmentation…"
        )

        try:
            result = self._segmenter.predict(us_2d)
        except Exception as e:
            self.annotation.segmentation_status_label.setText(
                f"Segmentation failed: {e}"
            )
            return

        # show segmentation as Labels
        labels = ensure_segmentation_labels_layer(self.viewer)
        try:
            set_segmentation_2d(
                labels,
                result.seg,
                class_names=result.class_names,
                reference_layer=us_layer,
            )
        except Exception as e:
            self.annotation.segmentation_status_label.setText(
                f"Failed to show labels: {e}"
            )
            return

        # Populate ROI class dropdown from model classes.
        self._set_roi_class_choices(result.class_names)
        self.annotation.roi_status_label.setText(
            "Segmentation generated. Choose class and place ROI."
        )

        self.annotation.segmentation_status_label.setText(
            "Segmentation layer added."
        )

    def on_place_roi_clicked(self) -> None:
        if self.annotation is None:
            return
        if self.shapes_layer is None:
            self.annotation.roi_status_label.setText("No ROIs layer")
            return

        # Must have segmentation layer.
        seg_layer = None
        try:
            if "Segmentation" in self.viewer.layers:
                seg_layer = self.viewer.layers["Segmentation"]
        except Exception:
            seg_layer = None

        if seg_layer is None or not isinstance(seg_layer, Labels):
            self.annotation.roi_status_label.setText(
                "Generate tissue segmentation first"
            )
            return

        try:
            seg = np.asarray(getattr(seg_layer, "data"))
        except Exception:
            self.annotation.roi_status_label.setText(
                "Invalid segmentation data"
            )
            return

        if seg.ndim != 2:
            self.annotation.roi_status_label.setText(
                "Segmentation layer must be 2D"
            )
            return

        class_id = self.annotation.roi_class_combo.currentData()
        if class_id is None:
            self.annotation.roi_status_label.setText("Select a class")
            return

        roi_type = self.annotation.roi_type_combo.currentData()
        if roi_type is None:
            roi_type = "ellipse"

        width_mm = parse_float_input(self.annotation.roi_width_edit.text())
        height_mm = parse_float_input(self.annotation.roi_height_edit.text())
        depth_mm = parse_float_input(self.annotation.roi_depth_edit.text())

        if width_mm is None or height_mm is None:
            self.annotation.roi_status_label.setText(
                "Enter ROI width and height (mm)"
            )
            return
        if depth_mm is None:
            depth_mm = 0.0

        # Use US layer calibration for placement.
        us_layer = self._resolve_us_layer()
        if us_layer is None:
            self.annotation.roi_status_label.setText("No US layer found")
            return

        try:
            ref_scale = getattr(us_layer, "scale", (1.0, 1.0))
            sy, sx = float(ref_scale[-2]), float(ref_scale[-1])
        except Exception:
            sy, sx = 1.0, 1.0

        try:
            ref_translate = getattr(us_layer, "translate", (0.0, 0.0))
            ty, tx = float(ref_translate[-2]), float(ref_translate[-1])
        except Exception:
            ty, tx = 0.0, 0.0

        class_mask = seg == int(class_id)
        config = EllipseConfig(
            width_mm=float(width_mm),
            height_mm=float(height_mm),
            depth_mm=float(depth_mm),
        )

        try:
            placer = ShapeFactory.create_shape(str(roi_type), config)
            verts_world = placer.to_napari_verts_world(
                class_mask=class_mask,
                sy=sy,
                sx=sx,
                ty=ty,
                tx=tx,
            )
        except Exception as e:
            self.annotation.roi_status_label.setText(
                f"ROI placement failed: {e}"
            )
            return

        # Only one placed ROI at a time.
        self._remove_previous_placed_roi()

        try:
            before = len(self.shapes_layer.data)
            self.shapes_layer.add(verts_world, shape_type="ellipse")
            after = len(self.shapes_layer.data)
            if after == before + 1:
                self._placed_roi_index = before
        except Exception as e:
            self.annotation.roi_status_label.setText(
                f"Failed to add ROI to viewer: {e}"
            )
            return

        self._ensure_roi_on_top()
        self._apply_roi_colors()
        self.update_live_table()

        self.annotation.roi_status_label.setText("ROI placed.")

    def on_selection_changed(self, event=None) -> None:
        self._resolve_active_layer()
        self.refresh_all()

    def on_dims_changed(self, event=None) -> None:
        # snap frames for sparse recon and refresh
        try:
            pt = list(self.viewer.dims.point)
            if len(pt) < 2:
                return

            frame_idx = int(round(pt[0]))
            snapped = self.snap_to_reconstructed_frame(frame_idx)
            if snapped != frame_idx:
                self.viewer.dims.set_point(0, snapped)
                return

            self.refresh_all()

        except Exception as e:
            print("on_dims_changed:", e)

    # ---------------- time analysis ----------------
    def on_generate_time_analysis_clicked(self, event=None) -> None:

        error_msg = ""

        if self.shapes_layer is None:
            error_msg = "No ROIs layer"
        elif self.active_layer is None:
            error_msg = "Select a PA image layer"
        elif len(self.shapes_layer.data) == 0:
            error_msg = "No ROIs defined"
        elif len(self.active_layer.metadata["frames"]) < 2:
            error_msg = "PA image layer has less than 2 frames"

        if error_msg:
            self.time_analysis.status_label.setText(
                f'<span style="color:red">{error_msg}</span>'
            )
            if self.time_analysis.plot_widget is not None:
                self.time_analysis.plot_widget.clear()
            return

        # Lazily create plot widget.
        if self.time_analysis.plot_widget is None:
            plot = pg.PlotWidget()
            plot.showGrid(x=True, y=True)
            plot.addLegend()
            self.time_analysis.plot_widget = plot
            layout = self.time_analysis.plot_container.layout()
            if layout is not None:
                layout.addWidget(plot)

        plot = self.time_analysis.plot_widget
        assert plot is not None

        # Current wavelength index from dims.
        pt = list(self.viewer.dims.point)
        wav_idx = int(round(pt[1])) if len(pt) >= 2 else 0

        self.time_analysis.status_label.setText("Computing time series…")
        x, series = compute_roi_time_series(
            self.shapes_layer,
            self.active_layer,
            wav_idx,
            clamp_min=self.roi_intensity_min,
            clamp_max=self.roi_intensity_max,
            clamp_mode=(self.roi_intensity_mode or "clip"),
        )

        plot.clear()

        plot.addLegend()

        for roi_index, y in series.items():
            color = roi_color_for_index(int(roi_index))
            plot.plot(
                x,
                y,
                pen=pg.mkPen(color=color, width=2),
                symbol="o",
                symbolSize=4,
                symbolBrush=pg.mkBrush(color),
                symbolPen=pg.mkPen(color=color, width=1),
                name=f"ROI {roi_index}",
            )

        # Re-autoscale y-axis on every refresh (useful when intensities vary).
        vb = plot.getViewBox()
        vb.enableAutoRange(axis=getattr(vb, "YAxis", "y"), enable=True)
        vb.autoRange(padding=0.02)

        xlabel = (
            "Time (s)"
            if self.active_layer.metadata.get("timestamps") is not None
            else "Frame"
        )
        plot.setLabel("bottom", xlabel)
        plot.setLabel("left", "Mean intensity")

        self.time_analysis.status_label.setText(
            f"Plotted {len(series)} ROI(s) over {len(x)} frame(s)."
        )

    # ---------------- histograms ----------------
    def on_refresh_histograms_clicked(self, event=None) -> None:
        if self.histograms is None:
            return
        if self.shapes_layer is None:
            self.histograms.status_label.setText("No ROIs layer")
            return
        if self.active_layer is None:
            self.histograms.status_label.setText("Select a PA image layer")
            return

        pt = list(self.viewer.dims.point)
        if len(pt) < 2:
            frame_idx, wav_idx = 0, 0
        else:
            frame_idx = int(round(pt[0]))
            wav_idx = int(round(pt[1]))

        self.histograms.status_label.setText("Computing histograms…")

        roi_vals = extract_roi_pixels_for_slice(
            self.shapes_layer,
            self.active_layer,
            frame_idx,
            wav_idx,
            clamp_min=self.roi_intensity_min,
            clamp_max=self.roi_intensity_max,
            clamp_mode=(self.roi_intensity_mode or "clip"),
        )

        # Clear previous plots
        container = self.histograms.plots_container
        layout = container.layout()
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget() if item is not None else None
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()

        n_plotted = 0
        for roi_index, vals in roi_vals.items():
            vals = np.asarray(vals)
            if vals.size == 0:
                continue

            # Histogram bins: simple default.
            try:
                counts, edges = np.histogram(vals, bins=50)
            except Exception:
                continue

            if counts.size == 0 or edges.size < 2:
                continue

            x = (edges[:-1] + edges[1:]) / 2.0
            width = float(edges[1] - edges[0])

            color = roi_color_for_index(int(roi_index))
            brush = pg.mkBrush(color)
            pen = pg.mkPen(color)

            plot = pg.PlotWidget()
            plot.setTitle(f"ROI {roi_index}")
            plot.showGrid(x=True, y=True)
            bar = pg.BarGraphItem(
                x=x,
                height=counts,
                width=width,
                brush=brush,
                pen=pen,
            )
            plot.addItem(bar)

            if layout is not None:
                layout.addWidget(plot)
            n_plotted += 1

        self.histograms.status_label.setText(
            f"Plotted {n_plotted} histogram(s) for frame {frame_idx}, wav {wav_idx}."
        )

    # ---------------- info/roi updates ----------------
    def refresh_all(self) -> None:
        """
        refresh all info that should be live updated
        """
        self.update_info_labels()
        self.update_live_table()
        # self._tabify_controls_and_annotation()

    def snap_to_reconstructed_frame(self, frame_idx: int) -> int:
        if self.active_layer is None:
            return frame_idx
        frames = self.active_layer.metadata.get("frames", None)
        if not frames:
            return frame_idx
        frames = np.asarray(frames, dtype=int)
        return int(frames[np.argmin(np.abs(frames - frame_idx))])

    def timestamp_for_slice(self, frame_idx: int, wav_idx: int):
        if self.active_layer is None:
            return "N/A", 0.0

        ts = self.active_layer.metadata.get("timestamps")
        if ts is None:
            return "N/A", 0.0

        if frame_idx >= ts.shape[0] or wav_idx >= ts.shape[1]:
            return "N/A", 0.0

        ts_seconds = ts[frame_idx, wav_idx]
        ts_start_seconds = ts[0, 0]

        # iThera uses .NET DateTime ticks
        try:
            from datetime import datetime, timedelta

            dt = datetime(1, 1, 1) + timedelta(seconds=float(ts_seconds))
        except Exception:
            dt = "N/A"

        return dt, float(ts_seconds) - float(ts_start_seconds)

    def update_info_labels(self, event=None) -> None:
        if self.info is None:
            return
        if self.active_layer is None:
            self.info.label.setText("Select a PA image layer")
            return

        pt = list(self.viewer.dims.point)
        if len(pt) < 2:
            self.info.label.setText(f"Layer: {self.active_layer.name}")
            return

        frame_idx = int(round(pt[0]))
        wav_idx = int(round(pt[1]))

        wavelengths = self.active_layer.metadata.get("wavelengths")
        wav_label = (
            f"{wavelengths[wav_idx]} nm"
            if isinstance(wavelengths, (list, tuple))
            and 0 <= wav_idx < len(wavelengths)
            else str(wav_idx)
        )

        frames = self.active_layer.metadata.get("frames")
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

        ts, ts_delta = self.timestamp_for_slice(frame_idx, wav_idx)
        scan_str = (
            str(self.path.stem) if getattr(self, "path", None) else "N/A"
        )
        self.info.label.setText(
            f"Scan: {scan_str}\n"
            f"Layer: {self.active_layer.name}\n"
            f"Frame: {frame_idx} | Wavelength: {wav_label}\n"
            f"Timestamp: {ts} ({ts_delta:.2f} s)"
        )

    def update_live_table(self, event=None) -> None:
        if self.roi is None or self.shapes_layer is None:
            return

        if self.active_layer is None:
            self.roi.live_table.value = pd.DataFrame(
                columns=list(dtype_map.keys())
            ).astype(dtype_map)
            return

        pt = list(self.viewer.dims.point)
        if len(pt) < 2:
            return

        frame_idx = int(round(pt[0]))
        wav_idx = int(round(pt[1]))

        try:
            df = compute_roi_stats(
                self.shapes_layer,
                self.active_layer,
                frame_idx,
                wav_idx,
                clamp_min=self.roi_intensity_min,
                clamp_max=self.roi_intensity_max,
                clamp_mode=(self.roi_intensity_mode or "clip"),
            )
        except Exception as e:
            print("update_live_table:", e)
            df = pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)

        self.roi.live_table.value = df

        # Keep shapes layer colors in sync with indices.
        self._apply_roi_colors()

        # color first column cells background to match ROI colors
        num_shapes = len(self.shapes_layer.data)
        for row_idx in range(num_shapes):
            item = self.roi.live_table.native.item(row_idx, 0)
            if item is not None:
                item.setBackground(QColor(roi_color_for_index(row_idx)))

    # ---------------- table helpers ----------------
    @staticmethod
    def _table_value_to_df(table: object) -> pd.DataFrame:
        # magicgui Table.value is sometimes a DataFrame and sometimes dict-like
        val = getattr(table, "value", table)
        if isinstance(val, pd.DataFrame):
            return val
        if isinstance(val, dict) and "data" in val and "columns" in val:
            return pd.DataFrame(val["data"], columns=val["columns"])
        return pd.DataFrame()

    # ---------------- button callbacks ----------------
    def on_save_clicked(self, event=None) -> None:
        if self.roi is None or self.shapes_layer is None:
            return

        selected = self.shapes_layer.selected_data
        if len(selected) != 1:
            print("Select one ROI to save")
            return

        roi_idx = list(selected)[0]
        df_live = self._table_value_to_df(self.roi.live_table)
        if df_live.empty or roi_idx >= len(df_live):
            print("Nothing to save")
            return

        include_all_frames = False
        include_all_wavelengths = False
        if self.annotation is not None:
            cb_frames = getattr(
                self.annotation, "include_all_frames_checkbox", None
            )
            cb_wavs = getattr(
                self.annotation, "include_all_wavelengths_checkbox", None
            )
            include_all_frames = (
                bool(cb_frames.isChecked()) if cb_frames is not None else False
            )
            include_all_wavelengths = (
                bool(cb_wavs.isChecked()) if cb_wavs is not None else False
            )

        if not include_all_frames and not include_all_wavelengths:
            rows_to_add = df_live.iloc[[roi_idx]].astype(dtype_map)
        else:
            if self.active_layer is None:
                print("Select an image layer to save ROI stats")
                return

            pt = list(self.viewer.dims.point)
            if len(pt) < 2:
                return
            frame_idx = int(round(pt[0]))
            wav_idx = int(round(pt[1]))

            data = np.asarray(self.active_layer.data)

            if data.ndim < 2:
                print("Active layer has no frame/wavelength dimensions")
                return

            if include_all_frames:
                frames_meta = getattr(self.active_layer, "metadata", {}).get(
                    "frames"
                )
                frame_indices = [int(f) for f in frames_meta]

            else:
                frame_indices = [frame_idx]

            if include_all_wavelengths:
                wav_indices = list(range(data.shape[1]))
            else:
                wav_indices = [wav_idx]

            collected: list[pd.DataFrame] = []
            for f_idx in frame_indices:
                for w_idx in wav_indices:
                    df_slice = compute_roi_stats(
                        self.shapes_layer,
                        self.active_layer,
                        int(f_idx),
                        int(w_idx),
                        clamp_min=self.roi_intensity_min,
                        clamp_max=self.roi_intensity_max,
                        clamp_mode=(self.roi_intensity_mode or "clip"),
                    )

                    roi_index_numeric = pd.to_numeric(
                        df_slice["roi_index"], errors="coerce"
                    )
                    df_row = df_slice[roi_index_numeric == int(roi_idx)]

                    collected.append(df_row.iloc[[0]].astype(dtype_map))

            if not collected:
                print("Nothing to save")
                return

            rows_to_add = pd.concat(collected, ignore_index=True).astype(
                dtype_map
            )

        df_saved = self._table_value_to_df(self.roi.saved_table)
        if df_saved.empty:
            df_saved = rows_to_add.copy()
        else:
            df_saved = pd.concat([df_saved, rows_to_add], ignore_index=True)

        self.roi.saved_table.value = df_saved.astype(dtype_map)
        print(f"Saved ROI {roi_idx} ({len(rows_to_add)} row(s))")

    def on_delete_saved_clicked(self, event=None) -> None:
        if self.roi is None:
            return

        selection_model = self.roi.saved_table.native.selectionModel()
        selected_rows = selection_model.selectedRows()
        selected_indices = [idx.row() for idx in selected_rows]
        if not selected_indices:
            print("No row selected to delete.")
            return

        df_saved = self._table_value_to_df(self.roi.saved_table)
        if df_saved.empty:
            return

        df_saved = df_saved.drop(selected_indices).reset_index(drop=True)
        self.roi.saved_table.value = df_saved.astype(dtype_map)
        print(f"Deleted {len(selected_indices)} saved rows")

    def on_csv_export_clicked(self, event=None) -> None:
        if self.roi is None:
            return

        df_saved = self._table_value_to_df(self.roi.saved_table)
        if df_saved.empty:
            print("Saved table empty")
            return

        filename, _ = QFileDialog.getSaveFileName(
            None,
            "Save ROIs as Excel",
            "roi_data.xlsx",
            "Excel Files (*.xlsx)",
        )
        if not filename:
            return
        if not filename.endswith(".xlsx"):
            filename += ".xlsx"

        df_saved.to_excel(filename, index=False)
        print(f"Saved ROI table to {filename}")

    def on_hdf5_export_clicked(self, event=None) -> None:
        """
        Export ROIs as a single 2D label mask image in an HDF5 file.

        The mask is rasterized in the active layer's pixel grid (last two dims).
        Metadata is stored as attributes on the "rois" group.
        TODO: this is GPT stuff. There is for sure a more compact way to do this
        """

        if self.roi is None:
            return

        if self.shapes_layer is None:
            print("No ROIs layer to export")
            return

        if self.active_layer is None:
            print(
                "Select a PA image layer (active layer) to define export grid"
            )
            return

        import h5py

        filename, _ = QFileDialog.getSaveFileName(
            None,
            "Save ROIs as HDF5",
            "rois.hdf5",
            "HDF5 Files (*.hdf5)",
        )
        if not filename:
            return
        if not filename.endswith(".hdf5"):
            filename += ".hdf5"

        # Determine output 2D mask shape from active layer (last two axes).
        try:
            data = np.asarray(self.active_layer.data)
            if data.ndim < 2:
                print("Active layer has unsupported shape")
                return
            mask_shape = tuple(map(int, data.shape[-2:]))  # (y, x)
        except Exception as e:
            print(f"Failed to determine export shape from active layer: {e}")
            return

        # Use current viewer point for non-spatial dims during world->data conversion.
        try:
            pt_world = list(self.viewer.dims.point)
        except Exception:
            pt_world = []

        # Convert ROI vertices from world coords (stored in shapes_layer) to the active
        # layer's data coords, then rasterize as a single 2D labels image.
        try:
            n_prefix = max(0, int(getattr(self.active_layer, "ndim", 2)) - 2)
            if len(pt_world) < n_prefix:
                pt_world = pt_world + [0.0] * (n_prefix - len(pt_world))
            prefix = np.asarray(pt_world[:n_prefix], dtype=float)

            data_2d_list: list[np.ndarray] = []
            shape_types = list(getattr(self.shapes_layer, "shape_type", []))

            for shape in self.shapes_layer.data:
                verts_world_2d = np.asarray(shape, dtype=float)
                if verts_world_2d.ndim != 2 or verts_world_2d.shape[1] != 2:
                    raise ValueError("ROI vertices must be an (N, 2) array")

                if n_prefix > 0:
                    prefix_rep = np.tile(
                        prefix[None, :], (verts_world_2d.shape[0], 1)
                    )
                    verts_world_full = np.concatenate(
                        [prefix_rep, verts_world_2d], axis=1
                    )
                else:
                    verts_world_full = verts_world_2d

                verts_data_full = np.asarray(
                    self.active_layer.world_to_data(verts_world_full),
                    dtype=float,
                )
                verts_data_2d = verts_data_full[:, -2:]
                data_2d_list.append(verts_data_2d)

            tmp_shapes = Shapes(
                data=data_2d_list, shape_type=shape_types, ndim=2
            )
            mask = tmp_shapes.to_labels(mask_shape)
        except Exception as e:
            print(f"Failed to rasterize ROIs to 2D mask: {e}")
            return

        # Extract current indices for metadata (if available).
        try:
            frame_idx = int(round(pt_world[0])) if len(pt_world) >= 1 else 0
        except Exception:
            frame_idx = 0
        try:
            wav_idx = int(round(pt_world[1])) if len(pt_world) >= 2 else 0
        except Exception:
            wav_idx = 0

        # rotate mask so that it fits the orientation in patato imported data
        mask = np.flipud(mask)
        # mask = np.rot90(mask)

        try:
            with h5py.File(filename, "w") as f:
                rois_group = f.create_group("rois")
                rois_group.create_dataset(
                    "mask",
                    data=np.asarray(mask),
                    compression="gzip",
                )

                # Metadata as attributes on the "rois" group.
                rois_group.attrs["exported_from"] = "PATARI"
                rois_group.attrs["timestamp"] = str(pd.Timestamp.now())
                rois_group.attrs["num_rois"] = int(len(self.shapes_layer.data))
                rois_group.attrs["active_layer"] = (
                    self.active_layer.name if self.active_layer else "N/A"
                )
                rois_group.attrs["frame_idx"] = int(frame_idx)
                rois_group.attrs["wav_idx"] = int(wav_idx)
                rois_group.attrs["mask_shape_yx"] = tuple(
                    int(x) for x in mask_shape
                )

                # Store reference transform info (useful to interpret world coords later).
                try:
                    rois_group.attrs["active_layer_scale"] = tuple(
                        float(x)
                        for x in getattr(self.active_layer, "scale", ())
                    )
                except Exception:
                    pass
                try:
                    rois_group.attrs["active_layer_translate"] = tuple(
                        float(x)
                        for x in getattr(self.active_layer, "translate", ())
                    )
                except Exception:
                    pass

            print(f"Saved ROI mask to {filename}")
        except Exception as e:
            print(f"Failed to save ROIs: {e}")
