import os
import logging
from .config import DEFAULT_GUI_LOG_LEVEL, DEFAULT_LOG_LEVEL

logger = logging.getLogger(__name__)


def main() -> None:

    # Force matplotlib to build its font cache first.
    # This should prevent the segmentation fault with Qt on the very first launch when installing using pyapp
    import matplotlib.font_manager
    print("Ensuring font cache is ready (this may take a moment on first launch)")
    matplotlib.font_manager.findfont(matplotlib.font_manager.FontProperties(), fallback_to_default=True)

    os.environ.setdefault("PATARI_LOG_LEVEL", DEFAULT_LOG_LEVEL)
    os.environ.setdefault("PATARI_GUI_LOG_LEVEL", DEFAULT_GUI_LOG_LEVEL)

    print(f"Starting PATARI... (GUI log level: {os.environ['PATARI_GUI_LOG_LEVEL']}, general log level: {os.environ['PATARI_LOG_LEVEL']})")

    from napari import Viewer, run

    viewer = Viewer()
    viewer.window.add_plugin_dock_widget("patari", "PATARI Controls")
    run()


if __name__ == "__main__":
    main()
