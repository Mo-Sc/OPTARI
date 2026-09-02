from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path

from patari.config import settings


class _NapariNotificationHandler(logging.Handler):
    """Forward log messages to napari notifications when available."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from napari.utils.notifications import (
                show_error,
                show_info,
                show_warning,
            )

            message = self.format(record)
            if record.levelno >= logging.ERROR:
                show_error(message)
            elif record.levelno >= logging.WARNING:
                show_warning(message)
            else:
                show_info(message)
        except Exception:
            # Never let GUI notification failures break application logging.
            pass


def configure_logging() -> None:
    """Configure PATARI logging from environment.

    Uses ``PATARI_LOG_LEVEL`` (default ``INFO``) for the ``patari`` logger
    namespace only, and keep the root logger at ``WARNING`` to avoid
    debug output from other packages (e.g. napari/matplotlib).
    """
    level_name = os.getenv("PATARI_LOG_LEVEL", settings.general.LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.WARNING)

    patari_logger = logging.getLogger("patari")
    patari_logger.setLevel(level)
    patari_logger.propagate = False

    formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")

    if not any(
        getattr(h, "name", "") == "patari_stream"
        for h in patari_logger.handlers
    ):
        stream_handler = logging.StreamHandler()
        stream_handler.name = "patari_stream"
        stream_handler.setFormatter(formatter)
        patari_logger.addHandler(stream_handler)

    gui_level_name = os.getenv(
        "PATARI_GUI_LOG_LEVEL", settings.general.GUI_LOG_LEVEL
    ).upper()
    gui_level = getattr(logging, gui_level_name, logging.WARNING)

    if not any(
        getattr(h, "name", "") == "patari_napari_notifications"
        for h in patari_logger.handlers
    ):
        gui_handler = _NapariNotificationHandler(level=gui_level)
        gui_handler.name = "patari_napari_notifications"
        gui_handler.setFormatter(formatter)
        patari_logger.addHandler(gui_handler)


@contextmanager
def run_log_file(destination: Path, level: int = logging.INFO):
    """Also write the ``patari`` log to *destination* for the duration of the block.

    Used by long unattended runs, where the console log is not where the user will
    look afterwards. The handler is always removed again, so a failed run cannot
    leave the file handle attached for the rest of the session.
    """
    handler = logging.FileHandler(destination, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    )
    patari_logger = logging.getLogger("patari")
    patari_logger.addHandler(handler)
    try:
        yield destination
    finally:
        patari_logger.removeHandler(handler)
        handler.close()
