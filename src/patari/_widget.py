import logging

from napari.viewer import Viewer
from qtpy.QtWidgets import QLabel, QWidget
from imageio.v3 import imread

from .config import STARTUP_LOGO_PATH
from .logging_utils import configure_logging
from patari.controllers.patari_controller import PatariController


logger = logging.getLogger(__name__)


def patari_controls(napari_viewer: Viewer | None = None) -> QWidget:
    """Instantiate PATARI UI.

    Returns the Info widget as the plugin's main widget. Other docks are added by the controller.

    Is a bit hacky, but this way it handles two startup paths:
        - Plugin menu path: napari usually injects the active viewer via
            ``napari_viewer``.
        - Script path: the widget may be created without an injected
            viewer, so we fall back to ``napari.current_viewer()``.

        This keeps PATARI initialization robust for both plugin-menu startup and
        script-based startup.
    """

    configure_logging()

    viewer = napari_viewer
    if viewer is None:
        try:
            import napari

            viewer = napari.current_viewer()
        except Exception:
            logger.debug(
                "failed to resolve current napari viewer",
                exc_info=True,
            )
            viewer = None

    if viewer is None:
        return QLabel("PATARI: no active napari viewer")

    try:
        viewer.add_image(
            imread(STARTUP_LOGO_PATH),
            name="Welcome to PATARI!",
            metadata={
                "type": "startup_logo",
                "filepath": str(STARTUP_LOGO_PATH),
            },
        )
    except Exception:
        logger.warning(
            "failed to load startup logo from %s", STARTUP_LOGO_PATH
        )

    if (
        not hasattr(patari_controls, "_controller")
        or patari_controls._controller.viewer is not viewer
    ):
        patari_controls._controller = PatariController(viewer, None)

    # Expose the info widget as the main PATARI Controls widget.
    return patari_controls._controller.info.widget
