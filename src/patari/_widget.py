import logging

from napari.viewer import Viewer
from qtpy.QtCore import QTimer, Qt
from qtpy.QtWidgets import QWidget
from imageio.v3 import imread

from .config import STARTUP_LOGO_PATH
from .logging_utils import configure_logging
from patari.controllers.patari_controller import PatariController

logger = logging.getLogger(__name__)


def patari_controls(napari_viewer: Viewer | None = None) -> QWidget:
    """Instantiate PATARI UI and return the primary info widget."""
    configure_logging()

    if napari_viewer is None:
        import napari

        napari_viewer = napari.current_viewer()

    if STARTUP_LOGO_PATH.exists():
        napari_viewer.add_image(
            imread(STARTUP_LOGO_PATH),
            name="Welcome to PATARI!",
            metadata={
                "type": "startup_logo",
                "filepath": str(STARTUP_LOGO_PATH),
            },
        )
    else:
        logger.warning(f"Startup logo not found: {STARTUP_LOGO_PATH}")

    if not hasattr(patari_controls, "_controller"):
        print("Initializing PATARI controller...")
        patari_controls._controller = PatariController(napari_viewer, None)

    return patari_controls._controller.info.widget
    # widget = patari_controls._controller.info.widget

    # # Minimal hack to force left docking after napari wraps the widget
    # def _dock_left():
    #     dock = widget.parentWidget()
    #     while dock and not dock.inherits("QDockWidget"):
    #         dock = dock.parentWidget()
    #     if dock and hasattr(napari_viewer.window, "_qt_window"):
    #         napari_viewer.window._qt_window.addDockWidget(
    #             Qt.LeftDockWidgetArea, dock
    #         )

    # QTimer.singleShot(0, _dock_left)
    # return widget
