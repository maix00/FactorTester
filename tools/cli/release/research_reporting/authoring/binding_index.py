"""SQLite-backed global binding identifiers for one report tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_sqlite_index import (
    binding_exists as sqlite_binding_exists,
    ensure_sqlite_index,
)


def ensure_binding_index(
    paths: dict[str, Path], root: dict[str, Any], generation: int,
) -> None:
    ensure_sqlite_index(paths, root, generation)


def binding_exists(
    paths: dict[str, Path], binding_id: str, generation: int,
) -> bool:
    return sqlite_binding_exists(paths, binding_id, generation)
