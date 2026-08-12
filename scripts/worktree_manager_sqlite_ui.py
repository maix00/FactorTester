"""Compatibility alias for :mod:`server.manager.http.sqlite_ui`."""

import sys as _sys

from server.manager.http import sqlite_ui as _implementation

_sys.modules[__name__] = _implementation
