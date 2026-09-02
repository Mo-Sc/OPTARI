import os
import logging
from os import _exit as os_exit
from pathlib import Path

import jax  # noqa: jax is required by PATATO
            # must import before PyQt6/napari on Windows: importing
            # PyQt6 first causes jaxlib's native extension (_jax.pyd) to fail with
            # "DLL load failed ... initialization routine failed".
            # Cause is unclear, but importing jax first is workaround.
            # Do not reorder without re-testing on Windows.


from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from .utils.logging import configure_logging
from .utils.setup import get_user_dir, configure_napari, load_startup_logo
from patari.config import settings
from patari.controllers.patari_controller import PatariController

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

    app = QApplication.instance() or QApplication([])

    # viewer = Viewer(title=f"PATARI v{__version__.split('+')[0]} (INTERNAL USE ONLY)")
    viewer = Viewer(title=f"PATARI v{__version__.split('+')[0]}")

    app.setWindowIcon(
        QIcon(str(Path(__file__).resolve().parent / "config" / "logo.png"))
    )
    controller = None

    try:
        configure_napari(viewer)
        load_startup_logo(viewer)

        controller = PatariController(viewer)

        run()

    finally:
        if controller is not None:
            try:
                controller.shutdown()
                logger.info("PATARI shutdown complete.")
            except Exception as e:
                logger.exception("Error during controller shutdown: %s", e)
        # os._exit bypasses Pythons GC. Probably not ideal, but avoids a segfault on shutdown due to Qt objects. TODO
        # being destroyed in the wrong order after the event loop has stopped.
        os_exit(0)

if __name__ == "__main__":
    main()