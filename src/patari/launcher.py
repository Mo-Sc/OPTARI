import os
import sys
import logging
import faulthandler

# ENABLE FAULT HANDLER IMMEDIATELY
faulthandler.enable()

from .utils.setup import get_user_dir
from .utils.logging import configure_logging
from .utils.setup import configure_napari
from patari.config import settings

logger = logging.getLogger(__name__)

def main() -> None:
    print(f"Starting PATARI... (GUI log level: {settings.general.GUI_LOG_LEVEL}, general log level: {settings.general.LOG_LEVEL})")
    configure_logging()

    # Set up user directory
    user_dir = get_user_dir()

    os.environ.setdefault("PATARI_USER_DIR", str(user_dir))
    os.environ.setdefault("PATARI_LOG_LEVEL", settings.general.LOG_LEVEL)
    os.environ.setdefault("PATARI_GUI_LOG_LEVEL", settings.general.GUI_LOG_LEVEL)

    from napari import Viewer, run
    from qtpy.QtWidgets import QApplication

    viewer = Viewer(title="PATARI (Clinical PA Analysis)") 

    configure_napari(viewer)

    # Force Qt to finish rendering (still good practice to keep this here!)
    QApplication.processEvents()

    viewer.window.add_plugin_dock_widget("patari", "PATARI Controls")
    
    # This blocks until the user closes the window
    run()

    # --- CLEAN TEARDOWN BLOCK ---
    print("Shutting down cleanly...")
    
    # 1. Force Napari to cleanly close its viewer and release Qt bindings
    try:
        viewer.close()
    except Exception:
        pass
        
    # 2. Hard exit the process to prevent Python's garbage collector from double-freeing Qt C++ objects
    sys.exit(0)

if __name__ == "__main__":
    main()