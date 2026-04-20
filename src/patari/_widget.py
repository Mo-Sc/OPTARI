import logging

from napari.viewer import Viewer
from qtpy.QtWidgets import QWidget, QLabel, QVBoxLayout
from imageio.v3 import imread

from .config import STARTUP_LOGO_PATH
from .logging_utils import configure_logging
from patari.controllers.patari_controller import PatariController

logger = logging.getLogger(__name__)


from . import __version__


def disclaimer_widget() -> QWidget:
    """simple disclaimer widget."""
    disclaimer = QWidget()
    layout = QVBoxLayout(disclaimer)

    version = QLabel(f"PATARI v{__version__.split('+')[0]}")
    # upper_label.setStyleSheet("font-weight: bold; font-size: 14px;")
    layout.addWidget(version)

    warn = QLabel("INTERNAL USE ONLY")
    warn.setStyleSheet("color: red;")
    layout.addWidget(warn)
    return disclaimer


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
        patari_controls._controller = PatariController(napari_viewer, None)

    # Return a simple widget to satisfy npe2's return requirement
    return disclaimer_widget()
