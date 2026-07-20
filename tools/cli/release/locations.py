"""Safe versioned application-support locations."""

from __future__ import annotations

import os
from pathlib import Path
import sys


CLIENT_ROOT_ENV = "FACTORTESTER_CLIENT_ROOT"


def default_client_root() -> Path:
    configured = os.environ.get(CLIENT_ROOT_ENV)
    if configured:
        return validate_client_root(Path(configured).expanduser())
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "FactorTester"
    else:
        root = Path.home() / ".local" / "share" / "factortester"
    return validate_client_root(root)


def validate_client_root(root: Path) -> Path:
    resolved = root.expanduser().resolve()
    home = Path.home().resolve()
    forbidden = {
        Path("/").resolve(),
        home,
        (home / "Documents").resolve(),
    }
    if resolved in forbidden:
        raise ValueError(f"unsafe client release root: {resolved}")
    if len(resolved.parts) < 3:
        raise ValueError(f"unsafe client release root: {resolved}")
    return resolved
