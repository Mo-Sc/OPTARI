import os

from .config import DEFAULT_GUI_LOG_LEVEL, DEFAULT_LOG_LEVEL


def main() -> None:
    from napari import Viewer, run

    os.environ.setdefault("PATARI_LOG_LEVEL", DEFAULT_LOG_LEVEL)
    os.environ.setdefault("PATARI_GUI_LOG_LEVEL", DEFAULT_GUI_LOG_LEVEL)

    viewer = Viewer()
    viewer.window.add_plugin_dock_widget("patari", "PATARI Controls")
    run()


if __name__ == "__main__":
    main()
