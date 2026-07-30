"""Shared exact-identity helpers for local shadow migration."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from typing import Any

import orjson


def validate_shadow_record(
    record: dict[str, Any],
    *,
    source_work_package_id: str,
    instance_id: str,
    branch_id: str,
) -> None:
    provenance = record.get("provenance") or {}
    if (
        record["record_id"] != instance_id
        or record["graph_instance_ref"] != f"work-package:{instance_id}"
        or record["graph_branch_ref"]
        != f"graph-branch:{instance_id}:{branch_id}"
        or provenance.get("kind") != "shadow_graph_continuation"
        or provenance.get("source_work_package_id")
        != source_work_package_id
    ):
        raise ValueError("local shadow research binding is not migratable")


def branch_id(value: str) -> str:
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != "graph-branch":
        raise ValueError("local shadow branch ref is invalid")
    return parts[2]


def git_head(path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path, check=True, capture_output=True, text=True,
    ).stdout.strip()


def file_hash(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"migration source file is invalid: {path.name}")
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def validate_plan_hash(plan: dict[str, Any]) -> None:
    supplied = str(plan.get("plan_hash") or "")
    value = {key: item for key, item in plan.items() if key != "plan_hash"}
    if supplied != canonical_hash(value):
        raise ValueError("local shadow migration plan hash is invalid")


def canonical_hash(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
