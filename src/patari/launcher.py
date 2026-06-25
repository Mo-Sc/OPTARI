import os
import sys
import logging
import faulthandler
from os import _exit as os_exit

faulthandler.enable()

from .utils.logging import configure_logging
from .utils.setup import get_user_dir, configure_napari, load_startup_logo
from patari.config import settings
from patari.controllers.patari_controller import PatariController
# from patari._widget import disclaimer_widget
from . import __version__

logger = logging.getLogger(__name__)

def main() -> None:

    print(f"Starting PATARI... (GUI log level: {settings.general.GUI_LOG_LEVEL}, general log level: {settings.general.LOG_LEVEL})")
    
    configure_logging()
    user_dir = get_user_dir()

    os.environ.setdefault("PATARI_USER_DIR", str(user_dir))
    os.environ.setdefault("PATARI_LOG_LEVEL", settings.general.LOG_LEVEL)
    os.environ.setdefault("PATARI_GUI_LOG_LEVEL", settings.general.GUI_LOG_LEVEL)

    from napari import Viewer, run

    viewer = Viewer(title=f"PATARI v{__version__.split('+')[0]} (INTERNAL USE ONLY)")
    controller = None

    try:
        configure_napari(viewer)
        load_startup_logo(viewer)

        controller = PatariController(viewer, None)

        run()
    finally:
        print("Shutting down cleanly...")
        if controller is not None:
            try:
                controller.shutdown()
            except Exception as e:
                logger.exception("Error during controller shutdown: %s", e)
        # os._exit bypasses Python's GC and atexit, preventing Qt objects from
        # being destroyed in the wrong order after the event loop has stopped.
        os_exit(0)

if __name__ == "__main__":
    main()