"""Compatibility alias for :mod:`server.manager.domain.capabilities`."""

import sys as _sys

from server.manager.domain import capabilities as _implementation

_sys.modules[__name__] = _implementation
