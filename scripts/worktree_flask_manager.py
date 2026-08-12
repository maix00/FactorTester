#!/usr/bin/env python3
"""Compatibility entry point for the relocated Manager server.

New deployments must use ``python -m server.manager.app``.  The module alias
keeps existing imports, test seams, and older launch-agent configurations
working while the remaining Manager domains are split into ``server/``.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

from server.manager import runtime as _runtime  # noqa: E402

# Return the real runtime module to importers so monkeypatches and historical
# ``scripts.worktree_flask_manager`` references continue to target the same
# classes and globals used by the new app bootstrap.
_sys.modules[__name__] = _runtime

if __name__ == "__main__":
    raise SystemExit(_runtime.main())
