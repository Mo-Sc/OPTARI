from napari.viewer import Viewer
from qtpy.QtWidgets import QLabel, QWidget

from patari._reader import patari_reader_function_all
from patari.controllers.patari_controller import PatariController


# TODO: timestamp in time graph doesnt fit the timestamp in info widget (at least peaks)
# TODO: problem is that timestamps are always taken from the first wavelength, so there they match
# also would it make sense to be able to toggle between time and frame as x-axis in time graph?
# also refresh button still doesnt rescale the time graph properly

# TODO: reset button in controls: deletes all ROIs, etc
# TODO: Export hdf5 button to patari_controls. add functionality
# TODO: export xlsx feature (all vs current wavelength / frame)
# TODO: Unmixed datasets
# TODO: Unmix widget?
# TODO: width of controls should not depend on length of folder path


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

    if (
        not hasattr(patari_controls, "_controller")
        or patari_controls._controller.viewer is not viewer
    ):
        patari_controls._controller = PatariController(
            viewer,
            None,
            reader=patari_reader_function_all,
        )

    # Expose the info widget as the main PATARI Controls widget.
    return patari_controls._controller.info.widget
