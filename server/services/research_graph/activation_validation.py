"""Server-derived validation gate for one Graph pointer proposal."""

from __future__ import annotations

from copy import deepcopy
import time
from typing import Any

import settings as Settings
from server.services.research_graph import activation_gate
from server.services.research_graph.protocol import (
    assert_no_skill_identity,
    json_hash,
)
from server.services.research_graph.shadow_validation import (
    derive_activation_evidence,
)
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


_VALIDATION_GATES = (
    "replay_passed",
    "shadow_passed",
    "capability_resolution_complete",
    "requirement_resolvers_complete",
    "unaffected_jobs_preserved",
    "token_efficiency_passed",
)


def record_validation(
    *,
    graph_id: str,
    version: int,
    actor: str,
    proposal_id: str,
    evidence: dict[str, Any],
    owner_user_id: str = "",
) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise ValueError("validation evidence must be an object")
    assert_no_skill_identity(evidence, location="validation evidence")
    forbidden = set(_VALIDATION_GATES) | {
        "token_metrics",
        "replay_summary",
        "shadow_summary",
        "requirement_resolver_summary",
    }
    supplied = sorted(forbidden.intersection(evidence))
    if supplied:
        raise ValueError(
            "client validation conclusions are not accepted: "
            + ", ".join(supplied)
        )
    refs = evidence.get("shadow_comparison_refs")
    if not isinstance(refs, dict):
        raise ValueError("shadow_comparison_refs are required")
    evidence_value = derive_activation_evidence(
        graph_id=graph_id,
        version=version,
        routine_instance_id=str(refs.get("routine_instance_id") or ""),
        routine_branch_id=str(refs.get("routine_branch_id") or ""),
        baseline_run_id=str(refs.get("baseline_run_id") or ""),
    )
    evidence_value["shadow_comparison_refs"] = deepcopy(refs)
    validation_id = json_hash(evidence_value)
    row = {
        "validation_id": validation_id,
        "graph_id": graph_id,
        "version": int(version),
        "actor": actor,
        "evidence": deepcopy(evidence_value),
        "created_at": time.time(),
    }
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=version,
        )
    if graph is None:
        raise KeyError("graph version not found")
    owner = owner_user_id or actor
    case = activation_gate.load_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner,
        case_id=proposal_id,
    )
    activation_gate.require_graph_target(
        case,
        graph_id=graph_id,
        graph_version=version,
        graph_hash=str(graph["content_hash"]),
    )
    failed = [
        gate for gate in _VALIDATION_GATES
        if evidence_value.get(gate) is not True
    ]
    if failed:
        details = list(evidence_value.get("token_failures") or [])
        raise ValueError(
            "activation validation failed: "
            + ", ".join(dict.fromkeys([*failed, *details]))
        )
    activation_gate.record_activation_validation(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner,
        case_id=proposal_id,
        validation_summary_hash=validation_id,
    )
    return row
