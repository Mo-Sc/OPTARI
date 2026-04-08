from __future__ import annotations

import logging
import os


def configure_logging() -> None:
    """Configure PATARI logging from environment.

    Uses ``PATARI_LOG_LEVEL`` (default ``INFO``) for the ``patari`` logger
    namespace only, and keep the root logger at ``WARNING`` to avoid
    debug output from other packages (e.g. napari/matplotlib).
    """
    level_name = os.getenv("PATARI_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.WARNING)

    patari_logger = logging.getLogger("patari")
    patari_logger.setLevel(level)
    patari_logger.propagate = False

    if not patari_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(levelname)s:%(name)s:%(message)s")
        )
        patari_logger.addHandler(handler)
