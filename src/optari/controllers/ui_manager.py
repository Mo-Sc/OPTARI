from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from qtpy.QtCore import QTimer

from optari.widgets.annotation_dock import create_annotation_dock
from optari.widgets.histogram_dock import create_histogram_dock
from optari.widgets.info_dock import create_info_dock
from optari.widgets.reconstruction_dock import create_reconstruction_dock
from optari.widgets.roi_dock import create_roi_dock
from optari.widgets.scan_browser_dock import create_scan_browser_dock
from optari.widgets.segmentation_dock import create_segmentation_dock
from optari.widgets.spectrum_dock import create_spectrum_dock
from optari.widgets.time_analysis_dock import create_time_analysis_dock
from optari.widgets.unmixing_dock import create_unmixing_dock

if TYPE_CHECKING:
    from optari.controllers.optari_controller import OptariController

logger = logging.getLogger(__name__)


class UiManager:
    """Build and wire dock widgets for a single OPTARI controller instance."""

    # ============ dock setup ============
    @staticmethod
    def setup_docks(controller: "OptariController") -> None:
        # Create docks once per controller instance.
        if controller.scan_browser is None:
            controller.scan_browser = create_scan_browser_dock()
            controller._scan_browser_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.scan_browser.widget,
                    name="Scan Browser",
                    area="right",
                )
            )

        if controller.info is None:
            # info dock is not tabified, but floating by default
            controller.info = create_info_dock()
            controller._info_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.info.widget,
                    name="Active Slice Info",
                    area="left",
                )
            )
            controller._info_dock_widget.setFloating(True)

        if controller.roi is None:
            controller.roi = create_roi_dock()
            controller._roi_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.roi.widget,
                    name="Tabular",
                    area="bottom",
                )
            )

        if controller.time_analysis is None:
            controller.time_analysis = create_time_analysis_dock()
            controller._time_analysis_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.time_analysis.widget,
                    name="Time Analysis",
                    area="bottom",
                    tabify=True,
                )
            )

        if controller.histograms is None:
            controller.histograms = create_histogram_dock()
            controller._histograms_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.histograms.widget,
                    name="Histogram",
                    area="bottom",
                    tabify=True,
                )
            )

        if controller.spectrum is None:
            controller.spectrum = create_spectrum_dock()
            controller._spectrum_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.spectrum.widget,
                    name="Spectrum",
                    area="bottom",
                    tabify=True,
                )
            )

        if controller.annotation is None:
            controller.annotation = create_annotation_dock()
            controller._annotation_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.annotation.widget,
                    name="Annotation",
                    area="right",
                    tabify=True,
                )
            )

        if controller.segmentation is None:
            controller.segmentation = create_segmentation_dock()
            controller._segmentation_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.segmentation.widget,
                    name="Segmentation",
                    area="right",
                    tabify=True,
                )
            )

        if controller.unmixing is None:
            controller.unmixing = create_unmixing_dock()
            controller._unmixing_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.unmixing.widget,
                    name="Unmixing",
                    area="right",
                    tabify=True,
                )
            )

        if controller.reconstruction is None:
            controller.reconstruction = create_reconstruction_dock()
            controller._reconstruction_dock_widget = (
                controller.viewer.window.add_dock_widget(
                    controller.reconstruction.widget,
                    name="Reconstruction",
                    area="right",
                    tabify=True,
                )
            )

        # Select default docks after the event loop has started
        QTimer.singleShot(
            0, lambda: UiManager._select_default_docks(controller)
        )

        logger.info("Dock widgets created and added to the viewer window.")

    # ============ dock layout ============
    @staticmethod
    def _select_default_docks(controller: "OptariController") -> None:
        # by default, Scan Browser on the right and Tables at the bottom
        if controller._roi_dock_widget is not None:
            controller._roi_dock_widget.raise_()
        if controller._scan_browser_dock_widget is not None:
            controller._scan_browser_dock_widget.raise_()

    @staticmethod
    def _install_shutdown_hook(controller: "OptariController") -> None:
        """Run controller teardown from the main window's close event."""
        window = controller.viewer.window._qt_window
        napari_close_event = window.closeEvent

        def close_event(event) -> None:
            napari_close_event(event)
            # napari ignores the event when the user cancels its confirm-close dialog.
            if event.isAccepted():
                controller.shutdown()

        window.closeEvent = close_event

    @staticmethod
    def connect_events(controller: "OptariController") -> None:
        # -------- viewer core events --------
        controller._connect_shapes_layer_events()
        controller.viewer.dims.events.point.connect(controller.on_dims_changed)
        controller.viewer.layers.selection.events.changed.connect(
            controller.on_selection_changed
        )
        controller.info.metadata_button.clicked.connect(
            controller.on_metadata_clicked
        )

        UiManager._install_shutdown_hook(controller)
        # TODO: should reordering / adding layers trigger anything?
        # controller.viewer.layers.events.reordered.connect(controller.on_layers_changed)
        # controller.viewer.layers.events.inserted.connect(controller.on_layers_changed)
        controller.viewer.layers.events.removed.connect(
            controller.on_layer_removed
        )

        # -------- dock signal wiring in controllers --------
        controller.scan_ctrl.bind_events()
        controller.roi_ctrl.bind_events()
        controller.analysis_ctrl.bind_events()
        controller.unmixing_ctrl.bind_events()
        controller.reconstruction_ctrl.bind_events()
        controller.segmentation_ctrl.bind_events()
