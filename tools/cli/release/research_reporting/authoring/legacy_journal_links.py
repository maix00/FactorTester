"""Stable component and chip identities for retired Journal migration."""

from __future__ import annotations

import hashlib
from typing import Any

from .tree_schema import BINDING_KINDS


def component_id(*parts: str) -> str:
    return "legacy-" + digest("\x1f".join(parts))[:48]


def link_chips(
    value: dict[str, Any], component: str, bindings: set[str], *,
    include_checkpoint: bool = False,
) -> list[dict[str, Any]]:
    result = []
    for link in value.get("links") or []:
        if isinstance(link, dict):
            item = chip(
                component, bindings, str(link.get("kind") or "graph_reference"),
                str(link.get("target_ref") or ""), str(link.get("label") or ""),
                {"link_id": str(link.get("link_id") or "")},
            )
            if item is not None:
                result.append(item)
    if include_checkpoint:
        item = chip(
            component, bindings, "checkpoint",
            str(value.get("checkpoint_ref") or ""), "历史检查点", {},
        )
        if item is not None:
            result.append(item)
    return result


def selected_chips(
    block: dict[str, Any], links: list[Any], component: str,
    bindings: set[str],
) -> list[dict[str, Any]]:
    wanted = set(block.get("link_ids") or [])
    result = []
    for link in links:
        if not isinstance(link, dict) or link.get("link_id") not in wanted:
            continue
        item = chip(
            component, bindings, str(link.get("kind") or "graph_reference"),
            str(link.get("target_ref") or ""), str(link.get("label") or ""),
            {"link_id": str(link.get("link_id") or "")},
        )
        if item is not None:
            result.append(item)
    return result


def append_chip(
    operations: list[dict[str, Any]], component: str, bindings: set[str],
    kind: str, target: str, label: str, data: dict[str, Any],
) -> None:
    item = chip(component, bindings, kind, target, label, data)
    if item is not None:
        operations.append({"op": "chip", "component_id": component, "binding": item})


def chip(
    component: str, bindings: set[str], kind: str, target: str, label: str,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    if not target:
        return None
    valid_kind = kind if kind in BINDING_KINDS else "graph_reference"
    stable_target = target if "/" not in target else "legacy-link:" + digest(target)
    item = {
        "binding_id": component_id("legacy-binding", component, valid_kind, stable_target),
        "kind": valid_kind, "target_ref": stable_target, "label": label,
        "data": {**data, **({"legacy_target_ref": target} if stable_target != target else {})},
    }
    if item["binding_id"] in bindings:
        return None
    bindings.add(item["binding_id"])
    return item


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
