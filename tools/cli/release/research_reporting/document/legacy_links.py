"""External binding projection for legacy report fragments."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .bindings import add_binding

_KINDS = {
    "evidence", "obligation", "task", "job", "claim", "artifact",
    "report_requirement", "graph_reference", "checkpoint", "run",
}


def attach_link(
    bindings: dict[str, Any], document: dict[str, Any],
    component_id: str, link: dict[str, Any],
) -> dict[str, Any]:
    kind = str(link.get("kind") or "graph_reference")
    target = str(link.get("target_ref") or "")
    return attach(bindings, document, component_id, kind, target, str(link.get("label") or ""))


def attach(
    bindings: dict[str, Any], document: dict[str, Any], component_id: str,
    kind: str, target: str, label: str = "",
) -> dict[str, Any]:
    if not target or "/" in target:
        return bindings
    binding_id = safe_id(f"binding-{component_id}-{kind}-{target}")
    if any(item.get("binding_id") == binding_id for item in bindings["bindings"]):
        return bindings
    return add_binding(
        bindings, document, component_id=component_id,
        binding_id=binding_id,
        kind=kind if kind in _KINDS else "graph_reference",
        target_ref=target, label=label,
    )


def safe_id(value: str) -> str:
    value = "".join(char if char.isalnum() or char in "._-" else "-" for char in value)
    return value[:120].strip("-") or "legacy"


def content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
