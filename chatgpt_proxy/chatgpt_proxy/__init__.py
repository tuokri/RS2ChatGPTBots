__version__: str


def _load_version():
    global __version__
    try:
        from ._version import __version__
    except ImportError:
        __version__ = "unknown"


_load_version()

__all__ = [
    "__version__",
    "_load_version",
]
