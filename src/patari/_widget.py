from napari.viewer import Viewer
from qtpy.QtWidgets import QLabel, QWidget

from patari._reader import patari_reader_function_all
from patari.controllers.patari_controller import PatariController


def patari_controls(napari_viewer: Viewer | None = None) -> QWidget:
    """Instantiate PATARI UI.

    Returns the Scan Browser widget (folder chooser + scan list). Additional
    docks (Info + ROI Tables) are added by the controller.

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

    if (
        not hasattr(patari_controls, "_controller")
        or patari_controls._controller.viewer is not viewer
    ):
        patari_controls._controller = PatariController(
            viewer,
            None,
            reader=patari_reader_function_all,
        )

    # Expose the scan browser as the main PATARI Controls widget.
    return patari_controls._controller.scan_browser.widget
