"""Server-owned construction of canonical entry-resolution attempts."""

from __future__ import annotations

import hashlib
from typing import Any

from .guard import resume_guard_hash
from .obligation_refs import blocking_obligation_refs
from .stack_state import text_ids


def project_entry_attempt(
    *,
    graph: dict[str, Any],
    target_node: str,
    checkpoint: dict[str, Any] | None,
    origin_ref: str,
    unresolved_requirement_refs: list[str],
    resolved_requirement_refs: list[str],
) -> dict[str, Any]:
    graph_ref = _graph_ref(graph)
    checkpoint_ref = _checkpoint_ref(checkpoint)
    requirements = _declared_requirements(graph, target_node)
    unresolved = text_ids(unresolved_requirement_refs)
    resolved = text_ids(resolved_requirement_refs)
    blocking = blocking_obligation_refs(
        checkpoint=checkpoint,
        requirement_refs=requirements,
    )
    value: dict[str, Any] = {
        "schema_version": 2,
        "entry_attempt_id": _attempt_id(
            origin_ref=origin_ref,
            graph_ref=graph_ref,
            target_node=target_node,
        ),
        "graph_ref": graph_ref,
        "target_node": target_node,
        "entry_requirement_refs": requirements,
        "blocking_obligation_refs": blocking,
        "unresolved_entry_requirement_refs": unresolved,
        "resolved_entry_requirement_refs": resolved,
        "status": "resolving" if unresolved else "resolved",
    }
    if checkpoint_ref:
        value["origin_checkpoint_ref"] = checkpoint_ref
        value["resume_guard_hash"] = resume_guard_hash(
            graph_ref=graph_ref,
            target_node=target_node,
            origin_checkpoint_ref=checkpoint_ref,
            blocking_obligation_refs=blocking,
            entry_requirement_refs=requirements,
        )
    return value


def graph_reference(graph: dict[str, Any]) -> str:
    return _graph_ref(graph)


def checkpoint_reference(checkpoint: dict[str, Any] | None) -> str:
    return _checkpoint_ref(checkpoint)


def _graph_ref(graph: dict[str, Any]) -> str:
    graph_id = str(graph.get("graph_id") or "")
    version = int(graph.get("version") or 0)
    content_hash = str(graph.get("content_hash") or "")
    if not graph_id or not version or not content_hash:
        raise ValueError("entry resolution requires an immutable Graph ref")
    return f"{graph_id}@v{version}#{content_hash}"


def _checkpoint_ref(checkpoint: dict[str, Any] | None) -> str:
    projection_hash = (
        str(checkpoint.get("projection_hash") or "")
        if isinstance(checkpoint, dict)
        else ""
    )
    return (
        f"research-cycle-checkpoint:{projection_hash}"
        if projection_hash
        else ""
    )


def _declared_requirements(
    graph: dict[str, Any], target_node: str,
) -> list[str]:
    node = next(
        (
            item
            for item in graph.get("nodes") or []
            if str(item.get("node_id") or "") == target_node
        ),
        None,
    )
    if node is None:
        raise ValueError(f"target Graph lacks {target_node} node")
    return text_ids(node.get("entry_requirement_refs"))
def _attempt_id(*, origin_ref: str, graph_ref: str, target_node: str) -> str:
    if not origin_ref:
        raise ValueError("entry attempt requires a server origin ref")
    digest = hashlib.sha256(
        f"{origin_ref}|{graph_ref}|{target_node}".encode()
    ).hexdigest()
    return f"entry-attempt-{digest}"
