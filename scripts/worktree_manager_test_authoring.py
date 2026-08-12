"""Compatibility alias for :mod:`server.manager.services.test_authoring`."""

import sys as _sys

from server.manager.services import test_authoring as _implementation

_sys.modules[__name__] = _implementation
