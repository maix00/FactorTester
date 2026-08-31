"""Server factor-library CLI module."""

from . import controller as _controller  # noqa: F401  Registers non-catalog commands.
from .factor_library import factor_library

__all__ = ["factor_library"]
