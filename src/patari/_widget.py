from napari.viewer import Viewer
from qtpy.QtWidgets import QLabel, QWidget
from imageio.v3 import imread

from .config import STARTUP_LOGO_PATH
from patari.controllers.patari_controller import PatariController

# TODO: workaround for old iannotation hdf5 group -> simply load as polygon vertices
# TODO: maybe include actual timestamp in patato directly?
# TODO: setup theme using FAU colors

# TODO: in patato, check whether napari roi to patato roi conversion should be moved to patari
# TODO: finish up full export hdf5, as suggested in chat
# TODO: currently auto ROI placement only works for ellipse ROIs --- decide on whether to support other shapes, and how (e.g. bounding box for rectangle, convex hull for polygon, etc.)
# decide on whether hdf5 files should be stored separately or in a folder?
# and when they should be exported (e.g. on save button click, or automatically when a new scan is loaded, or when the plugin is closed?)
# should we check for changes and ask the user when closing?


def patari_controls(napari_viewer: Viewer | None = None) -> QWidget:
    """Instantiate PATARI UI.

    Returns the Info widget as the plugin's main widget. Other docks are added by the controller.

    Note: napari injects the active viewer into plugin widgets using the
    parameter name `napari_viewer`.
    """

    viewer = napari_viewer
    if viewer is None:
        # Some napari call paths (e.g. add_plugin_dock_widget) call widget
        # factories with no args. Try to resolve the active viewer.
        try:
            import napari

            viewer = napari.current_viewer()
        except Exception:
            viewer = None

    if viewer is None:
        return QLabel("PATARI: no active napari viewer")

    # make sure relative path loading works
    viewer.add_image(
        imread(STARTUP_LOGO_PATH),
        name="Welcome to PATARI!",
        metadata={"type": "startup_logo", "filepath": str(STARTUP_LOGO_PATH)},
    )

    if (
        not hasattr(patari_controls, "_controller")
        or patari_controls._controller.viewer is not viewer
    ):
        patari_controls._controller = PatariController(
            viewer,
            None,
        )

    # Expose the info widget as the main PATARI Controls widget.
    return patari_controls._controller.info.widget
