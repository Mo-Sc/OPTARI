from napari.viewer import Viewer
from qtpy.QtWidgets import QLabel, QWidget
from imageio.v3 import imread

from .config import STARTUP_LOGO_PATH
from patari.controllers.patari_controller import PatariController


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

    viewer = napari_viewer
    if viewer is None:
        try:
            import napari

            viewer = napari.current_viewer()
        except Exception:
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
        print(f"PATARI: failed to load startup logo from {STARTUP_LOGO_PATH}")

    if (
        not hasattr(patari_controls, "_controller")
        or patari_controls._controller.viewer is not viewer
    ):
        patari_controls._controller = PatariController(viewer, None)

    # Expose the info widget as the main PATARI Controls widget.
    return patari_controls._controller.info.widget
