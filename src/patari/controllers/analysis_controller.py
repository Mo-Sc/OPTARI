from __future__ import annotations

import logging
import numpy as np
import pyqtgraph as pg

from patari.roi.roi_utils import (
    compute_roi_time_series,
    compute_roi_spectra,
    extract_roi_pixels_for_slice,
)
from patari.utils.misc import roi_color_for_index
from patari.controllers.base import TaskControllerBase

logger = logging.getLogger(__name__)


class AnalysisController(TaskControllerBase):
    """Time analysis, histograms, and spectral plotting helpers."""

    HISTOGRAM_BINS = 50

    def __init__(self, parent_controller):
        super().__init__(parent_controller)

    def bind_events(self) -> None:
        """Connect analysis dock signals."""
        self.patari_controller.time_analysis.generate_button.clicked.connect(
            self.on_generate_time_analysis_clicked
        )

        self.patari_controller.histograms.refresh_button.clicked.connect(
            self.on_refresh_histograms_clicked
        )

        self.patari_controller.spectrum.refresh_button.clicked.connect(
            self.on_refresh_spectrum_clicked
        )

    def unbind_events(self) -> None:
        """Disconnect analysis dock signals."""
        try:
            self.patari_controller.time_analysis.generate_button.clicked.disconnect(
                self.on_generate_time_analysis_clicked
            )
            self.patari_controller.histograms.refresh_button.clicked.disconnect(
                self.on_refresh_histograms_clicked
            )
            self.patari_controller.spectrum.refresh_button.clicked.disconnect(
                self.on_refresh_spectrum_clicked
            )
        except Exception as e:
            logger.exception("Error unbinding analysis dock signals: %s", e)

    def _clamp_kwargs(self) -> dict[str, object | None]:
        """Shared ROI intensity filtering settings for all analysis calls."""
        return {
            "clamp_min": self.patari_controller.roi_intensity_min,
            "clamp_max": self.patari_controller.roi_intensity_max,
            "clamp_mode": (
                self.patari_controller.roi_intensity_mode or "clip"
            ),
        }

    def _current_frame_channel(self) -> tuple[int, int]:
        """Return current (frame, channel) from viewer dims with safe defaults."""
        pt = list(self.viewer.dims.point)
        frame_idx = int(round(pt[0])) if len(pt) >= 1 else 0
        channel_idx = int(round(pt[1])) if len(pt) >= 2 else 0
        return frame_idx, channel_idx

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

    def on_generate_time_analysis_clicked(self, event=None) -> None:
        if self.patari_controller.time_analysis is None:
            return

        error_msg = ""

        if self.patari_controller.shapes_layer is None:
            error_msg = "No ROIs layer"
        elif self.patari_controller.active_recon_layer is None:
            error_msg = "Select a PA image layer"
        elif len(self.patari_controller.shapes_layer.data) == 0:
            error_msg = "No ROIs defined"
        elif len(self.patari_controller.active_recon_layer.metadata["frames"]) < 2:
            error_msg = "PA image layer has less than 2 frames"

        if error_msg:
            self.patari_controller.time_analysis.status_label.setText(
                f'<span style="color:red">{error_msg}</span>'
            )
            if self.patari_controller.time_analysis.plot_widget is not None:
                self.patari_controller.time_analysis.plot_widget.clear()
            return

        if self.patari_controller.time_analysis.plot_widget is None:
            plot = pg.PlotWidget()
            plot.showGrid(x=True, y=True)
            plot.addLegend()
            self.patari_controller.time_analysis.plot_widget = plot
            layout = (
                self.patari_controller.time_analysis.plot_container.layout()
            )
            if layout is not None:
                layout.addWidget(plot)

        plot = self.patari_controller.time_analysis.plot_widget
        assert plot is not None

        _, channel_idx = self._current_frame_channel()
        feature_id = self.patari_controller.annotation.time_analysis_feature_combo.currentData()

        self.patari_controller.time_analysis.status_label.setText(
            "Computing time series…"
        )
        x, series = compute_roi_time_series(
            self.patari_controller.shapes_layer,
            self.patari_controller.active_recon_layer,
            channel_idx,
            feature_id,
            **self._clamp_kwargs(),
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
                symbolSize=6,
                symbolBrush=pg.mkBrush(color),
                symbolPen=pg.mkPen(color=color, width=1),
                name=f"ROI {roi_index}",
            )

        vb = plot.getViewBox()
        vb.enableAutoRange(axis=getattr(vb, "YAxis", "y"), enable=True)
        vb.autoRange(padding=0.02)

        xlabel = (
            "Time (s)"
            if self.patari_controller.timestamps is not None
            else "Frame"
        )

        axis1_value = str(
            self.patari_controller.active_recon_layer.metadata.get("axis1_labels")[
                channel_idx
            ]
        )

        plot.setLabel("bottom", xlabel)
        plot.setLabel("left", f"{feature_id} ({axis1_value})")

        self.patari_controller.time_analysis.status_label.setText(
            f"Plotted {len(series)} ROI(s) over {len(x)} frame(s) using {feature_id}."
        )

    def on_refresh_histograms_clicked(self, event=None) -> None:
        if self.patari_controller.histograms is None:
            return
        if self.patari_controller.shapes_layer is None:
            self.patari_controller.histograms.status_label.setText(
                "No ROIs layer"
            )
            return
        if len(self.patari_controller.shapes_layer.data) == 0:
            self.patari_controller.histograms.status_label.setText(
                '<span style="color:red">No ROIs defined</span>'
            )
            self._clear_plot_layout(
                self.patari_controller.histograms.plots_container
            )
            return
        if self.patari_controller.active_recon_layer is None:
            self.patari_controller.histograms.status_label.setText(
                "Select a PA image layer"
            )
            return

        frame_idx, channel_idx = self._current_frame_channel()

        self.patari_controller.histograms.status_label.setText(
            "Computing histograms…"
        )

        roi_vals = extract_roi_pixels_for_slice(
            self.patari_controller.shapes_layer,
            self.patari_controller.active_recon_layer,
            frame_idx,
            channel_idx,
            **self._clamp_kwargs(),
        )

        layout = self._clear_plot_layout(
            self.patari_controller.histograms.plots_container
        )

        n_plotted = 0
        for roi_index, vals in roi_vals.items():
            vals = np.asarray(vals)
            if vals.size == 0:
                continue

            counts, edges = np.histogram(vals, bins=self.HISTOGRAM_BINS)

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

        self.patari_controller.histograms.status_label.setText(
            f"Plotted {n_plotted} histogram(s) for frame {frame_idx}, channel {channel_idx}."
        )

    def on_refresh_spectrum_clicked(self, event=None) -> None:
        if self.patari_controller.spectrum is None:
            return
        if self.patari_controller.shapes_layer is None:
            self.patari_controller.spectrum.status_label.setText(
                "No ROIs layer"
            )
            return
        if len(self.patari_controller.shapes_layer.data) == 0:
            self.patari_controller.spectrum.status_label.setText(
                '<span style="color:red">No ROIs defined</span>'
            )
            self._clear_plot_layout(
                self.patari_controller.spectrum.plots_container
            )
            return
        if self.patari_controller.active_recon_layer is None:
            self.patari_controller.spectrum.status_label.setText(
                "Select a PA image layer"
            )
            return

        frame_idx, _ = self._current_frame_channel()

        self.patari_controller.spectrum.status_label.setText(
            "Computing spectra…"
        )

        x, series, x_tick_labels = compute_roi_spectra(
            self.patari_controller.shapes_layer,
            self.patari_controller.active_recon_layer,
            frame_idx,
            **self._clamp_kwargs(),
        )

        layout = self._clear_plot_layout(
            self.patari_controller.spectrum.plots_container
        )

        n_plotted = 0
        axis1_name = str(
            self.patari_controller.active_recon_layer.metadata.get(
                "axis1_name", "Channel"
            )
        )
        x_label = "Channel" if axis1_name.lower() == "channel" else axis1_name
        for roi_index, y in series.items():
            if y.size == 0 or np.all(np.isnan(y)):
                continue

            color = roi_color_for_index(int(roi_index))

            plot = pg.PlotWidget()
            plot.setTitle(f"ROI {roi_index}")
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

        self.patari_controller.spectrum.status_label.setText(
            f"Plotted {n_plotted} spectra for frame {frame_idx}."
        )
