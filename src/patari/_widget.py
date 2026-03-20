from napari.viewer import Viewer
from qtpy.QtWidgets import QLabel, QWidget
from imageio.v3 import imread

from .config import STARTUP_LOGO_PATH
from patari.controllers.patari_controller import PatariController


# TODO: export xlsx feature (all vs current wavelength / frame)
# TODO: Unmixed datasets
# TODO: Unmix widget, recon widget
# TODO: ROI Layer should not be deleted
# TODO: refactor the segmentation part. Currently there is still a lot of AI stuff that is not necessary
# add more ROI types, make sure ROI is still somewhat consistent with pipeline implementation
# compare current ROI and segmentation handling to PATATO
# PATATO ithera ROI PR is now merged

# TODO: best frame selection based on SSIM or motion score
# TODO: maybe a measurement tool for distances?
# TODO: check whether raw ithera import also works
# TODO: performance evaluation: FOr example scrub line is currently commented out, but is nice feature, so check whether it is a bottleneck
# TODO: annotation dock should include option to select which feature to use for histo, time analysis, and spectrum (e.g. mean, p90, etc.) (and also for clipping?)
# TODO: Since ROI layer is accidentaly deleted sometimes by user, maybe re-add everytime a new scan is loaded? Or add a button to layer list if possible
# TODO: also we could rename Browse Folder to Open Study or smth
# TODO: explore keyboard shortcuts
# TODO: workaround for old iannotation hdf5 group -> simply load as polygon vertices

# TODO: I think currently scrolling only works if the AnnotationDOck is the limiting factor. But it would be nicer to create some base class that is scrollable and then wrap all the side docks into it

# TODO: maybe include actual timestamp in patato directly?

# TODO: ROI favorites / presets, similar to autoroi. One should be "last", and simply adds the ROI that was last created again
# TODO: is it possible to change the intial text written in the background of the viewer?
# TODO: Background auto save for saved ROI table

# TODO: ithera data loading
# decide on whether hdf5 files should be stored separately or in a folder?
# and when they should be exported (e.g. on save button click, or automatically when a new scan is loaded, or when the plugin is closed?)
# should we check for changes and ask the user when closing?
# TODO: setup theme using FAU colors
# TODO: saved roi table auto save and auto loading (persistent)

# TODO: in patato, check whether napari roi to patato roi conversion should be moved to patari
# TODO: separate features for roi table and saved table


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
