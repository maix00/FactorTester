"""Canonical projection of Research Graph node and Edge packets."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def branch_identity(
    *,
    instance_id: str,
    branch_id: str,
    packet: dict[str, Any],
) -> dict[str, str]:
    return {
        "branch_ref": f"graph-branch:{instance_id}:{branch_id}",
        "graph_ref": _required_text(packet.get("graph"), "graph"),
        "current_node": _required_text(
            (packet.get("node") or {}).get("node_id"),
            "node.node_id",
        ),
        "context_ref": _required_text(
            packet.get("context_ref"),
            "context_ref",
        ),
        "checkpoint_ref": checkpoint_ref(packet),
    }


def checkpoint_ref(packet: dict[str, Any]) -> str:
    explicit = packet.get("checkpoint_ref")
    if isinstance(explicit, str):
        return explicit
    traces = [
        item for item in packet.get("changed_refs") or []
        if isinstance(item, str) and item.startswith("trace:")
    ]
    if not traces:
        return ""
    if len(traces) != 1:
        raise ValueError(
            "server node packet does not expose one checkpoint_ref"
        )
    return traces[0]


def obligations(packet: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "obligation_id": str(item["obligation_id"]),
            "title_zh": str(item.get("title_zh") or ""),
            "status": str(item.get("status") or ""),
            "claim_ids": list(item.get("claim_ids") or []),
            "scope": deepcopy(item.get("scope") or {}),
            **({
                "coverage_scope": deepcopy(item["coverage_scope"]),
            } if item.get("coverage_scope") else {}),
            "claim_scopes": deepcopy(item.get("claim_scopes") or []),
            "contract_hash": str(item.get("contract_hash") or ""),
            "methodology_hash": str(item.get("methodology_hash") or ""),
            "materiality": str(item.get("materiality") or ""),
            "epistemic_question": str(item.get("question_summary") or ""),
            "requirement_refs": list(item.get("requirement_refs") or []),
            "detail_ref": str(item.get("detail_ref") or ""),
        }
        for item in packet.get("current_obligations") or []
        if isinstance(item, dict) and item.get("obligation_id")
    ]


def requirements(packet: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        deepcopy(item)
        for item in packet.get("entry_requirements") or []
        if isinstance(item, dict) and item.get("requirement_id")
    ]


def requirement_union(
    node_packet: dict[str, Any],
    edge_packet: dict[str, Any],
) -> list[dict[str, Any]]:
    values = requirements(node_packet)
    present = {
        str(item["requirement_id"]) for item in values
    }
    for item in (
        (edge_packet.get("edge") or {}).get("obligation_requirements")
        or []
    ):
        if not isinstance(item, dict) or not item.get("requirement_id"):
            continue
        requirement_id = str(item["requirement_id"])
        if requirement_id in present:
            continue
        values.append(deepcopy(item))
        present.add(requirement_id)
    return values


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"server node packet lacks {field}")
    return value
