"""Bounded, read-only review packet for one Graph activation proposal."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import settings as Settings
from server.services.research_graph import activation_gate
from server.services.research_graph.versions import load_graph


_INTERNAL_AFFECTED_REF_PREFIXES = (
    "graph-proposal:",
    "gate-proposer:",
    "gate-action:",
    "gate-target-hash:",
    "graph-pointer-from:",
    "graph-pointer-reason-hash:",
)


def load_proposal_review_packet(
    *,
    owner_user_id: str,
    proposal_id: str,
) -> dict[str, Any]:
    """Describe the exact immutable target without exposing Agent identities."""
    case = activation_gate.load_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        case_id=proposal_id,
    )
    target = _proposal_target(case)
    graph = load_graph(
        graph_id=target["graph_id"],
        version=target["version"],
    )
    if graph is None:
        raise KeyError("proposal target Graph version not found")
    if str(graph["content_hash"]) != target["content_hash"]:
        raise ValueError("proposal target Graph hash does not match")
    readiness = activation_gate.activation_gate_readiness(case)
    return {
        "proposal": {
            "proposal_id": str(case["case_id"]),
            "action": activation_gate.gate_action(case),
            "diff_hash": target["diff_hash"],
            "conversation_ref": str(case["conversation_ref"]),
            "status": str(case["status"]),
            "created_at": case["created_at"],
            "evidence_refs": _proposal_evidence_refs(case),
        },
        "target_graph": {
            "graph_id": str(graph["graph_id"]),
            "version": int(graph["version"]),
            "content_hash": str(graph["content_hash"]),
            "parent_version": graph.get("parent_version"),
            "lifecycle": str(graph["lifecycle"]),
            "change_manifest": deepcopy(graph.get("change_manifest") or {}),
        },
        "gate_readiness": readiness,
        "review_contract": {
            "requires_settled_reviewer_invocation": True,
            "requires_independent_principal_and_lineage": True,
            "allowed_dispositions": [
                "approved",
                "rejected",
                "disagreed",
            ],
            "command": (
                "factortester research-graph review "
                f"{proposal_id} "
                "--disposition <approved|rejected|disagreed> "
                "--agent-execution-id "
                "<settled-independent-reviewer-invocation-id> "
                "[--evidence-ref <ref>]"
            ),
        },
    }


def _proposal_target(case: dict[str, Any]) -> dict[str, Any]:
    refs = [
        str(ref)
        for ref in case.get("affected_refs") or []
        if str(ref).startswith("graph-proposal:")
    ]
    if len(refs) != 1:
        raise ValueError("activation Gate Graph target is invalid")
    body = refs[0][len("graph-proposal:"):]
    try:
        graph_and_version, graph_hash, diff_hash = body.rsplit(":", 2)
        graph_id, version_text = graph_and_version.rsplit("@", 1)
        version = int(version_text)
    except (TypeError, ValueError) as exc:
        raise ValueError("activation Gate Graph target is invalid") from exc
    if not graph_id or version < 1:
        raise ValueError("activation Gate Graph target is invalid")
    return {
        "graph_id": graph_id,
        "version": version,
        "content_hash": graph_hash,
        "diff_hash": diff_hash,
    }


def _proposal_evidence_refs(case: dict[str, Any]) -> list[str]:
    return [
        str(ref)
        for ref in case.get("affected_refs") or []
        if not str(ref).startswith(_INTERNAL_AFFECTED_REF_PREFIXES)
    ]
