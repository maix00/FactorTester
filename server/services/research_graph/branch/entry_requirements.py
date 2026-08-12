"""Schema-v2 entry-requirement aliases and lazy contract reads."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def compact_entry_requirements(
    *,
    graph: dict[str, Any],
    node: dict[str, Any],
    checkpoint: dict[str, Any] | None,
    active_requirement_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Project aliases and existing obligation mappings without full bodies."""
    catalog = requirement_map(graph)
    obligations = checkpoint_obligations(checkpoint)
    rows = []
    declared_ids = [
        str(item) for item in node.get("entry_requirement_refs") or []
    ]
    if active_requirement_ids is None:
        selected_ids = declared_ids
    else:
        active_ids = set(active_requirement_ids)
        selected_ids = [
            requirement_id for requirement_id in declared_ids
            if requirement_id in active_ids
        ]
    for requirement_id in selected_ids:
        requirement = catalog.get(str(requirement_id))
        if requirement is None:
            raise ValueError(f"unknown node entry requirement: {requirement_id}")
        mapped = mapped_obligations(obligations, str(requirement_id))
        rows.append({
            "requirement_id": str(requirement_id),
            "title_zh": str(requirement.get("title_zh") or ""),
            "gate_policy": str(requirement.get("gate_policy") or ""),
            "mapped_obligation_refs": [
                f"obligation:{item['obligation_id']}" for item in mapped
            ],
            "mapped_statuses": sorted({
                str(item.get("status") or "") for item in mapped
            }),
            "detail_ref": f"graph-requirement:{requirement_id}",
        })
    return rows


def requirement_detail(
    *,
    graph: dict[str, Any],
    node: dict[str, Any],
    checkpoint: dict[str, Any] | None,
    requirement_id: str,
    allowed_requirement_ids: set[str] | None = None,
    requirement_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Load one current-node or candidate-Edge obligation requirement."""
    allowed = (
        {
            str(item) for item in node.get("entry_requirement_refs") or []
        }
        if allowed_requirement_ids is None
        else set(allowed_requirement_ids)
    )
    if requirement_id not in allowed:
        raise KeyError("requirement is not active at the current node or Edge")
    requirement = requirement_map(graph).get(requirement_id)
    if requirement is None:
        raise KeyError("graph requirement not found")
    mapped = mapped_obligations(
        checkpoint_obligations(checkpoint), requirement_id
    )
    report_ids = set(requirement.get("report_requirement_refs") or [])
    reports = [
        deepcopy(item)
        for item in graph.get("report_requirements") or []
        if str(item.get("report_requirement_id") or "") in report_ids
    ]
    return {
        "graph_ref": f"{graph['graph_id']}@v{graph['version']}",
        "node_id": str(node.get("node_id") or ""),
        "requirement_sources": list(requirement_sources or ["entry"]),
        "requirement": deepcopy(requirement),
        "mapped_obligations": [
            {
                "obligation_id": str(item.get("obligation_id") or ""),
                "status": str(item.get("status") or ""),
                "question_summary": str(
                    item.get("epistemic_question")
                    or item.get("question_summary")
                    or ""
                ),
                "detail_ref": (
                    "research-cycle-object:obligation:"
                    f"{item.get('obligation_id') or ''}"
                ),
            }
            for item in mapped
        ],
        "report_requirements": reports,
    }


def requirement_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog = graph.get("requirement_catalog") or {}
    return {
        str(item.get("requirement_id") or ""): item
        for item in catalog.get("requirements") or []
        if isinstance(item, dict)
    }


def checkpoint_obligations(
    checkpoint: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(checkpoint, dict):
        return []
    return [
        item for item in checkpoint.get("obligations") or []
        if isinstance(item, dict)
    ]


def mapped_obligations(
    obligations: list[dict[str, Any]],
    requirement_id: str,
) -> list[dict[str, Any]]:
    return [
        item for item in obligations
        if requirement_id in {
            bare_requirement_ref(ref)
            for ref in item.get("requirement_refs") or []
        }
    ]


def bare_requirement_ref(value: Any) -> str:
    return str(value or "").removeprefix("requirement:")
