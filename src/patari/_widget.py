from pathlib import Path

from magicgui import magic_factory
from napari.viewer import Viewer

from patari._reader import patari_reader_function_all
from patari.controllers.patari_controller import PatariController


@magic_factory(auto_call=True, layout="vertical")
def patari_controls(viewer: Viewer, path: Path):
    """Instantiate PATARI UI.

    Adds multiple dock widgets (Info + ROI Tables) and wires napari events.
    The controller is memoized per (viewer, path).
    """

    if (
        not hasattr(patari_controls, "_controller")
        or patari_controls._controller.viewer is not viewer
        or patari_controls._controller.path != Path(path)
    ):
        patari_controls._controller = PatariController(
            viewer,
            path,
            reader=patari_reader_function_all,
        )

    return None
