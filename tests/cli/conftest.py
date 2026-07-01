from __future__ import annotations

import sys
from pathlib import Path


def _repo_root(start: Path) -> Path:
    for parent in start.resolve().parents:
        if (parent / "server").is_dir() and (parent / "tools").is_dir():
            return parent
    raise RuntimeError("Could not locate repository root")


ROOT = _repo_root(Path(__file__))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
