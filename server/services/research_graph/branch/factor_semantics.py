"""Cold-path server evidence for the factor-semantics transition."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import settings as Settings
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
from tools.cli.factor_subject_refs import factor_subject_kind
from tools.data.sqlite.db import connect_sqlite

SERVER_ACTION = "bind_factor_semantics"
REQUEST_FIELD = "factor_semantics_request"
_SERVER_GUARDS = (
    "frozen_factor_formulas_bound",
    "selected_factor_semantics_resolved",
)


def prepare_transition(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    edge_id: str,
    request: Any,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
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
        if edge.get("server_action") != SERVER_ACTION and request is None:
            return None
        _validate_edge(row=row, edge=edge)
        checkpoint = checkpoint_from_branch_row(row)
        if checkpoint is None:
            raise ValueError(
                "factor semantics requires a Research Cycle checkpoint"
            )
        expected = _branch_identity(row)
    factor_subject_refs = _transition_factor_subject_refs(
        checkpoint=checkpoint,
        evidence=evidence or {},
    )
    envelope, resolved = project_factor_semantics_evidence(
        checkpoint=checkpoint,
        factor_subject_refs=factor_subject_refs,
    )
    return {
        "expected": expected,
        "guard_facts": {
            "frozen_factor_formulas_bound": True,
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
            "factor semantics transition could not bind frozen factor subjects"
        )
    if prepared is None:
        return
    _validate_edge(row=row, edge=edge)
    if _branch_identity(row) != prepared["expected"]:
        raise ValueError(
            "factor semantics preflight is stale; inspect factors again"
        )


def _branch_identity(row: Any) -> dict[str, Any]:
    return {
        "current_node": str(row["current_node"]),
        "latest_trace_id": str(row["latest_trace_id"]),
        "graph_id": str(row["graph_id"]),
        "graph_version": int(row["graph_version"]),
    }


def _validate_edge(*, row: Any, edge: dict[str, Any]) -> None:
    if edge.get("server_action") != SERVER_ACTION:
        raise ValueError("factor semantics action is not allowed on this edge")
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


def _transition_factor_subject_refs(
    *,
    checkpoint: dict[str, Any],
    evidence: dict[str, Any],
) -> list[str]:
    values = evidence.get("factor_subject_refs")
    if not isinstance(values, list) or not values:
        raise ValueError(
            "factor semantics requires explicit factor_subject_refs from "
            "the current report bindings"
        )
    refs: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("research factor subject ref must be text")
        kind = factor_subject_kind(value)
        if kind != "factor":
            raise ValueError("factor semantics requires a frozen factor")
        refs.add(value)
    _validate_subject_matches_checkpoint(checkpoint, refs)
    return sorted(refs)


def _validate_subject_matches_checkpoint(
    checkpoint: dict[str, Any], refs: set[str],
) -> None:
    expected_refs = {
        str(scope.get("factor_ref") or "").strip()
        for collection in ("claims", "obligations")
        for item in checkpoint.get(collection) or []
        for scope in [item.get("scope") if isinstance(item, dict) else None]
        if isinstance(scope, dict) and scope.get("factor_ref")
    }
    if expected_refs and not refs.issubset(expected_refs):
        raise ValueError(
            "frozen factor subjects do not match the accepted research subject"
        )
