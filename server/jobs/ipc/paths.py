"""Stable short paths for Unix sockets on macOS and Linux."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path


def normalized_socket_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if len(str(path).encode()) <= 96:
        return path
    digest = hashlib.sha256(str(path).encode()).hexdigest()[:24]
    return Path(tempfile.gettempdir()) / "factortester-jobs" / f"{digest}.sock"
