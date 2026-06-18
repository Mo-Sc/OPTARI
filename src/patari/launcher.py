import os
import logging
from .utils.setup import get_user_dir
from .utils.logging import configure_logging
from .utils.setup import configure_napari_preferences
logger = logging.getLogger(__name__)

from patari.config import settings


def main() -> None:

    # Force matplotlib to build its font cache first.
    # This should prevent the segmentation fault with Qt on the very first launch when installing using pyapp
    import matplotlib.font_manager
    print("Ensuring font cache is ready (this may take a moment on first launch)")
    matplotlib.font_manager.findfont(matplotlib.font_manager.FontProperties(), fallback_to_default=True)

    
    print(f"Starting PATARI... (GUI log level: {settings.general.GUI_LOG_LEVEL}, general log level: {settings.general.LOG_LEVEL})")
    configure_logging()

    # Set up user directory
    user_dir = get_user_dir()

    os.environ.setdefault("PATARI_USER_DIR", str(user_dir))
    os.environ.setdefault("PATARI_LOG_LEVEL", settings.general.LOG_LEVEL)
    os.environ.setdefault("PATARI_GUI_LOG_LEVEL", settings.general.GUI_LOG_LEVEL)

    

    from napari import Viewer, run

    configure_napari_preferences()

    # once custom logo is ready
    # from qtpy.QtGui import QIcon 
    # logo_path = os.path.join(os.path.dirname(__file__), "data", "patari_logo.png")
    # if os.path.exists(logo_path):
    #     viewer.window._qt_window.setWindowIcon(QIcon(logo_path))

    viewer = Viewer(title="PATARI (Clinical PA Analysis)") 

    viewer.window.add_plugin_dock_widget("patari", "PATARI Controls")
    run()


if __name__ == "__main__":
    main()
