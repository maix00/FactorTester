"""Crash-consistent publication of a readable report-tree HEAD."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_store import load_head, store_node, write_head
from .tree_sqlite_index import publish_sqlite_index


def publish_tree_head(
    *,
    paths: dict[str, Path],
    previous: dict[str, Any],
    next_head: dict[str, Any],
    root: dict[str, Any],
    changed: list[str],
    created: set[str],
) -> dict[str, Any]:
    """Publish content first; acceleration indexes are recoverable derivatives."""
    root_ref, _ = store_node(paths, root, created=created)
    generation = previous["generation"] + 1
    provisional = {
        **next_head,
        "generation": generation,
        "root_ref": root_ref,
        "changed_node_ids": list(dict.fromkeys(changed)),
        "locator_generation": previous["locator_generation"],
    }
    _write_or_confirm(paths, provisional)

    try:
        publish_sqlite_index(
            paths, root, generation,
        )
    except Exception:
        locator_head = provisional
    else:
        locator_head = _advance_locator_generation(
            paths, previous, provisional, generation,
        )
    return locator_head


def _advance_locator_generation(
    paths: dict[str, Path],
    previous: dict[str, Any],
    provisional: dict[str, Any],
    generation: int,
) -> dict[str, Any]:
    if previous["locator_generation"] != previous["generation"]:
        return provisional
    indexed = {**provisional, "locator_generation": generation}
    try:
        _write_or_confirm(paths, indexed)
    except Exception:
        return provisional
    return indexed


def _write_or_confirm(
    paths: dict[str, Path], expected: dict[str, Any],
) -> None:
    """Treat a post-replace fsync failure as success when HEAD is durable."""
    try:
        write_head(paths, expected)
    except OSError:
        try:
            actual = load_head(paths)
        except (OSError, ValueError):
            raise
        if actual != expected:
            raise
