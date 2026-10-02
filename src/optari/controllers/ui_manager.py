from __future__ import annotations

import logging
from functools import partial
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
        """Create OPTARI's docks and register them, with napari's own, in
        ``controller.dock_widgets``. The order there is the order of OPTARI ▸ Docks
        and of the Settings dock list; tabified docks join the previous one in their area.
        """
        add = partial(UiManager._add_dock, controller)
        controller.scan_browser = add(
            create_scan_browser_dock(), "Scan Browser", "right", tabify=False
        )
        controller.info = add(
            create_info_dock(), "Active Slice Info", "left", tabify=False
        )
        controller.roi = add(
            create_roi_dock(), "Tabular", "bottom", tabify=False
        )
        controller.time_analysis = add(
            create_time_analysis_dock(), "Temporal", "bottom"
        )
        controller.histograms = add(
            create_histogram_dock(), "Histogram", "bottom"
        )
        controller.spectrum = add(create_spectrum_dock(), "Spectral", "bottom")
        controller.annotation = add(
            create_annotation_dock(), "Annotation", "right"
        )
        controller.segmentation = add(
            create_segmentation_dock(), "Segmentation", "right"
        )
        controller.unmixing = add(create_unmixing_dock(), "Unmixing", "right")
        controller.reconstruction = add(
            create_reconstruction_dock(), "Reconstruction", "right"
        )
        # The info dock floats by default instead of sitting in the left area.
        controller.dock_widgets["Active Slice Info"].setFloating(True)

        # napari's own docks, so they can be toggled and defaulted like OPTARI's.
        # private _qt_viewer (public qt_viewer is deprecated), still present in napari 0.9.1
        qt_viewer = controller.viewer.window._qt_viewer
        controller.dock_widgets["Layer Controls"] = qt_viewer.dockLayerControls
        controller.dock_widgets["Layer List"] = qt_viewer.dockLayerList

        # Select default docks after the event loop has started
        QTimer.singleShot(
            0, lambda: UiManager._select_default_docks(controller)
        )

        logger.info("Dock widgets created and added to the viewer window.")

    @staticmethod
    def _add_dock(
        controller, dock, title: str, area: str, tabify: bool = True
    ):
        """Add *dock*'s widget to the window under *title* and return *dock*."""
        controller.dock_widgets[title] = (
            controller.viewer.window.add_dock_widget(
                dock.widget, name=title, area=area, tabify=tabify
            )
        )
        return dock

    # ============ dock layout ============
    @staticmethod
    def _select_default_docks(controller: "OptariController") -> None:
        # by default, Scan Browser on the right and Tables at the bottom
        controller.dock_widgets["Tabular"].raise_()
        controller.dock_widgets["Scan Browser"].raise_()

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
        controller.connect_shapes_layer_events()
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
