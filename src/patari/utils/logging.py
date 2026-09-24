from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from napari.utils.notifications import (
    ErrorNotification,
    notification_manager,
    show_error,
    show_info,
    show_warning,
)

from patari.config import settings
from patari.utils.setup import get_user_logs_dir

# one file per session (e.g. if two PATARI instances run side by side)
KEPT_SESSION_LOGS = 20
FILE_FORMAT = "%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"


class _NapariNotificationHandler(logging.Handler):
    """Show patari log records as napari notifications, with the traceback left to the log file."""

    def __init__(self, level: int | str, log_file: Path) -> None:
        super().__init__(level)
        self.log_file = log_file

    def emit(self, record: logging.LogRecord) -> None:
        # notifications create Qt widgets, which only the main thread may do; worker records
        # still reach the console and the log file
        if threading.current_thread() is not threading.main_thread():
            return
        try:
            message = record.getMessage()
            if record.exc_info:
                message += f"\nDetails in {self.log_file}"
            if record.levelno >= logging.ERROR:
                show_error(message)
            elif record.levelno >= logging.WARNING:
                show_warning(message)
            else:
                show_info(message)
        except Exception:
            self.handleError(record)


def _new_session_log_file() -> Path:
    logs_dir = get_user_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    # timestamped names sort chronologically; keep room for the file created below
    for old_log in sorted(logs_dir.glob("patari_*.log"))[: -(KEPT_SESSION_LOGS - 1)]:
        old_log.unlink()
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return logs_dir / f"patari_{timestamp}_{os.getpid()}.log"


def _log_napari_error(notification) -> None:
    """Exceptions raised in napari event callbacks only reach napari's popup otherwise."""
    if isinstance(notification, ErrorNotification):
        exception = notification.exception
        logging.getLogger("napari").error(
            "uncaught exception", exc_info=(type(exception), exception, exception.__traceback__)
        )


def configure_logging() -> Path:
    """Configure console, session log file and napari notifications; return the log file.

    The ``patari`` logger runs at ``PATARI_LOG_LEVEL`` (default: config ``LOG_LEVEL``) and
    propagates to the root handlers, while other packages (napari, PATATO, ...) only log
    warnings and above. ``patari`` records at ``PATARI_GUI_LOG_LEVEL`` (default: config
    ``GUI_LOG_LEVEL``) and above also show up as napari notifications.
    """
    log_file = _new_session_log_file()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    session_file = logging.FileHandler(log_file, encoding="utf-8")
    session_file.setFormatter(logging.Formatter(FILE_FORMAT))

    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(console)
    root.addHandler(session_file)

    # setLevel raises on an unknown level name, which catches typos in config.json
    patari_logger = logging.getLogger("patari")
    patari_logger.setLevel(os.getenv("PATARI_LOG_LEVEL", settings.general.LOG_LEVEL).upper())
    gui_level = os.getenv("PATARI_GUI_LOG_LEVEL", settings.general.GUI_LOG_LEVEL).upper()
    patari_logger.addHandler(_NapariNotificationHandler(gui_level, log_file))

    notification_manager.notification_ready.connect(_log_napari_error)
    return log_file


@contextmanager
def run_log_file(destination: Path, level: int = logging.INFO):
    """Also write the ``patari`` log to *destination* for the duration of the block.

    Used by long unattended runs, where the console log is not where the user will
    look afterwards. The handler is always removed again, so a failed run cannot
    leave the file handle attached for the rest of the session.
    """
    handler = logging.FileHandler(destination, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(FILE_FORMAT))
    patari_logger = logging.getLogger("patari")
    patari_logger.addHandler(handler)
    try:
        yield destination
    finally:
        patari_logger.removeHandler(handler)
        handler.close()
