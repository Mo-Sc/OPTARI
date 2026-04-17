import os

from patari.logging_utils import configure_logging
from napari import Viewer, run


def main() -> None:
    os.environ.setdefault("PATARI_LOG_LEVEL", "DEBUG")
    os.environ.setdefault("PATARI_GUI_LOG_LEVEL", "DEBUG")
    configure_logging()
    viewer = Viewer()
    viewer.window.add_plugin_dock_widget("patari", "PATARI Controls")
    run()


if __name__ == "__main__":
    main()
