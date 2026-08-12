"""Compatibility alias for :mod:`server.manager.storage.sqlite`."""

import sys as _sys

from server.manager.storage import sqlite as _implementation

_sys.modules[__name__] = _implementation
