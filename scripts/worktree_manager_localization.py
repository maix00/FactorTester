"""Compatibility alias for :mod:`server.manager.http.localization`."""

import sys as _sys

from server.manager.http import localization as _implementation

_sys.modules[__name__] = _implementation
