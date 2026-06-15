import logging

from napari.viewer import Viewer
from qtpy.QtWidgets import QWidget, QLabel, QVBoxLayout
from imageio.v3 import imread

from .config import STARTUP_LOGO_PATH
from .logging_utils import configure_logging
from patari.controllers.patari_controller import PatariController

logger = logging.getLogger(__name__)


from . import __version__



def configure_napari_preferences() -> None:
    """configure PATRI specific napari settings (playback fps, save window state, grid stride)."""
    try:
        import napari
        settings = napari.settings.get_settings()
        
        settings.application.playback_fps = 5
        settings.application.save_window_state = True
        settings.application.grid_stride = -2
        logger.info("PATARI: Clinical environment preferences applied successfully.")
    except Exception as e:
        logger.warning(f"Could not apply Napari preferences: {e}")

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
    configure_napari_preferences()

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
