"""Compatibility alias for :mod:`server.manager.services.client_state`."""

import sys as _sys

from server.manager.services import client_state as _implementation

_sys.modules[__name__] = _implementation
