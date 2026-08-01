"""Cold-path server evidence for the existing data-contract transition."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import settings as Settings
from server.services.data_availability import (
    availability_for_scope,
    load_availability_profile,
    request_from_profile,
)
from server.services.research_evidence_registry import get_evidence
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.research_cycle import (
    checkpoint_from_branch_row,
)
from server.services.research_graph.research_cycle.data_availability_evidence import (
    project_data_provenance_evidence,
    project_availability_evidence,
    validate_availability_request,
)
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


SERVER_ACTION = "bind_data_availability"
REQUEST_FIELD = "data_availability_request"
_SERVER_GUARDS = (
    "data_availability_profile_bound",
    "material_data_obligations_adjudicated_or_not_triggered",
    "requested_product_availability_present",
    "required_market_fields_available",
    "historical_field_catalog_bound",
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
    """Bind a frozen Terminal Evidence snapshot without rescanning sources."""
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
        _validate_edge_request(row=row, edge=edge)
        checkpoint = checkpoint_from_branch_row(row)
        if checkpoint is None:
            raise ValueError(
                "data availability requires a Research Cycle checkpoint"
            )
        expected = {
            "current_node": str(row["current_node"]),
            "latest_trace_id": str(row["latest_trace_id"]),
            "graph_id": str(row["graph_id"]),
            "graph_version": int(row["graph_version"]),
        }
    if request is None:
        profile_ref = _terminal_profile_ref(owner=owner, evidence=evidence or {})
        profile = load_availability_profile(profile_ref)
        normalized_request = validate_availability_request(
            request_from_profile(profile)
        )
    else:
        # Compatibility for older clients. availability_for_scope is now a
        # persistent single-flight materialization, so this does not repeat a
        # prior scan for the same canonical request.
        normalized_request = validate_availability_request(request)
        availability_kwargs: dict[str, Any] = {
            "product_names": normalized_request["products"],
            "source_names": normalized_request["sources"],
            "frequency_names": normalized_request["frequencies"],
            "probe": normalized_request["probe"],
            "expanded": False,
        }
        if "fields" in normalized_request:
            availability_kwargs["required_fields"] = normalized_request["fields"]
        if "include_field_catalog" in normalized_request:
            availability_kwargs["include_field_catalog"] = normalized_request["include_field_catalog"]
        if "include_historical_fields" in normalized_request:
            availability_kwargs["include_historical_fields"] = normalized_request["include_historical_fields"]
        profile = availability_for_scope(**availability_kwargs)
    envelope, present = project_availability_evidence(
        profile=profile,
        request=normalized_request,
        checkpoint=checkpoint,
    )
    provenance_envelope = project_data_provenance_evidence(
        profile=profile,
        request=normalized_request,
        checkpoint=checkpoint,
    )
    return {
        "expected": expected,
        "guard_facts": {
            "data_availability_profile_bound": True,
            "requested_product_availability_present": present,
            "required_market_fields_available": _required_market_fields_available(
                envelope
            ),
            "historical_field_catalog_bound": _historical_field_catalog_bound(
                envelope
            ),
        },
        "envelope": envelope,
        "provenance_envelope": provenance_envelope,
        "evidence_ref": "evidence:" + envelope["envelope_hash"],
        "provenance_evidence_ref": (
            "evidence:" + provenance_envelope["envelope_hash"]
        ),
    }


def _terminal_profile_ref(
    *, owner: str, evidence: dict[str, Any],
) -> str:
    refs = evidence.get("evidence_refs") or []
    if not isinstance(refs, list):
        raise ValueError("evidence_refs must be a reference array")
    profile_refs: list[str] = []
    for evidence_ref in refs:
        if not isinstance(evidence_ref, str) or not evidence_ref.startswith("evidence:"):
            continue
        try:
            item = get_evidence(owner=owner, evidence_ref=evidence_ref)
        except KeyError:
            continue
        lifecycle = item.get("lifecycle") or {}
        if lifecycle.get("status") == "excluded":
            continue
        fragments = item.get("fragments") or []
        if not any(
            isinstance(fragment, dict)
            and isinstance(fragment.get("source"), dict)
            and str(fragment["source"].get("source_kind") or "") == "terminal"
            for fragment in fragments
        ):
            continue
        applicability = item.get("applicability") or {}
        for source_ref in applicability.get("source_refs") or []:
            if str(source_ref).startswith("data-availability-profile:sha256:"):
                profile_refs.append(str(source_ref))
    unique = list(dict.fromkeys(profile_refs))
    if not unique:
        raise ValueError(
            "data_contract transition requires Terminal Evidence bound to "
            "a frozen data availability profile"
        )
    if len(unique) != 1:
        raise ValueError(
            "data_contract transition requires one combined data availability "
            "profile; query all required sources in one CLI execution"
        )
    return unique[0]


def _required_market_fields_available(envelope: dict[str, Any]) -> bool:
    facts = envelope.get("facts") or {}
    request = facts.get("request") or {}
    fields = request.get("fields")
    statuses = facts.get("required_field_status")
    if not isinstance(fields, list) or not fields or not isinstance(statuses, list):
        return False
    return bool(statuses) and all(
        isinstance(item, dict)
        and bool({"direct", "derived"}.intersection(item.get("statuses") or []))
        for item in statuses
    )


def _historical_field_catalog_bound(envelope: dict[str, Any]) -> bool:
    facts = envelope.get("facts") or {}
    request = facts.get("request") or {}
    summary = facts.get("historical_field_summary")
    if request.get("include_historical_fields") is not True or not isinstance(summary, list):
        return False
    products = request.get("products") or []
    bound = {
        str(item.get("product") or "")
        for item in summary if isinstance(item, dict)
    }
    return all(str(product) in bound for product in products)


def bind_server_evidence(
    evidence: dict[str, Any],
    prepared: dict[str, Any] | None,
) -> dict[str, Any]:
    """Remove client authority fields and attach one server envelope."""
    value = deepcopy(evidence)
    value.pop(REQUEST_FIELD, None)
    for field in _SERVER_GUARDS:
        value.pop(field, None)
    if prepared is None:
        return value
    value["server_evidence"] = {
        "data_availability": deepcopy(prepared["envelope"]),
        "data_provenance": deepcopy(prepared["provenance_envelope"]),
    }
    raw_refs = value.get("evidence_refs", [])
    if not isinstance(raw_refs, list) or not all(
        isinstance(item, str) and item for item in raw_refs
    ):
        raise ValueError("evidence_refs must be a reference array")
    refs = list(raw_refs)
    if prepared["evidence_ref"] not in refs:
        refs.append(prepared["evidence_ref"])
    if prepared["provenance_evidence_ref"] not in refs:
        refs.append(prepared["provenance_evidence_ref"])
    value["evidence_refs"] = refs
    return value


def validate_preflight(
    *,
    row: Any,
    edge: dict[str, Any],
    prepared: dict[str, Any] | None,
) -> None:
    requires_evidence = edge.get("server_action") == SERVER_ACTION
    if requires_evidence and prepared is None:
        raise ValueError(
            "data_contract transition requires frozen Terminal Evidence"
        )
    if prepared is None:
        return
    _validate_edge_request(row=row, edge=edge)
    expected = prepared["expected"]
    actual = {
        "current_node": str(row["current_node"]),
        "latest_trace_id": str(row["latest_trace_id"]),
        "graph_id": str(row["graph_id"]),
        "graph_version": int(row["graph_version"]),
    }
    if actual != expected:
        raise ValueError(
            "data availability preflight is stale; inspect current scope again"
        )


def _validate_edge_request(*, row: Any, edge: dict[str, Any]) -> None:
    if edge.get("server_action") != SERVER_ACTION:
        raise ValueError(
            "data_availability_request is not allowed on this edge"
        )
    if str(edge.get("from_node") or "") != str(row["current_node"]):
        raise ValueError("data availability edge does not leave current node")


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
