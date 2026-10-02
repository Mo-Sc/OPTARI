"""Analysis controller: time-series, histogram and spectral plots (pyqtgraph) over selected ROIs."""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
import pyqtgraph as pg

from optari.roi.roi_utils import (
    compute_roi_track_time_series,
    compute_roi_time_series,
    compute_roi_spectra,
    extract_roi_pixels_for_slice,
)
from optari.utils.misc import roi_color_for_index
from optari.controllers.base import TaskControllerBase
from optari.config import settings
from optari.utils.viewer import selected_frame_and_channel

logger = logging.getLogger(__name__)


class AnalysisController(TaskControllerBase):
    """Temporal analysis, histograms, and spectral plotting helpers."""

    def __init__(self, parent_controller):
        """Initialize the analysis controller."""
        super().__init__(parent_controller)

    def refresh_ui(self) -> None:
        """Refresh gating for the histogram/spectrum/time-analysis buttons."""
        has_data = (
            self.optari_controller.shapes_layer is not None
            and self.optari_controller.active_recon_layer is not None
        )
        self.optari_controller.time_analysis.generate_button.setEnabled(
            has_data
        )
        self.optari_controller.histograms.refresh_button.setEnabled(has_data)
        self.optari_controller.spectrum.refresh_button.setEnabled(has_data)

    def _signal_bindings(self) -> list[tuple[object, Callable]]:
        """Plot dock signals, and the Time Analysis scope in the annotation dock."""
        ctrl = self.optari_controller
        return [
            (
                ctrl.time_analysis.generate_button.clicked,
                self.on_generate_time_analysis_clicked,
            ),
            (
                ctrl.histograms.refresh_button.clicked,
                self.on_refresh_histograms_clicked,
            ),
            (
                ctrl.spectrum.refresh_button.clicked,
                self.on_refresh_spectrum_clicked,
            ),
            (
                ctrl.annotation.time_analysis_track_radio.toggled,
                self.on_time_analysis_scope_changed,
            ),
        ]

    def on_time_analysis_scope_changed(self, checked: bool) -> None:
        """When the user switches between "Selected ROI" and "Track ID" scopes,
        refresh the track-id combo, show only tracks that exist in the current
        ROI records.
        """
        if checked:
            self._refresh_time_analysis_track_combo()

    def _current_frame_channel(self) -> tuple[int, int]:
        """Current (frame, channel) from viewer dims. Plots fall back to the first."""
        return selected_frame_and_channel(self.viewer) or (0, 0)

    def _clear_plot_layout(self, container) -> object | None:
        """Remove and delete all plot widgets from a dock container layout."""
        layout = container.layout()
        if layout is None:
            return None

        while layout.count():
            item = layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        return layout

    def _refresh_time_analysis_track_combo(self) -> int | None:
        """Repopulate the track-id combo from live ROI records.

        Keeps the previous selection if that track still exists. Returns the
        selected track id, or ``None`` if no tracked ROI exists to plot.
        """
        combo = self.optari_controller.annotation.time_analysis_track_id_combo
        track_ids = sorted(
            {r.track_id for r in self.optari_controller.roi_ctrl.roi_records}
        )
        previous = combo.currentData()

        combo.blockSignals(True)
        combo.clear()
        for track_id in track_ids:
            combo.addItem(str(track_id), userData=track_id)
        if previous in track_ids:
            combo.setCurrentIndex(combo.findData(previous))
        combo.blockSignals(False)

        return combo.currentData()

    def _time_series_for_current_scope(
        self, channel_idx: int, feature_id: str
    ):
        """(x, series) for whichever Time Analysis scope is selected. "Selected
        ROI" measures each shape's own record on every frame. "Track ID" follows
        one tracked ROI, measuring each frame on that frame's own record."""
        roi_ctrl = self.optari_controller.roi_ctrl
        annotation = self.optari_controller.annotation

        if annotation.time_analysis_track_radio.isChecked():
            track_id = self._refresh_time_analysis_track_combo()
            if track_id is None:
                return np.asarray([]), {}
            return compute_roi_track_time_series(
                track_id,
                roi_ctrl.roi_records,
                self.optari_controller.active_recon_layer,
                channel_idx,
                feature_id,
                clamp=roi_ctrl.intensity_clamp,
            )

        return compute_roi_time_series(
            roi_ctrl.current_records(),
            self.optari_controller.active_recon_layer,
            channel_idx,
            feature_id,
            clamp=roi_ctrl.intensity_clamp,
        )

    def on_generate_time_analysis_clicked(self, event=None) -> None:
        """Compute and plot the time series for the current Time Analysis scope.

        Validates that ROIs and a multi-frame PA layer are selected, lazily creates the
        plot widget on first use, then redraws all series for either the selected ROIs
        or a single tracked ID.
        """
        annotation = self.optari_controller.annotation
        track_scope = annotation.time_analysis_track_radio.isChecked()

        error_msg = ""

        if self.optari_controller.shapes_layer is None:
            error_msg = "No ROIs layer"
        elif self.optari_controller.active_recon_layer is None:
            error_msg = "Select a PA image layer"
        elif (
            not track_scope
            and len(self.optari_controller.shapes_layer.data) == 0
        ):
            error_msg = "No ROIs defined"
        elif track_scope and not self.optari_controller.roi_ctrl.roi_records:
            error_msg = "No tracked ROIs available"
        elif (
            len(self.optari_controller.active_recon_layer.metadata["frames"])
            < 2
        ):
            error_msg = "PA image layer has less than 2 frames"

        if error_msg:
            self.optari_controller.time_analysis.status_label.setText(
                f'<span style="color:red">{error_msg}</span>'
            )
            if self.optari_controller.time_analysis.plot_widget is not None:
                self.optari_controller.time_analysis.plot_widget.clear()
            return

        if self.optari_controller.time_analysis.plot_widget is None:
            plot = pg.PlotWidget()
            plot.showGrid(x=True, y=True)
            plot.addLegend()
            self.optari_controller.time_analysis.plot_widget = plot
            layout = (
                self.optari_controller.time_analysis.plot_container.layout()
            )
            if layout is not None:
                layout.addWidget(plot)

        plot = self.optari_controller.time_analysis.plot_widget
        assert plot is not None

        _, channel_idx = self._current_frame_channel()
        feature_id = (
            self.optari_controller.annotation.time_analysis_feature_combo.currentData()
        )

        self.optari_controller.time_analysis.status_label.setText(
            "Computing time series…"
        )
        x, series = self._time_series_for_current_scope(
            channel_idx, feature_id
        )
        key_label = "Track" if track_scope else "ROI"

        if not series:
            self.optari_controller.time_analysis.status_label.setText(
                f'<span style="color:red">No data for the selected {key_label.lower()}.</span>'
            )
            if self.optari_controller.time_analysis.plot_widget is not None:
                self.optari_controller.time_analysis.plot_widget.clear()
            return

        plot.clear()
        plot.addLegend()

        for position, (key, y) in enumerate(series.items()):
            color = roi_color_for_index(position)
            plot.plot(
                x,
                y,
                pen=pg.mkPen(color=color, width=2),
                symbol="o",
                symbolSize=6,
                symbolBrush=pg.mkBrush(color),
                symbolPen=pg.mkPen(color=color, width=1),
                name=f"{key_label} {key}",
                connect="finite",  # NaN gaps (Track ID scope) must not be drawn over
            )

        vb = plot.getViewBox()
        vb.enableAutoRange(axis=getattr(vb, "YAxis", "y"), enable=True)
        vb.autoRange(padding=0.02)

        # Same source as the x values themselves (roi_utils._time_axis).
        layer_metadata = self.optari_controller.active_recon_layer.metadata
        xlabel = (
            "Time (s)"
            if layer_metadata.get("timestamps") is not None
            else "Frame"
        )

        axis1_value = str(
            self.optari_controller.active_recon_layer.metadata.get(
                "axis1_labels"
            )[channel_idx]
        )

        plot.setLabel("bottom", xlabel)
        plot.setLabel("left", f"{feature_id} ({axis1_value})")

        self.optari_controller.time_analysis.status_label.setText(
            f"Plotted {len(series)} {key_label.lower()}(s) over {len(x)} frame(s) using {feature_id}."
        )

    def on_refresh_histograms_clicked(self, event=None) -> None:
        """Recompute and redraw per-ROI intensity histograms for the current frame and channel."""
        if self.optari_controller.shapes_layer is None:
            self.optari_controller.histograms.status_label.setText(
                "No ROIs layer"
            )
            return
        if len(self.optari_controller.shapes_layer.data) == 0:
            self.optari_controller.histograms.status_label.setText(
                '<span style="color:red">No ROIs defined</span>'
            )
            self._clear_plot_layout(
                self.optari_controller.histograms.plots_container
            )
            return
        if self.optari_controller.active_recon_layer is None:
            self.optari_controller.histograms.status_label.setText(
                "Select a PA image layer"
            )
            return

        frame_idx, channel_idx = self._current_frame_channel()

        self.optari_controller.histograms.status_label.setText(
            "Computing histograms…"
        )

        roi_vals = extract_roi_pixels_for_slice(
            self.optari_controller.roi_ctrl.current_records(),
            self.optari_controller.active_recon_layer,
            frame_idx,
            channel_idx,
            clamp=self.optari_controller.roi_ctrl.intensity_clamp,
        )

        layout = self._clear_plot_layout(
            self.optari_controller.histograms.plots_container
        )

        n_plotted = 0
        for position, (roi_id, vals) in enumerate(roi_vals.items()):
            vals = np.asarray(vals)
            # Remove NaN values before computing histogram
            vals = vals[np.isfinite(vals)]
            if vals.size == 0:
                continue

            counts, edges = np.histogram(
                vals, bins=settings.analysis.histogram_bins
            )

            if counts.size == 0 or edges.size < 2:
                continue

            x = (edges[:-1] + edges[1:]) / 2.0
            width = float(edges[1] - edges[0])

            color = roi_color_for_index(position)
            brush = pg.mkBrush(color)
            pen = pg.mkPen(color)

            plot = pg.PlotWidget()
            plot.setTitle(f"ROI {roi_id}")
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

        self.optari_controller.histograms.status_label.setText(
            f"Plotted {n_plotted} histogram(s) for frame {frame_idx}, channel {channel_idx}."
        )

    def on_refresh_spectrum_clicked(self, event=None) -> None:
        """Recompute and redraw per-ROI spectra across channels for the current frame."""
        if self.optari_controller.shapes_layer is None:
            self.optari_controller.spectrum.status_label.setText(
                "No ROIs layer"
            )
            return
        if len(self.optari_controller.shapes_layer.data) == 0:
            self.optari_controller.spectrum.status_label.setText(
                '<span style="color:red">No ROIs defined</span>'
            )
            self._clear_plot_layout(
                self.optari_controller.spectrum.plots_container
            )
            return
        if self.optari_controller.active_recon_layer is None:
            self.optari_controller.spectrum.status_label.setText(
                "Select a PA image layer"
            )
            return

        frame_idx, _ = self._current_frame_channel()

        self.optari_controller.spectrum.status_label.setText(
            "Computing spectra…"
        )

        x, series, x_tick_labels = compute_roi_spectra(
            self.optari_controller.roi_ctrl.current_records(),
            self.optari_controller.active_recon_layer,
            frame_idx,
            clamp=self.optari_controller.roi_ctrl.intensity_clamp,
        )

        layout = self._clear_plot_layout(
            self.optari_controller.spectrum.plots_container
        )

        n_plotted = 0
        axis1_name = str(
            self.optari_controller.active_recon_layer.metadata.get(
                "axis1_name", "Channel"
            )
        )
        x_label = "Channel" if axis1_name.lower() == "channel" else axis1_name
        for position, (roi_id, y) in enumerate(series.items()):
            if y.size == 0 or np.all(np.isnan(y)):
                continue

            color = roi_color_for_index(position)

            plot = pg.PlotWidget()
            plot.setTitle(f"ROI {roi_id}")
            plot.showGrid(x=True, y=True)
            plot.setLabel("bottom", x_label)
            plot.setLabel("left", "Mean intensity")
            plot.plot(
                x,
                y,
                pen=pg.mkPen(color=color, width=2),
                symbol="o",
                symbolSize=6,
                symbolBrush=pg.mkBrush(color),
                symbolPen=pg.mkPen(color=color, width=1),
            )

            if x_tick_labels:
                tick_values = [
                    (float(i), label) for i, label in enumerate(x_tick_labels)
                ]
                plot.getAxis("bottom").setTicks([tick_values])

            if layout is not None:
                layout.addWidget(plot)
            n_plotted += 1

        self.optari_controller.spectrum.status_label.setText(
            f"Plotted {n_plotted} spectra for frame {frame_idx}."
        )
