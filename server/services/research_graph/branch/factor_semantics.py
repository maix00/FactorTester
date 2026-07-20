"""Cold-path server evidence for the factor-semantics transition."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import settings as Settings
from server.services import factor_revisions, research_configurations
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.research_cycle import (
    checkpoint_from_branch_row,
)
from server.services.research_graph.research_cycle.factor_semantics_evidence import (
    project_factor_semantics_evidence,
)
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


SERVER_ACTION = "bind_factor_semantics"
REQUEST_FIELD = "factor_semantics_request"
_SERVER_GUARDS = (
    "factor_revision_manifests_bound",
    "selected_factor_semantics_resolved",
)


def prepare_transition(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    edge_id: str,
    request: Any,
) -> dict[str, Any] | None:
    if request is None:
        return None
    revision = _request_revision(request)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = load_instance_branch_with_latest_trace(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        if row is None:
            raise KeyError("graph branch not found")
        graph = load_graph_from_conn(
            conn,
            graph_id=str(row["graph_id"]),
            version=int(row["graph_version"]),
        ) or {}
        edge = _edge(graph, edge_id)
        _validate_edge(row=row, edge=edge)
        checkpoint = checkpoint_from_branch_row(row)
        if checkpoint is None:
            raise ValueError(
                "factor semantics requires a Research Cycle checkpoint"
            )
        expected = _branch_identity(row)
        workspace_id = str(row["workspace_id"])
    configuration = research_configurations.load_workspace_configuration(
        workspace_id=workspace_id,
        owner=owner,
    )
    if configuration is None:
        raise ValueError("research workspace configuration not found")
    if int(configuration["revision"]) != revision:
        raise ValueError("factor semantics configuration revision changed")
    frozen = factor_revisions.freeze_factor_revisions(
        configuration,
        owner=owner,
    )
    envelope, resolved = project_factor_semantics_evidence(
        configuration=frozen,
        checkpoint=checkpoint,
    )
    return {
        "expected": expected,
        "guard_facts": {
            "factor_revision_manifests_bound": True,
            "selected_factor_semantics_resolved": resolved,
        },
        "envelope": envelope,
        "evidence_ref": "evidence:" + envelope["envelope_hash"],
    }


def bind_server_evidence(
    evidence: dict[str, Any],
    prepared: dict[str, Any] | None,
) -> dict[str, Any]:
    value = deepcopy(evidence)
    value.pop(REQUEST_FIELD, None)
    for field in _SERVER_GUARDS:
        value.pop(field, None)
    if prepared is None:
        return value
    value["server_evidence"] = {
        "factor_semantics": deepcopy(prepared["envelope"]),
    }
    raw_refs = value.get("evidence_refs", [])
    if not isinstance(raw_refs, list) or not all(
        isinstance(item, str) and item for item in raw_refs
    ):
        raise ValueError("evidence_refs must be a reference array")
    refs = list(raw_refs)
    if prepared["evidence_ref"] not in refs:
        refs.append(prepared["evidence_ref"])
    value["evidence_refs"] = refs
    return value


def validate_preflight(
    *,
    row: Any,
    edge: dict[str, Any],
    prepared: dict[str, Any] | None,
) -> None:
    if edge.get("server_action") == SERVER_ACTION and prepared is None:
        raise ValueError(
            "factor semantics transition requires factor_semantics_request"
        )
    if prepared is None:
        return
    _validate_edge(row=row, edge=edge)
    if _branch_identity(row) != prepared["expected"]:
        raise ValueError(
            "factor semantics preflight is stale; inspect factors again"
        )


def _request_revision(value: Any) -> int:
    if not isinstance(value, dict) or set(value) != {
        "configuration_revision"
    }:
        raise ValueError(
            "factor_semantics_request requires configuration_revision"
        )
    revision = value.get("configuration_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("configuration_revision must be positive")
    return revision


def _branch_identity(row: Any) -> dict[str, Any]:
    return {
        "current_node": str(row["current_node"]),
        "latest_trace_id": str(row["latest_trace_id"]),
        "graph_id": str(row["graph_id"]),
        "graph_version": int(row["graph_version"]),
        "workspace_id": str(row["workspace_id"]),
    }


def _validate_edge(*, row: Any, edge: dict[str, Any]) -> None:
    if edge.get("server_action") != SERVER_ACTION:
        raise ValueError("factor_semantics_request is not allowed on this edge")
    if str(edge.get("from_node") or "") != str(row["current_node"]):
        raise ValueError("factor semantics edge does not leave current node")


def _edge(graph: dict[str, Any], edge_id: str) -> dict[str, Any]:
    edge = next(
        (
            item for item in graph.get("edges") or []
            if str(item.get("edge_id") or "") == edge_id
        ),
        None,
    )
    if edge is None:
        raise KeyError("graph edge not found")
    return edge
