"""The dock table and the wiring of viewer and dock signals.

``DOCKS`` lists the docks several controllers share. A dock only one controller uses is
declared on that controller (``TaskControllerBase.DOCK``) and added after these.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from qtpy.QtCore import QTimer

from optari.widgets.annotation_dock import create_annotation_dock
from optari.widgets.histogram_dock import create_histogram_dock
from optari.widgets.info_dock import create_info_dock
from optari.widgets.motion_dock import create_motion_dock
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

# OPTARI's docks as (attribute on OptariController, factory, title, area, tabify). The order
# is the order of OPTARI > Docks and of the Settings dock list.a tabified dock joins the
# previous one in its area. A new dock is one row here plus its typed attribute.
DOCKS = (
    (
        "scan_browser_dock",
        create_scan_browser_dock,
        "Scan Browser",
        "right",
        False,
    ),
    ("info_dock", create_info_dock, "Active Slice Info", "left", False),
    ("roi_dock", create_roi_dock, "Tabular", "bottom", False),
    (
        "time_analysis_dock",
        create_time_analysis_dock,
        "Temporal",
        "bottom",
        True,
    ),
    ("motion_dock", create_motion_dock, "Frame QC", "bottom", True),
    ("histogram_dock", create_histogram_dock, "Histogram", "bottom", True),
    ("spectrum_dock", create_spectrum_dock, "Spectral", "bottom", True),
    ("annotation_dock", create_annotation_dock, "Annotation", "right", True),
    (
        "segmentation_dock",
        create_segmentation_dock,
        "Segmentation",
        "right",
        True,
    ),
    ("unmixing_dock", create_unmixing_dock, "Unmixing", "right", True),
    (
        "reconstruction_dock",
        create_reconstruction_dock,
        "Reconstruction",
        "right",
        True,
    ),
)


class UiManager:
    """Build and wire dock widgets for a single OPTARI controller instance."""

    def __init__(self, controller: OptariController):
        self.controller = controller

    # ============ dock setup ============
    def setup_docks(self) -> None:
        """Create OPTARI's docks and register them, with napari's own, in
        ``controller.dock_widgets``. The order there is the order of OPTARI ▸ Docks
        and of the Settings dock list; tabified docks join the previous one in their area.
        """
        controller = self.controller
        own_docks = tuple(c.DOCK for c in controller.controllers if c.DOCK)
        for attribute, create_dock, title, area, tabify in DOCKS + own_docks:
            dock = create_dock()
            controller.dock_widgets[title] = (
                controller.viewer.window.add_dock_widget(
                    dock.widget, name=title, area=area, tabify=tabify
                )
            )
            setattr(controller, attribute, dock)
        # The info dock floats by default instead of sitting in the left area.
        controller.dock_widgets["Active Slice Info"].setFloating(True)

        # napari's own docks, so they can be toggled and defaulted like OPTARI's.
        # private _qt_viewer (public qt_viewer is deprecated), still present in napari 0.9.1
        qt_viewer = controller.viewer.window._qt_viewer
        controller.dock_widgets["Layer Controls"] = qt_viewer.dockLayerControls
        controller.dock_widgets["Layer List"] = qt_viewer.dockLayerList

        # Select default docks after the event loop has started
        QTimer.singleShot(0, self._select_default_docks)

        logger.info("Dock widgets created and added to the viewer window.")

    # ============ dock layout ============
    def _select_default_docks(self) -> None:
        # by default, Scan Browser on the right and Tables at the bottom
        self.controller.dock_widgets["Tabular"].raise_()
        self.controller.dock_widgets["Scan Browser"].raise_()

    def _install_shutdown_hook(self) -> None:
        """Run controller teardown from the main window's close event."""
        controller = self.controller
        window = controller.viewer.window._qt_window
        napari_close_event = window.closeEvent

        def close_event(event) -> None:
            napari_close_event(event)
            # napari ignores the event when the user cancels its confirm-close dialog.
            if event.isAccepted():
                controller.shutdown()

        window.closeEvent = close_event

    def connect_events(self) -> None:
        controller = self.controller
        # -------- viewer core events --------
        controller.connect_shapes_layer_events()
        controller.viewer.dims.events.point.connect(controller.on_dims_changed)
        controller.viewer.layers.selection.events.changed.connect(
            controller.on_selection_changed
        )
        controller.info_dock.metadata_button.clicked.connect(
            controller.on_metadata_clicked
        )

        self._install_shutdown_hook()
        # TODO: should reordering / adding layers trigger anything?
        # controller.viewer.layers.events.reordered.connect(controller.on_layers_changed)
        # controller.viewer.layers.events.inserted.connect(controller.on_layers_changed)
        controller.viewer.layers.events.removed.connect(
            controller.on_layer_removed
        )

        # -------- dock signal wiring in controllers --------
        for task_controller in controller.controllers:
            task_controller.bind_events()
