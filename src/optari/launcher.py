"""Entry point of the ``optari`` command: logging, the napari window, the controller."""

import logging
from os import _exit as os_exit
from pathlib import Path

# must import before Qt/napari on Windows (for PyQt6)
# TODO: check if still necessary after switch to PySide6
import jax  # noqa: F401  (PATATO needs it imported before Qt)
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QApplication

from optari import __version__
from optari.config import settings
from optari.controllers.optari_controller import OptariController
from optari.utils.logging import configure_logging
from optari.utils.setup import configure_napari, load_startup_logo
from optari.widgets.settings_dialog import identification_dialog

logger = logging.getLogger(__name__)


def main() -> None:
    """Run OPTARI until its window closes, then end the process with ``os._exit``."""
    log_file = configure_logging()
    logger.info(
        "starting OPTARI %s (log level %s, notification level %s), logging to %s",
        __version__,
        settings.general.LOG_LEVEL,
        settings.general.GUI_LOG_LEVEL,
        log_file,
    )

    from napari import Viewer, run

    app = QApplication.instance() or QApplication([])

    viewer = Viewer(title=f"OPTARI v{__version__.split('+')[0]}")

    app.setWindowIcon(
        QIcon(str(Path(__file__).resolve().parent / "config" / "logo.png"))
    )
    controller = None
    exit_code = 0

    try:
        configure_napari(viewer)
        load_startup_logo(viewer)

        controller = OptariController(viewer)
        identification_dialog(viewer.window._qt_window)

        run()

    except Exception:
        # os_exit below ends the process before a re-raised exception could print its
        # traceback
        logger.exception("OPTARI stopped on an unhandled error, log: %s", log_file)
        exit_code = 1

    finally:
        if controller is not None:
            try:
                controller.shutdown()
                logger.info("OPTARI shutdown complete")
            except Exception:
                logger.exception("error during controller shutdown")
        # os._exit bypasses Pythons GC. Probably not ideal, but avoids a segfault on
        # shutdown due to Qt objects being destroyed in the wrong order after the event
        # loop has stopped.
        os_exit(exit_code)


if __name__ == "__main__":
    main()
