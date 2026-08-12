"""Compatibility alias for :mod:`server.manager.storage.preferences`."""

import sys as _sys

from server.manager.storage import preferences as _implementation

_sys.modules[__name__] = _implementation
