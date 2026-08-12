"""Compatibility alias for :mod:`server.manager.http.gateway`."""

import sys as _sys

from server.manager.http import gateway as _implementation

_sys.modules[__name__] = _implementation
