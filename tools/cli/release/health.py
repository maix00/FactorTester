"""Cheap local health checks for one materialized client release."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def release_is_healthy(
    version_root: Path,
    receipt: dict[str, Any] | None,
) -> bool:
    if receipt is None:
        return False
    materialized = receipt.get("materialized") or {}
    python = materialized.get("python") or {}
    for command in python.get("commands") or []:
        executable = version_root / "runtime" / "python" / "bin" / command
        if not executable.is_file() or not os.access(executable, os.X_OK):
            return False
    app = materialized.get("macos_app") or {}
    if app:
        path = version_root / str(app.get("path") or "")
        if not (path / "Contents" / "Info.plist").is_file():
            return False
    for asset in receipt.get("assets") or []:
        adapter = asset.get("adapter") or {}
        if adapter:
            path = version_root / str(adapter.get("path") or "")
            if not (path / "adapter.json").is_file():
                return False
    return True
