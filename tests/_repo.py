from __future__ import annotations

from pathlib import Path


def repo_root(start: Path | None = None) -> Path:
    base = start or Path(__file__)
    for parent in base.resolve().parents:
        if (parent / "server").is_dir() and (parent / "tools").is_dir():
            return parent
    raise RuntimeError("Could not locate repository root")
