"""Compatibility alias for :mod:`server.manager.domain.federation`."""

import sys as _sys

from server.manager.domain import federation as _implementation

_sys.modules[__name__] = _implementation
