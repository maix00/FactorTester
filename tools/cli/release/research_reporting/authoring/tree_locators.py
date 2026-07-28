"""Non-authoritative parent indexes for fast report-tree traversal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .tree_paths import locator_path
from .tree_schema import identifier
from .tree_store import atomic_write, load_json


def write_locators(
    paths: dict[str, Path], entries: list[tuple[str, str]], generation: int,
) -> None:
    for node_id, parent_id in entries:
        payload = encode_locator(node_id, parent_id, generation)
        path = locator_path(paths, node_id)
        if path.exists() and path.read_bytes() == payload:
            continue
        atomic_write(path, payload)


def locator_exists(
    paths: dict[str, Path], node_id: str, visible_generation: int,
) -> bool:
    value = load_locator(paths, node_id)
    return value is not None and value["generation"] <= visible_generation


def load_locator(
    paths: dict[str, Path], node_id: str,
) -> dict[str, Any] | None:
    path = locator_path(paths, node_id)
    if not path.is_file():
        return None
    try:
        value = load_json(path, label="报告节点索引")
        if set(value) != {"node_id", "parent_id", "generation"}:
            return None
        identifier(value["node_id"], "locator.node_id")
        identifier(value["parent_id"], "locator.parent_id")
        if not isinstance(value["generation"], int) or value["generation"] < 0:
            return None
    except ValueError:
        return None
    if value["node_id"] != node_id:
        return None
    return value


def encode_locator(node_id: str, parent_id: str, generation: int) -> bytes:
    identifier(node_id, "locator.node_id")
    identifier(parent_id, "locator.parent_id")
    if not isinstance(generation, int) or generation < 0:
        raise ValueError("locator.generation is invalid")
    return (
        f'{{"node_id":"{node_id}","parent_id":"{parent_id}",'
        f'"generation":{generation}}}\n'
    ).encode("utf-8")
