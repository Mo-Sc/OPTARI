try:
    from ._version import version as __version__
except ImportError:
    __version__ = "unknown"

# Source tag included in every ROI created by PATARI
PATARI_SOURCE_TAG = f"PATARI_v{__version__}"
