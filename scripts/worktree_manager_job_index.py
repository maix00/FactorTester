"""Compatibility alias for :mod:`server.manager.storage.job_index`."""

import sys as _sys

from server.manager.storage import job_index as _implementation

_sys.modules[__name__] = _implementation
