from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from patari.roi.roi_utils import (
    compute_roi_time_series,
    compute_roi_spectra,
    extract_roi_pixels_for_slice,
)
from patari.utils.misc import roi_color_for_index


class AnalysisController:
    """Time analysis, histograms, and spectral plotting helpers."""

    HISTOGRAM_BINS = 50

    @staticmethod
    def _clamp_kwargs(controller) -> dict[str, object | None]:
        """Shared ROI intensity filtering settings for all analysis calls."""
        return {
            "clamp_min": controller.roi_intensity_min,
            "clamp_max": controller.roi_intensity_max,
            "clamp_mode": (controller.roi_intensity_mode or "clip"),
        }

    @staticmethod
    def _current_frame_wavelength(controller) -> tuple[int, int]:
        """Return current (frame, wavelength) from viewer dims with safe defaults."""
        pt = list(controller.viewer.dims.point)
        frame_idx = int(round(pt[0])) if len(pt) >= 1 else 0
        wav_idx = int(round(pt[1])) if len(pt) >= 2 else 0
        return frame_idx, wav_idx

    @staticmethod
    def _clear_plot_layout(container) -> object | None:
        """Remove and delete all plot widgets from a dock container layout."""
        layout = container.layout()
        if layout is None:
            return None

        # Important: removing + deleteLater avoids accumulating hidden widgets
        # across repeated refreshes and keeps memory usage predictable.
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        return layout

    @staticmethod
    def on_generate_time_analysis_clicked(controller, event=None) -> None:
        if controller.time_analysis is None:
            return

        error_msg = ""

        if controller.shapes_layer is None:
            error_msg = "No ROIs layer"
        elif controller.active_layer is None:
            error_msg = "Select a PA image layer"
        elif len(controller.shapes_layer.data) == 0:
            error_msg = "No ROIs defined"
        elif len(controller.active_layer.metadata["frames"]) < 2:
            error_msg = "PA image layer has less than 2 frames"

        if error_msg:
            controller.time_analysis.status_label.setText(
                f'<span style="color:red">{error_msg}</span>'
            )
            if controller.time_analysis.plot_widget is not None:
                controller.time_analysis.plot_widget.clear()
            return

        # Lazily create the plot once and reuse it for fast refreshes.
        if controller.time_analysis.plot_widget is None:
            plot = pg.PlotWidget()
            plot.showGrid(x=True, y=True)
            plot.addLegend()
            controller.time_analysis.plot_widget = plot
            layout = controller.time_analysis.plot_container.layout()
            if layout is not None:
                layout.addWidget(plot)

        plot = controller.time_analysis.plot_widget
        assert plot is not None

        _, wav_idx = AnalysisController._current_frame_wavelength(controller)

        controller.time_analysis.status_label.setText("Computing time series…")
        x, series = compute_roi_time_series(
            controller.shapes_layer,
            controller.active_layer,
            wav_idx,
            **AnalysisController._clamp_kwargs(controller),
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

        # Re-autoscale y-axis on every refresh so ROI curves remain visible
        # even when intensity range changes strongly between wavelengths.
        vb = plot.getViewBox()
        vb.enableAutoRange(axis=getattr(vb, "YAxis", "y"), enable=True)
        vb.autoRange(padding=0.02)

        xlabel = "Time (s)" if controller.timestamps is not None else "Frame"
        plot.setLabel("bottom", xlabel)
        plot.setLabel("left", "Mean intensity")

        controller.time_analysis.status_label.setText(
            f"Plotted {len(series)} ROI(s) over {len(x)} frame(s)."
        )

    @staticmethod
    def on_refresh_histograms_clicked(controller, event=None) -> None:
        if controller.histograms is None:
            return
        if controller.shapes_layer is None:
            controller.histograms.status_label.setText("No ROIs layer")
            return
        if len(controller.shapes_layer.data) == 0:
            controller.histograms.status_label.setText(
                '<span style="color:red">No ROIs defined</span>'
            )
            AnalysisController._clear_plot_layout(
                controller.histograms.plots_container
            )
            return
        if controller.active_layer is None:
            controller.histograms.status_label.setText(
                "Select a PA image layer"
            )
            return

        frame_idx, wav_idx = AnalysisController._current_frame_wavelength(
            controller
        )

        controller.histograms.status_label.setText("Computing histograms…")

        roi_vals = extract_roi_pixels_for_slice(
            controller.shapes_layer,
            controller.active_layer,
            frame_idx,
            wav_idx,
            **AnalysisController._clamp_kwargs(controller),
        )

        layout = AnalysisController._clear_plot_layout(
            controller.histograms.plots_container
        )

        n_plotted = 0
        for roi_index, vals in roi_vals.items():
            vals = np.asarray(vals)
            if vals.size == 0:
                continue

            counts, edges = np.histogram(
                vals, bins=AnalysisController.HISTOGRAM_BINS
            )

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

        controller.histograms.status_label.setText(
            f"Plotted {n_plotted} histogram(s) for frame {frame_idx}, wav {wav_idx}."
        )

    @staticmethod
    def on_refresh_spectrum_clicked(controller, event=None) -> None:
        if controller.spectrum is None:
            return
        if controller.shapes_layer is None:
            controller.spectrum.status_label.setText("No ROIs layer")
            return
        if len(controller.shapes_layer.data) == 0:
            controller.spectrum.status_label.setText(
                '<span style="color:red">No ROIs defined</span>'
            )
            AnalysisController._clear_plot_layout(
                controller.spectrum.plots_container
            )
            return
        if controller.active_layer is None:
            controller.spectrum.status_label.setText("Select a PA image layer")
            return

        frame_idx, _ = AnalysisController._current_frame_wavelength(controller)

        controller.spectrum.status_label.setText("Computing spectra…")

        x, series = compute_roi_spectra(
            controller.shapes_layer,
            controller.active_layer,
            frame_idx,
            **AnalysisController._clamp_kwargs(controller),
        )

        layout = AnalysisController._clear_plot_layout(
            controller.spectrum.plots_container
        )

        n_plotted = 0
        for roi_index, y in series.items():
            if y.size == 0 or np.all(np.isnan(y)):
                continue

            color = roi_color_for_index(int(roi_index))

            plot = pg.PlotWidget()
            plot.setTitle(f"ROI {roi_index}")
            plot.showGrid(x=True, y=True)
            plot.setLabel("bottom", "Wavelength (nm)")
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

            if layout is not None:
                layout.addWidget(plot)
            n_plotted += 1

        controller.spectrum.status_label.setText(
            f"Plotted {n_plotted} spectra for frame {frame_idx}."
        )
