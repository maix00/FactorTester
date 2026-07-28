"""Incremental global binding identifiers for one report tree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .tree_schema import identifier
from .tree_store import atomic_write, load_json, load_node


def ensure_binding_index(
    paths: dict[str, Path], root: dict[str, Any], generation: int,
) -> None:
    """Build the index once for a pre-index tree, then retain it incrementally."""
    if _index_generation(paths) == generation:
        return
    entries = _collect(paths, root)
    _write_entries(paths, entries, generation)
    _write_index(paths, generation)


def binding_exists(
    paths: dict[str, Path], binding_id: str, generation: int,
) -> bool:
    value = _load_entry(paths, binding_id)
    return value is not None and value["generation"] <= generation


def publish_binding_index(
    paths: dict[str, Path], binding_ids: set[str], generation: int,
) -> None:
    _write_entries(paths, binding_ids, generation)
    _write_index(paths, generation)


def _collect(paths: dict[str, Path], root: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    seen: set[str] = set()

    def visit(node: dict[str, Any]) -> None:
        node_id = str(node["node_id"])
        if node_id in seen:
            raise ValueError("report tree contains a node cycle")
        seen.add(node_id)
        for binding in node["bindings"]:
            binding_id = str(binding["binding_id"])
            if binding_id in result:
                raise ValueError("report tree has duplicate binding_id")
            result.add(binding_id)
        for child in node["children"]:
            visit(load_node(paths, child["ref"]))

    visit(root)
    return result


def _write_entries(
    paths: dict[str, Path], binding_ids: set[str], generation: int,
) -> None:
    for binding_id in binding_ids:
        identifier(binding_id, "binding.binding_id")
        atomic_write(_entry_path(paths, binding_id), _entry_payload(binding_id, generation))


def _load_entry(paths: dict[str, Path], binding_id: str) -> dict[str, Any] | None:
    path = _entry_path(paths, binding_id)
    if not path.is_file():
        return None
    try:
        value = load_json(path, label="报告绑定索引")
        if set(value) != {"binding_id", "generation"}:
            return None
        identifier(value["binding_id"], "binding.binding_id")
        if not isinstance(value["generation"], int) or value["generation"] < 0:
            return None
    except ValueError:
        return None
    return value if value["binding_id"] == binding_id else None


def _index_generation(paths: dict[str, Path]) -> int | None:
    path = paths["binding_index"]
    if not path.is_file():
        return None
    try:
        value = load_json(path, label="报告绑定索引元数据")
        valid = set(value) == {"schema_version", "generation"}
        if valid and value["schema_version"] == 1 and isinstance(value["generation"], int):
            return value["generation"]
    except ValueError:
        pass
    return None


def _write_index(paths: dict[str, Path], generation: int) -> None:
    atomic_write(paths["binding_index"], json.dumps(
        {"schema_version": 1, "generation": generation},
        separators=(",", ":"), sort_keys=True,
    ).encode() + b"\n")


def _entry_path(paths: dict[str, Path], binding_id: str) -> Path:
    identifier(binding_id, "binding.binding_id")
    return paths["binding_locators"] / f"{binding_id}.json"


def _entry_payload(binding_id: str, generation: int) -> bytes:
    return json.dumps(
        {"binding_id": binding_id, "generation": generation},
        separators=(",", ":"), sort_keys=True,
    ).encode() + b"\n"
