try:
    from ._version import version as __version__
except ImportError:
    __version__ = "unknown"

# Source tag included in every ROI created by OPTARI
OPTARI_SOURCE_TAG = f"OPTARI_v{__version__}"
