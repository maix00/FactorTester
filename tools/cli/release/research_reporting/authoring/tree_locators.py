"""SQLite-backed parent indexes for fast report-tree traversal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_sqlite_index import component_parent


def locator_exists(
    paths: dict[str, Path], node_id: str, visible_generation: int,
) -> bool:
    return component_parent(paths, node_id, visible_generation) is not None


def load_locator(
    paths: dict[str, Path], node_id: str,
) -> dict[str, Any] | None:
    parent_id = component_parent(paths, node_id, 2**63 - 1)
    if parent_id is not None:
        return {
            "node_id": node_id,
            "parent_id": parent_id,
            "generation": 0,
        }
    return None
