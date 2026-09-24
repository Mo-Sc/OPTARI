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
from .utils.setup import configure_napari, load_startup_logo
from patari.config import settings
from patari.controllers.patari_controller import PatariController

from . import __version__

logger = logging.getLogger(__name__)

def main() -> None:

    log_file = configure_logging()
    logger.info(
        "starting PATARI %s (log level %s, notification level %s), logging to %s",
        __version__, settings.general.LOG_LEVEL, settings.general.GUI_LOG_LEVEL, log_file,
    )

    from napari import Viewer, run

    app = QApplication.instance() or QApplication([])

    viewer = Viewer(title=f"PATARI v{__version__.split('+')[0]}")

    app.setWindowIcon(
        QIcon(str(Path(__file__).resolve().parent / "config" / "logo.png"))
    )
    controller = None
    exit_code = 0

    try:
        configure_napari(viewer)
        load_startup_logo(viewer)

        controller = PatariController(viewer)

        run()

    except Exception:
        # os_exit below ends the process before a re-raised exception could print its traceback
        logger.exception("PATARI stopped on an unhandled error, log: %s", log_file)
        exit_code = 1

    finally:
        if controller is not None:
            try:
                controller.shutdown()
                logger.info("PATARI shutdown complete")
            except Exception:
                logger.exception("error during controller shutdown")
        # os._exit bypasses Pythons GC. Probably not ideal, but avoids a segfault on shutdown due to Qt objects
        # being destroyed in the wrong order after the event loop has stopped.
        os_exit(exit_code)

if __name__ == "__main__":
    main()