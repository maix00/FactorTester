"""Atomic content-addressed persistence for one report tree."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .tree_paths import node_path
from .tree_assets import validate_asset
from .tree_schema import canonical_bytes, digest, validate_node


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_bytes(payload)
        with temp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temp.exists():
            temp.unlink()


@contextmanager
def tree_lock(paths: dict[str, Path]) -> Iterator[None]:
    paths["root"].mkdir(parents=True, exist_ok=True)
    with paths["lock"].open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取{label}: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}必须是对象")
    return value


def validate_head(value: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version", "report_id", "title", "language", "generation",
        "root_ref", "assets", "changed_node_ids", "locator_generation",
    }
    if set(value) != fields or value.get("schema_version") != 2:
        raise ValueError("report tree HEAD schema is invalid")
    if not isinstance(value["generation"], int) or value["generation"] < 0:
        raise ValueError("report tree generation is invalid")
    if (
        not isinstance(value["locator_generation"], int)
        or value["locator_generation"] < 0
        or value["locator_generation"] > value["generation"]
    ):
        raise ValueError("report tree locator generation is invalid")
    if not isinstance(value["assets"], list) or not isinstance(value["changed_node_ids"], list):
        raise ValueError("report tree HEAD lists are invalid")
    for asset in value["assets"]:
        validate_asset(asset)
    return value


def load_head(paths: dict[str, Path]) -> dict[str, Any]:
    return validate_head(load_json(paths["head"], label="报告 HEAD"))


def load_node(paths: dict[str, Path], ref: str) -> dict[str, Any]:
    if ref.startswith("/") or ".." in ref.split("/"):
        raise ValueError("report node reference is invalid")
    return validate_node(load_json(paths["root"] / ref, label="报告节点"))


def store_node(
    paths: dict[str, Path], node: dict[str, Any], *, created: set[str] | None = None,
) -> tuple[str, str]:
    value = validate_node(node)
    node_hash = digest(value)
    path = node_path(paths, value["node_id"], node_hash)
    payload = canonical_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("content-addressed report node collision")
    else:
        atomic_write(path, payload)
        if created is not None:
            created.add(str(path.relative_to(paths["root"])))
    return str(path.relative_to(paths["root"])), node_hash


def write_head(paths: dict[str, Path], head: dict[str, Any]) -> dict[str, Any]:
    value = validate_head(head)
    atomic_write(paths["head"], canonical_bytes(value) + b"\n")
    return value
