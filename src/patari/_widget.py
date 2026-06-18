import logging
from pathlib import Path

from napari.viewer import Viewer
from qtpy.QtWidgets import QWidget, QLabel, QVBoxLayout
from imageio.v3 import imread

from patari.controllers.patari_controller import PatariController

from . import __version__


logger = logging.getLogger(__name__)


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

    if napari_viewer is None:
        import napari

        napari_viewer = napari.current_viewer()

    startup_logo_path = Path(__file__).resolve().parent / "data/startup.png"

    if startup_logo_path.exists():
        napari_viewer.add_image(
            imread(startup_logo_path),
            name="Welcome to PATARI!",
            metadata={
                "type": "startup_logo",
                "filepath": str(startup_logo_path),
            },
        )
    else:
        logger.warning(f"Startup logo not found: {startup_logo_path}")

    if not hasattr(patari_controls, "_controller"):
        patari_controls._controller = PatariController(napari_viewer, None)

    # Return a simple widget to satisfy npe2 return requirement
    return disclaimer_widget()
