#!/usr/bin/env python3
"""Compatibility entry point for the Manager artifact data plane.

Production Manager startup uses ``python -m server.manager.services.artifacts``.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

from server.manager.services import artifacts as _artifacts  # noqa: E402

_sys.modules[__name__] = _artifacts

if __name__ == "__main__":
    raise SystemExit(_artifacts.main())
