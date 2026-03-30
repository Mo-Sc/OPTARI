from __future__ import annotations

import numpy as np
import pandas as pd
import patato as pat
from qtpy.QtGui import QColor
from qtpy.QtWidgets import QFileDialog

from patari.config import ROI_LABELS, dtype_map
from patari.patato_bridge import save_rois_to_scan
from patari.roi.roi_utils import compute_roi_stats
from patari.utils.misc import roi_color_for_index


class RoiController:
    """ROI visualization, table management, and ROI export helpers."""

    @staticmethod
    def apply_roi_colors(controller) -> None:
        """Assign deterministic colors to ROI edges by ROI index."""
        if controller.shapes_layer is None:
            return

        controller.shapes_layer.edge_color = [
            roi_color_for_index(i)
            for i in range(len(controller.shapes_layer.data))
        ]

    @staticmethod
    def apply_roi_labels(controller) -> None:
        """Show ROI index labels next to shapes (when enabled)."""
        if controller.shapes_layer is None:
            return

        try:
            props = dict(
                getattr(controller.shapes_layer, "properties", {}) or {}
            )
            props["roi_id"] = np.arange(
                len(controller.shapes_layer.data), dtype=int
            )
            controller.shapes_layer.properties = props
            # napari text supports formatting from properties.
            controller.shapes_layer.text = {"string": "{roi_id}", "size": 8}
        except Exception:
            print("PATARI: failed to apply ROI labels")

    @staticmethod
    def on_shapes_data_changed(controller, event=None) -> None:
        if controller.shapes_layer is None:
            return

        RoiController.apply_roi_colors(controller)
        if ROI_LABELS:
            RoiController.apply_roi_labels(controller)

        RoiController.update_live_table(controller)

    @staticmethod
    def update_live_table(controller, event=None) -> None:
        if controller.roi is None or controller.shapes_layer is None:
            return

        if controller.active_layer is None:
            controller.roi.live_table.value = pd.DataFrame(
                columns=list(dtype_map.keys())
            ).astype(dtype_map)
            return

        pt = list(controller.viewer.dims.point)
        if len(pt) < 2:
            return

        frame_idx = int(round(pt[0]))
        wav_idx = int(round(pt[1]))

        try:
            df = compute_roi_stats(
                controller.shapes_layer,
                controller.active_layer,
                frame_idx,
                wav_idx,
                clamp_min=controller.roi_intensity_min,
                clamp_max=controller.roi_intensity_max,
                clamp_mode=(controller.roi_intensity_mode or "clip"),
            )
        except Exception as e:
            print("update_live_table:", e)
            df = pd.DataFrame(columns=list(dtype_map.keys())).astype(dtype_map)

        controller.roi.live_table.value = df

        # Keep ROI colors in sync with current shape count/order.
        RoiController.apply_roi_colors(controller)

        # Color first table column to match each ROI color.
        num_shapes = len(controller.shapes_layer.data)
        for row_idx in range(num_shapes):
            item = controller.roi.live_table.native.item(row_idx, 0)
            if item is not None:
                item.setBackground(QColor(roi_color_for_index(row_idx)))

    @staticmethod
    def table_value_to_df(table: object) -> pd.DataFrame:
        # magicgui Table.value is sometimes a DataFrame and sometimes dict-like
        val = getattr(table, "value", table)
        if isinstance(val, pd.DataFrame):
            return val
        if isinstance(val, dict) and "data" in val and "columns" in val:
            return pd.DataFrame(val["data"], columns=val["columns"])
        return pd.DataFrame()

    @staticmethod
    def on_save_clicked(controller, event=None) -> None:
        if controller.roi is None or controller.shapes_layer is None:
            return

        selected = controller.shapes_layer.selected_data
        if len(selected) != 1:
            print("Select one ROI to save")
            return

        roi_idx = list(selected)[0]
        df_live = RoiController.table_value_to_df(controller.roi.live_table)
        if df_live.empty or roi_idx >= len(df_live):
            print("Nothing to save")
            return

        include_all_frames = False
        include_all_wavelengths = False
        if controller.annotation is not None:
            cb_frames = getattr(
                controller.annotation, "include_all_frames_checkbox", None
            )
            cb_wavs = getattr(
                controller.annotation, "include_all_wavelengths_checkbox", None
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
            if controller.active_layer is None:
                print("Select an image layer to save ROI stats")
                return

            pt = list(controller.viewer.dims.point)
            if len(pt) < 2:
                return
            frame_idx = int(round(pt[0]))
            wav_idx = int(round(pt[1]))

            data = np.asarray(controller.active_layer.data)
            if data.ndim < 2:
                print("Active layer has no frame/wavelength dimensions")
                return

            if include_all_frames:
                frames_meta = getattr(
                    controller.active_layer, "metadata", {}
                ).get("frames")
                frame_indices = [int(f) for f in frames_meta]
            else:
                frame_indices = [frame_idx]

            if include_all_wavelengths:
                wav_indices = list(range(data.shape[1]))
            else:
                wav_indices = [wav_idx]

            # Potentially expensive path: compute one row per (frame, wavelength)
            # for the selected ROI only, preserving the current ROI filtering rules.
            collected: list[pd.DataFrame] = []
            for f_idx in frame_indices:
                for w_idx in wav_indices:
                    df_slice = compute_roi_stats(
                        controller.shapes_layer,
                        controller.active_layer,
                        int(f_idx),
                        int(w_idx),
                        clamp_min=controller.roi_intensity_min,
                        clamp_max=controller.roi_intensity_max,
                        clamp_mode=(controller.roi_intensity_mode or "clip"),
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

        df_saved = RoiController.table_value_to_df(controller.roi.saved_table)
        if df_saved.empty:
            df_saved = rows_to_add.copy()
        else:
            df_saved = pd.concat([df_saved, rows_to_add], ignore_index=True)

        controller.roi.saved_table.value = df_saved.astype(dtype_map)
        print(f"Saved ROI {roi_idx} ({len(rows_to_add)} row(s))")

    @staticmethod
    def on_delete_saved_clicked(controller, event=None) -> None:
        if controller.roi is None:
            return

        selection_model = controller.roi.saved_table.native.selectionModel()
        selected_rows = selection_model.selectedRows()
        selected_indices = [idx.row() for idx in selected_rows]
        if not selected_indices:
            print("No row selected to delete.")
            return

        df_saved = RoiController.table_value_to_df(controller.roi.saved_table)
        if df_saved.empty:
            return

        df_saved = df_saved.drop(selected_indices).reset_index(drop=True)
        controller.roi.saved_table.value = df_saved.astype(dtype_map)
        print(f"Deleted {len(selected_indices)} saved rows")

    @staticmethod
    def on_csv_export_clicked(controller, event=None) -> None:
        if controller.roi is None:
            return

        df_saved = RoiController.table_value_to_df(controller.roi.saved_table)
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

    @staticmethod
    def on_hdf5_export_clicked(controller, event=None) -> None:
        """Save all ROI shapes to the scan HDF5 (full overwrite)."""
        if controller.shapes_layer is None:
            print("PATARI: no ROIs layer")
            return
        if controller.pa_data is None or controller.path is None:
            print("PATARI: no scan loaded")
            return
        if controller.path.suffix.lower() not in {".hdf5", ".h5"}:
            print(
                "PATARI: ROI export currently supports loaded HDF5 scans only"
            )
            return

        fov = controller._get_fov()
        if fov is None:
            print("PATARI: cannot determine FOV — is a reconstruction loaded?")
            return
        fov_x_m, fov_y_m = fov

        pt = list(controller.viewer.dims.point)
        frame_idx = int(round(pt[0])) if pt else 0
        try:
            z = float(
                controller.pa_data.scan_reader.get_scanner_z_position()[
                    frame_idx, 0
                ]
            )
            run = float(
                controller.pa_data.scan_reader.get_run_numbers()[frame_idx, 0]
            )
            rep = float(
                controller.pa_data.scan_reader.get_repetition_numbers()[
                    frame_idx, 0
                ]
            )
        except Exception:
            z, run, rep = 0.0, 0.0, 0.0

        # Snapshot shapes before closing the read handle.
        # This keeps UI state independent from the write/reopen cycle below.
        shapes_snapshot = [
            np.asarray(v, dtype=float) for v in controller.shapes_layer.data
        ]
        shape_types_snapshot = list(controller.shapes_layer.shape_type)

        # Close read handle while writing; always reopen in finally.
        controller.pa_data.close()
        controller.pa_data = None

        try:
            n_saved = save_rois_to_scan(
                controller.path,
                shapes_snapshot,
                shape_types_snapshot,
                fov_x_m,
                fov_y_m,
                z,
                run,
                rep,
                frame_idx,
            )
            if n_saved == 0:
                print(f"PATARI: cleared all ROIs from {controller.path.name}")
            else:
                print(
                    f"PATARI: saved {n_saved} ROI(s) to {controller.path.name}"
                )
        except Exception as e:
            print(f"PATARI: failed to save ROIs: {e}")
        finally:
            try:
                controller.pa_data = pat.PAData.from_hdf5(
                    str(controller.path), mode="r"
                )
            except Exception as e2:
                print(f"PATARI: failed to reopen scan after ROI save: {e2}")
