"""Typed foundation for reusable FastAPI infrastructure."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("fastapi-infra")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["__version__"]
