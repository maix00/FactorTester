"""Logical Work Package ownership of physical Graph branches."""

from __future__ import annotations

from typing import Any


def branch_bindings(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized branch bindings, including the legacy primary ref."""
    values = [
        dict(item)
        for item in record.get("branch_bindings") or []
        if isinstance(item, dict)
    ]
    primary = str(record.get("graph_branch_ref") or "")
    if primary and not any(item.get("branch_ref") == primary for item in values):
        values.insert(0, {
            "branch_ref": primary,
            "kind": "live",
            "source_branch_ref": "",
        })
    return values


def binding_for(
    record: dict[str, Any],
    branch_ref: str,
) -> dict[str, Any] | None:
    matches = [
        item for item in branch_bindings(record)
        if item["branch_ref"] == branch_ref
    ]
    return matches[0] if len(matches) == 1 else None


def owns_branch(record: dict[str, Any], branch_ref: str) -> bool:
    return binding_for(record, branch_ref) is not None


def with_branch_binding(
    record: dict[str, Any],
    *,
    branch_ref: str,
    kind: str,
    source_branch_ref: str = "",
) -> dict[str, Any]:
    if kind not in {"live", "fork"}:
        raise ValueError("research branch binding kind is unsupported")
    if not _is_graph_branch_ref(branch_ref):
        raise ValueError("research branch binding ref is invalid")
    if source_branch_ref and not _is_graph_branch_ref(source_branch_ref):
        raise ValueError("research source branch binding ref is invalid")
    bindings = [
        item for item in branch_bindings(record)
        if item["branch_ref"] != branch_ref
    ]
    bindings.append({
        "branch_ref": branch_ref,
        "kind": kind,
        "source_branch_ref": source_branch_ref,
    })
    return {**record, "branch_bindings": bindings}


def _is_graph_branch_ref(value: str) -> bool:
    parts = str(value).split(":")
    return (
        len(parts) == 3
        and parts[0] == "graph-branch"
        and bool(parts[1])
        and bool(parts[2])
    )
