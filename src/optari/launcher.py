import logging
from os import _exit as os_exit
from pathlib import Path

# must import before Qt/napari on Windows (for PyQt6)
# TODO: check if still necessary after switch to PySide6
import jax  # noqa: jax is required by PATATO


from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QApplication

from .utils.logging import configure_logging
from .utils.setup import configure_napari, load_startup_logo
from optari.config import settings
from optari.controllers.optari_controller import OptariController

from . import __version__

logger = logging.getLogger(__name__)


def main() -> None:

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

        run()

    except Exception:
        # os_exit below ends the process before a re-raised exception could print its traceback
        logger.exception(
            "OPTARI stopped on an unhandled error, log: %s", log_file
        )
        exit_code = 1

    finally:
        if controller is not None:
            try:
                controller.shutdown()
                logger.info("OPTARI shutdown complete")
            except Exception:
                logger.exception("error during controller shutdown")
        # os._exit bypasses Pythons GC. Probably not ideal, but avoids a segfault on shutdown due to Qt objects
        # being destroyed in the wrong order after the event loop has stopped.
        os_exit(exit_code)


if __name__ == "__main__":
    main()
