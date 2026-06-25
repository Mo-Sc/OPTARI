import os
import sys
import logging
import faulthandler

faulthandler.enable()

from .utils.setup import get_user_dir
from .utils.logging import configure_logging
from .utils.setup import configure_napari
from patari.config import settings

# Import your controller directly!
from patari.controllers.patari_controller import PatariController
# from patari._widget import disclaimer_widget

logger = logging.getLogger(__name__)

def main() -> None:
    print(f"Starting PATARI... (GUI log level: {settings.general.GUI_LOG_LEVEL}, general log level: {settings.general.LOG_LEVEL})")
    configure_logging()

    user_dir = get_user_dir()
    os.environ.setdefault("PATARI_USER_DIR", str(user_dir))
    os.environ.setdefault("PATARI_LOG_LEVEL", settings.general.LOG_LEVEL)
    os.environ.setdefault("PATARI_GUI_LOG_LEVEL", settings.general.GUI_LOG_LEVEL)

    from napari import Viewer, run
    from qtpy.QtWidgets import QApplication

    viewer = Viewer(title="PATARI (Clinical PA Analysis)") 
    configure_napari(viewer)
    
    QApplication.processEvents()

    # --- THE ARCHITECTURAL FIX ---
    # 1. Instantiate your controller directly (bypassing the plugin engine inception).
    # This safely adds and tabifies all 7 docks without interrupting Napari's internal state.
    controller = PatariController(viewer, None)
    
    # 2. If you still want the disclaimer widget, add it cleanly as a standard dock widget!
    # disclaimer = disclaimer_widget()
    # viewer.window.add_dock_widget(disclaimer, name="PATARI Controls", area="left")

    # Hook for clean teardown (from our previous fix)
    from qtpy.QtCore import QCoreApplication

    def prepare_shutdown():
        print("Disconnecting plugin events for clean shutdown...")
        try:
            viewer.dims.events.disconnect()
            viewer.layers.events.disconnect()
        except Exception as e:
            logger.error(f"Shutdown error: {e}")

    # Use the global application signal instead of the window signal
    QCoreApplication.instance().aboutToQuit.connect(prepare_shutdown)

    run()

    print("Shutting down cleanly...")
    sys.exit(0)

if __name__ == "__main__":
    main()