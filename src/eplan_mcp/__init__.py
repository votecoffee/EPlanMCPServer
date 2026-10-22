"""EPLAN MCP Server: local drawing intelligence."""

from .release_version import DISPLAY_VERSION as __version__
from .release_version import PACKAGE_VERSION as __package_version__

__all__ = ["__version__", "__package_version__", "EXTRACTION_VERSION"]
EXTRACTION_VERSION = "1"
