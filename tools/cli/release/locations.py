"""Safe versioned application-support locations."""

from __future__ import annotations

import os
from pathlib import Path
import sys


CLIENT_ROOT_ENV = "TRADERESEARCH_CLIENT_ROOT"
_LEGACY_CLIENT_ROOT_ENV = "FACTORTESTER_CLIENT_ROOT"


def default_client_root() -> Path:
    configured = os.environ.get(CLIENT_ROOT_ENV) or os.environ.get(
        _LEGACY_CLIENT_ROOT_ENV
    )
    if configured:
        return validate_client_root(Path(configured).expanduser())
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "TradeResearch"
        legacy_root = Path.home() / "Library" / "Application Support" / "FactorTester"
    else:
        root = Path.home() / ".local" / "share" / "traderesearch"
        legacy_root = Path.home() / ".local" / "share" / "factortester"
    if not root.exists() and legacy_root.exists():
        root = legacy_root
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
