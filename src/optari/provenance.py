"""The origin record OPTARI writes into every file it creates (HDF5 scans, ROI tables,
batch reports).
"""

from __future__ import annotations

import datetime as dt

from optari import __version__
from optari.config import settings
from optari.config.config import CONFIG_SCHEMA_VERSION

# increment if the HDF5 file format changes in a way that breaks backward compatibility
OPTARI_FILE_FORMAT_VERSION = 2
OPTARI_SOURCE_URL = "https://github.com/Mo-Sc/OPTARI"
OPTARI_DOCS_URL = "https://mo-sc.github.io/OPTARI/"
OPTARI_PUBLICATION_DOI = "10.48550/arXiv.2610.32468"


def file_origin(**extra) -> dict:
    """origin recorded in every file OPTARI writes."""
    return {
        "tool": "OPTARI",
        "tool_version": __version__,
        "operator": settings.general.OPERATOR,
        "analysis_id": settings.general.ANALYSIS_ID,
        "creation_time": dt.datetime.now(dt.timezone.utc).isoformat(),
        "format_version": OPTARI_FILE_FORMAT_VERSION,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "source_url": OPTARI_SOURCE_URL,
        "documentation_url": OPTARI_DOCS_URL,
        "publication_doi": OPTARI_PUBLICATION_DOI,
        **extra,
    }
