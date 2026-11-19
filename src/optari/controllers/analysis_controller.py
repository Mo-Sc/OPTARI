"""Analysis controller: time-series, histogram and spectral plots (pyqtgraph) over selected ROIs,
and the scan's motion score per frame."""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
import pyqtgraph as pg

from optari.config import settings
from optari.controllers.base import TaskControllerBase
from optari.roi.roi_utils import (
    compute_roi_spectra,
    compute_roi_time_series,
    compute_roi_track_time_series,
    extract_roi_pixels_for_slice,
    time_axis,
)
from optari.utils.misc import roi_color_for_index
from optari.utils.motion import standout_frames
from optari.utils.viewer import selected_frame_and_channel

logger = logging.getLogger(__name__)


class AnalysisController(TaskControllerBase):
    """Temporal analysis, histograms, and spectral plotting helpers."""

    def refresh_ui(self) -> None:
        """Refresh gating for the histogram/spectrum/time-analysis buttons."""
        has_data = (
            self.optari_controller.shapes_layer is not None
            and self.optari_controller.active_recon_layer is not None
        )
        self.optari_controller.time_analysis_dock.refresh_button.setEnabled(
            has_data
        )
        self.optari_controller.histogram_dock.refresh_button.setEnabled(
            has_data
        )
        self.optari_controller.spectrum_dock.refresh_button.setEnabled(
            has_data
        )
        self.optari_controller.motion_dock.refresh_button.setEnabled(
            self.optari_controller.active_us_layer is not None
        )

    def _signal_bindings(self) -> list[tuple[object, Callable]]:
        """Plot dock signals, and the Time Analysis scope in the annotation dock."""
        ctrl = self.optari_controller
        return [
            (
                ctrl.time_analysis_dock.refresh_button.clicked,
                self.on_generate_time_analysis_clicked,
            ),
            (
                ctrl.histogram_dock.refresh_button.clicked,
                self.on_refresh_histograms_clicked,
            ),
            (
                ctrl.spectrum_dock.refresh_button.clicked,
                self.on_refresh_spectrum_clicked,
            ),
            (
                ctrl.annotation_dock.time_analysis_track_radio.toggled,
                self.on_time_analysis_scope_changed,
            ),
            (
                ctrl.motion_dock.refresh_button.clicked,
                self.on_refresh_motion_clicked,
            ),
            (
                ctrl.motion_dock.frame_line.sigPositionChangeFinished,
                self.on_motion_frame_line_dragged,
            ),
            (
                ctrl.time_analysis_dock.frame_line.sigPositionChangeFinished,
                self.on_time_frame_line_dragged,
            ),
        ]

    def on_active_layers_changed(self) -> None:
        """Gate the plot buttons on the new layers. Without a US layer the motion plot says why."""
        self.refresh_ui()
        if self.optari_controller.active_us_layer is None:
            self.show_motion_scores(compute=False)

    def on_frame_changed(self, frame_idx: int) -> None:
        self.update_frame_lines()

    def on_time_analysis_scope_changed(self, checked: bool) -> None:
        """When the user switches between the "Selected ROI" and "Track ID" scopes,
        refresh the track-id combo, show only tracks that exist in the current
        ROI records.
        """
        if checked:
            self._refresh_time_analysis_track_combo()

    # ============ motion ============
    def on_refresh_motion_clicked(self) -> None:
        """Score the loaded scan's motion (once, then cached) and plot it."""
        self.show_motion_scores(compute=True)

    def show_motion_scores(self, *, compute: bool) -> None:
        """Plot both motion scores per frame of the loaded scan, or say why there are none.

        Without *compute* only already cached scores are plotted, so a scan load can
        refresh the dock for free when a motion-based default frame scored it anyway.
        """
        dock = self.optari_controller.motion_dock
        scores = self.optari_controller.scan_ctrl.motion_scores(
            compute=compute
        )
        if scores is None:
            dock.spectral_curve.setData([], [])
            dock.frame_curve.setData([], [])
            dock.stillest.setData([], [])
            dock.spectral_standout.setOpts(x=[], height=[])
            dock.frame_standout.setOpts(x=[], height=[])
            dock.frame_line.hide()
            if self.optari_controller.pa_data is None:
                dock.status_label.setText("Load a scan to score its motion.")
            elif self.optari_controller.active_us_layer is None:
                dock.status_label.setText(
                    "This scan has no ultrasound to score motion on."
                )
            else:
                dock.status_label.setText(
                    "Click 'Refresh' to score motion per frame."
                )
            return

        spectral, frame = scores["spectral_motion"], scores["frame_motion"]
        stillest_frame = int(np.argmin(frame))
        dock.frame_curve.setData(np.arange(len(frame)), frame)
        frame_out = np.flatnonzero(standout_frames(frame))
        dock.frame_standout.setOpts(
            x=frame_out, height=np.ones(len(frame_out))
        )
        if spectral is None:
            dock.spectral_curve.setData([], [])
            dock.spectral_standout.setOpts(x=[], height=[])
            dock.stillest.setData([stillest_frame], [frame[stillest_frame]])
            dock.status_label.setText(
                "One image per wavelength set, so no spectral motion. Lowest "
                f"frame-to-frame motion: frame {stillest_frame} (green). "
                f"{len(frame_out)} frame(s) with unusual motion shaded."
            )
        else:
            stillest_spectral = int(np.nanargmin(spectral))
            # NaN: wavelength sets without a US refresh, drawn as gaps
            dock.spectral_curve.setData(
                np.arange(len(spectral)), spectral, connect="finite"
            )
            spectral_out = np.flatnonzero(standout_frames(spectral))
            dock.spectral_standout.setOpts(
                x=spectral_out, height=np.ones(len(spectral_out))
            )
            dock.stillest.setData(
                [stillest_spectral, stillest_frame],
                [spectral[stillest_spectral], frame[stillest_frame]],
            )
            dock.status_label.setText(
                f"Lowest motion: frame {stillest_spectral} spectral, frame "
                f"{stillest_frame} frame-to-frame (green). Unusual motion shaded: "
                f"{len(spectral_out)} spectral, {len(frame_out)} frame-to-frame. "
                f"{int(np.isnan(spectral).sum())} wavelength set(s) without a US "
                "refresh are not scored."
            )
        dock.frame_line.show()
        self.update_frame_lines()

    def clear_plots(self) -> None:
        """Empty the Temporal, Histogram and Spectral plots.

        Called on a scan change
        """
        for dock in (
            self.optari_controller.time_analysis_dock,
            self.optari_controller.histogram_dock,
            self.optari_controller.spectrum_dock,
        ):
            dock.clear()

    def update_frame_lines(self) -> None:
        """Move the Motion and Temporal frame lines to the viewer's current frame."""
        frame_channel = selected_frame_and_channel(self.viewer)
        if frame_channel is None:
            return
        frame = frame_channel[0]
        self.optari_controller.motion_dock.frame_line.setValue(frame)

        time_analysis = self.optari_controller.time_analysis_dock
        plotted = np.flatnonzero(time_analysis.plotted_frames == frame)
        # A frame the plot has no point for (not in the plotted layer) gets no line.
        time_analysis.frame_line.setVisible(plotted.size > 0)
        if plotted.size:
            time_analysis.frame_line.setValue(
                time_analysis.plotted_x[plotted[0]]
            )

    def on_motion_frame_line_dragged(self, line) -> None:
        """Show the frame the user dragged the line to."""
        last_frame = int(self.viewer.dims.nsteps[0]) - 1
        self.viewer.dims.set_point(
            0, int(np.clip(round(line.value()), 0, last_frame))
        )
        # Snap the line onto the frame actually shown, also when it did not change.
        self.update_frame_lines()

    def on_time_frame_line_dragged(self, line) -> None:
        """Show the plotted frame nearest to where the user dragged the line."""
        time_analysis = self.optari_controller.time_analysis_dock
        nearest = np.argmin(np.abs(time_analysis.plotted_x - line.value()))
        self.viewer.dims.set_point(
            0, int(time_analysis.plotted_frames[nearest])
        )
        self.update_frame_lines()

    def _current_frame_channel(self) -> tuple[int, int]:
        """Current (frame, channel) from viewer dims. Plots fall back to the first."""
        return selected_frame_and_channel(self.viewer) or (0, 0)

    def _refresh_time_analysis_track_combo(self) -> int | None:
        """Repopulate the track-id combo from live ROI records.

        Keeps the previous selection if that track still exists. Returns the
        selected track id, or ``None`` if no tracked ROI exists to plot.
        """
        combo = (
            self.optari_controller.annotation_dock.time_analysis_track_id_combo
        )
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
        ROI" measures every ROI shown on this frame, with its current outline, on
        every frame. "Track ID" follows
        one tracked ROI, measuring each frame on that frame's own record."""
        roi_ctrl = self.optari_controller.roi_ctrl
        annotation = self.optari_controller.annotation_dock

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

    def _missing_plot_input(
        self, *, track_scope: bool = False, min_frames: int = 1
    ) -> str | None:
        """What a plot still lacks before it can be drawn, or None when it has everything.

        *track_scope* asks for tracked ROI records instead of shapes on this frame.
        """
        ctrl = self.optari_controller
        if ctrl.shapes_layer is None:
            return "No ROIs layer"
        if ctrl.active_recon_layer is None:
            return "Select a PA image layer"
        if track_scope and not ctrl.roi_ctrl.roi_records:
            return "No tracked ROIs available"
        if not track_scope and len(ctrl.shapes_layer.data) == 0:
            return "No ROIs defined"
        if len(ctrl.active_recon_layer.metadata["frames"]) < min_frames:
            return f"PA image layer has less than {min_frames} frames"
        return None

    @staticmethod
    def _show_plot_error(dock, message: str) -> None:
        """Empty *dock*'s plots and say in red why there is nothing to show."""
        dock.clear()
        dock.status_label.setText(f'<span style="color:red">{message}</span>')

    def on_generate_time_analysis_clicked(self, event=None) -> None:
        """Compute and plot the time series for the current Time Analysis scope.

        Validates that ROIs and a multi-frame PA layer are selected, then redraws all
        series for either the selected ROIs or a single tracked ID.
        """
        ctrl = self.optari_controller
        dock = ctrl.time_analysis_dock
        track_scope = (
            ctrl.annotation_dock.time_analysis_track_radio.isChecked()
        )
        error = self._missing_plot_input(track_scope=track_scope, min_frames=2)
        if error:
            self._show_plot_error(dock, error)
            return

        layer = ctrl.active_recon_layer
        _, channel_idx = self._current_frame_channel()
        feature_id = (
            ctrl.annotation_dock.time_analysis_feature_combo.currentData()
        )

        dock.status_label.setText("Computing time series…")
        # The computation below blocks the event loop, paint the text before it.
        dock.status_label.repaint()
        x, series = self._time_series_for_current_scope(
            channel_idx, feature_id
        )
        key_label = "Track" if track_scope else "ROI"

        if not series:
            self._show_plot_error(
                dock, f"No data for the selected {key_label.lower()}."
            )
            return

        plot = dock.plot_widget
        plot.clear()
        plot.addLegend()
        plot.addItem(dock.frame_line, ignoreBounds=True)

        colors = ctrl.roi_ctrl.colors_by_roi_id()
        for key, y in series.items():
            # keyed by track id in the Track ID scope, by ROI id otherwise
            color = roi_color_for_index(key) if track_scope else colors[key]
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
        vb.enableAutoRange(axis=vb.YAxis, enable=True)
        vb.autoRange(padding=0.02)

        dock.plotted_frames, dock.plotted_x = time_axis(layer, channel_idx)
        self.update_frame_lines()

        # Same source as the x values themselves (roi_utils.time_axis).
        xlabel = (
            "Time (s)"
            if layer.metadata.get("timestamps") is not None
            else "Frame"
        )
        axis1_value = str(layer.metadata["axis1_labels"][channel_idx])
        plot.setLabel("bottom", xlabel)
        plot.setLabel("left", f"{feature_id} ({axis1_value})")

        dock.status_label.setText(
            f"Plotted {len(series)} {key_label.lower()}(s) over {len(x)} frame(s) using {feature_id}."
        )

    def on_refresh_histograms_clicked(self, event=None) -> None:
        """Recompute and redraw per-ROI intensity histograms for the current frame and channel."""
        ctrl = self.optari_controller
        dock = ctrl.histogram_dock
        error = self._missing_plot_input()
        if error:
            self._show_plot_error(dock, error)
            return

        frame_idx, channel_idx = self._current_frame_channel()
        roi_vals = extract_roi_pixels_for_slice(
            ctrl.roi_ctrl.current_records(),
            ctrl.active_recon_layer,
            frame_idx,
            channel_idx,
            clamp=ctrl.roi_ctrl.intensity_clamp,
        )

        dock.clear()
        layout = dock.plots_container.layout()
        colors = ctrl.roi_ctrl.colors_by_roi_id()
        n_plotted = 0
        for roi_id, vals in roi_vals.items():
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

            color = colors[roi_id]
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

            layout.addWidget(plot)
            n_plotted += 1

        dock.status_label.setText(
            f"Plotted {n_plotted} histogram(s) for frame {frame_idx}, channel {channel_idx}."
        )

    def on_refresh_spectrum_clicked(self, event=None) -> None:
        """Recompute and redraw per-ROI spectra across channels for the current frame."""
        ctrl = self.optari_controller
        dock = ctrl.spectrum_dock
        error = self._missing_plot_input()
        if error:
            self._show_plot_error(dock, error)
            return

        frame_idx, _ = self._current_frame_channel()
        x, series, x_tick_labels = compute_roi_spectra(
            ctrl.roi_ctrl.current_records(),
            ctrl.active_recon_layer,
            frame_idx,
            clamp=ctrl.roi_ctrl.intensity_clamp,
        )

        dock.clear()
        layout = dock.plots_container.layout()
        n_plotted = 0
        colors = ctrl.roi_ctrl.colors_by_roi_id()
        for roi_id, y in series.items():
            if y.size == 0 or np.all(np.isnan(y)):
                continue

            color = colors[roi_id]

            plot = pg.PlotWidget()
            plot.setTitle(f"ROI {roi_id}")
            plot.showGrid(x=True, y=True)
            plot.setLabel("bottom", "Channel")
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

            layout.addWidget(plot)
            n_plotted += 1

        dock.status_label.setText(
            f"Plotted {n_plotted} spectra for frame {frame_idx}."
        )
