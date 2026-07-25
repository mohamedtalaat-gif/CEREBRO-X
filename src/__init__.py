"""CEREBRO-X — src package."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Re-export the centralized version constants so that any module that does
# `from src import __version__` (or `from src import PROJECT_TITLE`) gets the
# canonical values. This is the single source of truth for the project name
# and version, used in every report, banner, and log line.
try:
    from _version import (  # noqa: F401
        AUTHOR,
        AUTHOR_EMAIL,
        AUTHOR_FULL,
        CITATION,
        COPYRIGHT,
        PROJECT_NAME,
        PROJECT_TAGLINE,
        PROJECT_TITLE,
        PROJECT_VERSION,
        __author__,
        __email__,
        __title__,
        __version__,
        banner,
        short_banner,
    )
except ImportError:
    # Fallback (defensive): if _version.py is unreachable, hard-code the
    # current canonical values so downstream code never crashes.
    PROJECT_NAME    = "CEREBRO-X"
    PROJECT_VERSION = "22.1"
    PROJECT_TITLE   = "CEREBRO-X"
    __title__       = PROJECT_TITLE
    __version__     = PROJECT_VERSION
