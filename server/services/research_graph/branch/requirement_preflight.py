"""Deterministic obligation-contract delta for same-node Graph reentry."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson


def assess_requirement_continuation(
    *,
    source_graph: dict[str, Any],
    target_graph: dict[str, Any],
    target_node: str,
) -> dict[str, Any]:
    """Describe material catalog and current-entry changes without judging them."""
    source_catalog = _requirements(source_graph)
    target_catalog = _requirements(target_graph)
    source_ids = set(source_catalog)
    target_ids = set(target_catalog)
    metadata_changed_ids = sorted(
        requirement_id
        for requirement_id in source_ids & target_ids
        if _contract_identity(source_catalog[requirement_id])
        != _contract_identity(target_catalog[requirement_id])
    )
    revised_ids = sorted(
        requirement_id
        for requirement_id in source_ids & target_ids
        if _semantic_revision(source_catalog[requirement_id])
        != _semantic_revision(target_catalog[requirement_id])
    )
    source_entry = _entry_ids(source_graph, target_node)
    target_entry = _entry_ids(target_graph, target_node)
    catalog_delta = {
        "added_ids": sorted(target_ids - source_ids),
        "changed_ids": metadata_changed_ids,
        "removed_ids": sorted(source_ids - target_ids),
    }
    entry_revised = sorted((source_entry & target_entry) & set(revised_ids))
    entry_metadata_changed = sorted(
        (source_entry & target_entry) & set(metadata_changed_ids)
        - set(entry_revised)
    )
    identity = {
        "target_node": target_node,
        "catalog_added_count": len(catalog_delta["added_ids"]),
        "catalog_changed_count": len(catalog_delta["changed_ids"]),
        "catalog_removed_count": len(catalog_delta["removed_ids"]),
        "catalog_delta_hash": _hash(catalog_delta),
        "entry_added_ids": sorted(target_entry - source_entry),
        "entry_revised_ids": entry_revised,
        "entry_metadata_changed_ids": entry_metadata_changed,
        "entry_removed_ids": sorted(source_entry - target_entry),
    }
    identity["assessment_required_ids"] = sorted(
        set(identity["entry_added_ids"]) | set(entry_revised)
    )
    return {
        **identity,
        "delta_hash": _hash(identity),
    }


def _requirements(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog = graph.get("requirement_catalog") or {}
    return {
        str(item.get("requirement_id") or ""): item
        for item in catalog.get("requirements") or []
        if isinstance(item, dict) and str(item.get("requirement_id") or "")
    }


def _entry_ids(graph: dict[str, Any], node_id: str) -> set[str]:
    node = next(
        (
            item for item in graph.get("nodes") or []
            if str(item.get("node_id") or "") == node_id
        ),
        {},
    )
    return {str(item) for item in node.get("entry_requirement_refs") or []}


def _contract_identity(value: dict[str, Any]) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)


def _semantic_revision(value: dict[str, Any]) -> tuple[int, str]:
    return (
        int(value.get("revision") or 0),
        str(value.get("semantic_hash") or ""),
    )


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
