"""Compatibility alias for :mod:`server.manager.web.assets`."""

import sys as _sys

from server.manager.web import assets as _implementation

_sys.modules[__name__] = _implementation
