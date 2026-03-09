from napari.viewer import Viewer
from qtpy.QtWidgets import QLabel, QWidget

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
# TODO: ROI Layer should not be deleted
# TODO: refactor the segmentation part. Currently there is still a lot of AI stuff that is not necessary
# add more ROI types, make sure ROI is still somewhat consistent with pipeline implementation
# compare current ROI and segmentation handling to PATATO
# PATATO ithera ROI PR is now merged
# TODO: there will be only one US layer, so maybe that can be stored in the controller so it doenst have to be searched every time
# Same for scaling and unit conversion
# TODO: xlsx /csv export in a way that it can be easily viewed in excel (semicolon separated?)
# TODO: best frame selection based on SSIM or motion score
# TODO: iannotation import and export
# TODO: when clicking on pixel, show spectra. Or spectra view of roi like the histogram view
# TODO: maybe a measurement tool for distances?


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
        )

    # Expose the info widget as the main PATARI Controls widget.
    return patari_controls._controller.info.widget
