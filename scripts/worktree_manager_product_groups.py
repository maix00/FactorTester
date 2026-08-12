"""Compatibility alias for :mod:`server.manager.domain.product_groups`."""

import sys as _sys

from server.manager.domain import product_groups as _implementation

_sys.modules[__name__] = _implementation
