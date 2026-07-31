"""Server-authoritative validation of one branch obligation coverage claim."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from server.services.research_graph.branch.entry_requirements import (
    compact_entry_requirements,
)
from server.services.research_graph.evidence_admission import (
    validate_branch_evidence_uses,
)
from tools.cli.release.research_obligations.projection import (
    project_requirement_coverage,
)
from tools.cli.release.research_obligations.scope_revalidation import (
    current_edge_scope,
)


_PASSING = {"satisfied", "limited"}
_LIMITED_STATES = {"bounded", "serviced"}
_SATISFIED_STATES = {"discharged"}
_PENDING_STATES = {"open", "reopened"}
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_FIELDS = {
    "schema_version", "branch_ref", "graph_ref", "current_node",
    "context_ref", "checkpoint_ref", "edge_id", "target_node",
    "coverage", "coverage_hash", "prepared_git_commit",
}
_HASH_FIELDS = _FIELDS - {"coverage_hash", "prepared_git_commit"}
_ROW_FIELDS = {
    "requirement_id", "obligation_refs", "obligation_statuses",
    "evidence_uses", "scope_revalidation", "node_required",
    "edge_required", "satisfaction",
}


def validate_obligation_coverage_submission(
    *,
    submitted: Any,
    instance_id: str,
    branch_id: str,
    graph: dict[str, Any],
    current_node: dict[str, Any],
    edge: dict[str, Any],
    checkpoint: dict[str, Any] | None,
    expected_checkpoint_ref: str,
    conn=None,
    owner: str = "",
    workspace_id: str = "",
    allow_missing: bool = False,
) -> dict[str, Any]:
    if not isinstance(submitted, dict) or set(submitted) != _FIELDS:
        raise ValueError("obligation coverage submission fields are invalid")
    if submitted.get("schema_version") != 2:
        raise ValueError("obligation coverage schema_version must be 2")
    expected_identity = {
        "branch_ref": f"graph-branch:{instance_id}:{branch_id}",
        "graph_ref": f"{graph['graph_id']}@v{graph['version']}",
        "current_node": str(current_node.get("node_id") or ""),
        "checkpoint_ref": expected_checkpoint_ref,
        "edge_id": str(edge.get("edge_id") or ""),
        "target_node": str(edge.get("to_node") or ""),
    }
    for field, expected in expected_identity.items():
        if submitted.get(field) != expected:
            raise ValueError(f"obligation coverage {field} is stale")
    context_ref = str(submitted.get("context_ref") or "")
    if not context_ref.startswith("sha256:") or len(context_ref) != 71:
        raise ValueError("obligation coverage context_ref is invalid")
    commit = str(submitted.get("prepared_git_commit") or "")
    if _COMMIT.fullmatch(commit) is None:
        raise ValueError("obligation coverage prepared_git_commit is invalid")
    edge_required_ids = _edge_requirement_ids(graph, edge)
    requirements = _requirement_union(
            graph=graph,
            entry_requirements=compact_entry_requirements(
                graph=graph,
                node=current_node,
                checkpoint=checkpoint,
            ),
            edge_required_ids=edge_required_ids,
        )
    required_scope = current_edge_scope(checkpoint)
    for requirement in requirements:
        requirement["scope_policy"] = {
            "mode": "current_claim_scope",
            "revalidate_on_advance": True,
            "required_scope": required_scope,
            "missing_scope_is_bypassable": False,
        }
    submitted_rows = _rows(submitted.get("coverage"))
    submitted_uses = _unique_evidence_uses(submitted_rows)
    if submitted_uses:
        if conn is None or not owner or not workspace_id:
            raise ValueError(
                "obligation coverage EvidenceUse authority is unavailable"
            )
        submitted_uses = validate_branch_evidence_uses(
            conn,
            owner=owner,
            workspace_id=workspace_id,
            instance_id=instance_id,
            branch_id=branch_id,
            evidence_uses=submitted_uses,
        )
    expected_rows = _project(
        requirements,
        _obligations_with_claim_scopes(checkpoint),
        evidence_uses=submitted_uses,
        edge_required_ids=edge_required_ids,
        node_required_ids={
            str(item.get("requirement_id") or "")
            for item in compact_entry_requirements(
                graph=graph,
                node=current_node,
                checkpoint=checkpoint,
            )
        },
    )
    if submitted_rows != expected_rows:
        raise ValueError(
            "obligation coverage does not match the accepted server projection"
        )
    scope_mismatch = [
        item["requirement_id"] for item in expected_rows
        if (
            item["edge_required"]
            and item["evidence_uses"]
            and item["scope_revalidation"]["status"] != "matched"
        )
    ]
    if scope_mismatch:
        raise ValueError(
            "selected edge has stale or unbound obligation scope: "
            + ", ".join(scope_mismatch)
        )
    missing = [
        item["requirement_id"] for item in expected_rows
        if item["edge_required"] and item["satisfaction"] not in _PASSING
    ]
    if missing and not allow_missing:
        raise ValueError(
            "selected edge has missing obligation coverage: "
            + ", ".join(missing)
        )
    hashed = {
        field: deepcopy(submitted[field])
        for field in _HASH_FIELDS
    }
    expected_hash = "sha256:" + hashlib.sha256(
        _canonical_bytes(hashed)
    ).hexdigest()
    if submitted.get("coverage_hash") != expected_hash:
        raise ValueError("obligation coverage hash mismatch")
    return {
        **hashed,
        "coverage_hash": expected_hash,
        "prepared_git_commit": commit,
    }


def _project(
    requirements: list[dict[str, Any]],
    obligations: list[dict[str, Any]],
    *,
    evidence_uses: list[dict[str, Any]],
    edge_required_ids: set[str],
    node_required_ids: set[str],
) -> list[dict[str, Any]]:
    projected = project_requirement_coverage(
        requirements=requirements,
        obligations=obligations,
        evidence_uses=evidence_uses,
        edge_required_ids=edge_required_ids,
        node_required_ids=node_required_ids,
        enforce_evidence=True,
    )
    return [{field: deepcopy(item[field]) for field in _ROW_FIELDS}
            for item in projected]


def _edge_requirement_ids(
    graph: dict[str, Any],
    edge: dict[str, Any],
) -> set[str]:
    explicit = {
        str(item).removeprefix("requirement:")
        for item in edge.get("obligation_requirement_refs") or []
    }
    if explicit:
        return explicit
    reports = {
        str(item.get("report_requirement_id") or ""): item
        for item in graph.get("report_requirements") or []
        if isinstance(item, dict)
    }
    return {
        str(report.get("requirement_ref") or "")
        for report_id in edge.get("report_requirement_refs") or []
        for report in [reports.get(str(report_id)) or {}]
        if report.get("requirement_ref")
    }


def _requirement_union(
    *,
    graph: dict[str, Any],
    entry_requirements: list[dict[str, Any]],
    edge_required_ids: set[str],
) -> list[dict[str, Any]]:
    values = list(entry_requirements)
    present = {
        str(item.get("requirement_id") or "") for item in values
    }
    catalog = {
        str(item.get("requirement_id") or ""): item
        for item in (
            (graph.get("requirement_catalog") or {}).get("requirements")
            or []
        )
        if isinstance(item, dict)
    }
    for requirement_id in sorted(edge_required_ids - present):
        requirement = catalog.get(requirement_id)
        if requirement is None:
            raise ValueError(
                "edge obligation requirement is absent from the catalog: "
                + requirement_id
            )
        values.append({
            "requirement_id": requirement_id,
            "title_zh": str(requirement.get("title_zh") or ""),
            "accepted_states": list(
                requirement.get("accepted_states")
                or ["bounded", "serviced", "discharged"]
            ),
            "minimum_qualification": str(
                requirement.get("minimum_qualification") or "limited"
            ),
        })
    return values


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("obligation coverage must be an array")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != _ROW_FIELDS:
            raise ValueError("obligation coverage row fields are invalid")
        refs = item.get("obligation_refs")
        statuses = item.get("obligation_statuses")
        evidence_uses = item.get("evidence_uses")
        scope = item.get("scope_revalidation")
        if (
            not isinstance(refs, list)
            or not all(
                isinstance(ref, str) and ref.startswith("obligation:")
                for ref in refs
            )
            or not isinstance(statuses, list)
            or not all(isinstance(status, str) for status in statuses)
            or not isinstance(evidence_uses, list)
            or any(not isinstance(use, dict) for use in evidence_uses)
            or not isinstance(scope, dict)
            or scope.get("status") not in {"matched", "missing"}
            or not isinstance(item.get("edge_required"), bool)
            or not isinstance(item.get("node_required"), bool)
            or item.get("satisfaction") not in {
                "satisfied", "limited", "missing", "pending",
            }
        ):
            raise ValueError("obligation coverage row is invalid")
        result.append(deepcopy(item))
    return result


def _unique_evidence_uses(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for row in rows:
        for use in row.get("evidence_uses") or []:
            use_id = str(use.get("use_id") or "")
            if not use_id:
                raise ValueError("obligation coverage EvidenceUse lacks use_id")
            existing = values.get(use_id)
            if existing is not None and existing != use:
                raise ValueError("obligation coverage EvidenceUse identity drift")
            values[use_id] = deepcopy(use)
    return list(values.values())


def _obligations_with_claim_scopes(
    checkpoint: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    value = checkpoint or {}
    claims = {
        str(item.get("claim_id") or ""): item
        for item in value.get("claims") or []
        if isinstance(item, dict) and item.get("claim_id")
    }
    result = []
    for raw in value.get("obligations") or []:
        if not isinstance(raw, dict):
            continue
        item = deepcopy(raw)
        item["claim_scopes"] = [
            {
                "claim_id": claim_id,
                "scope": deepcopy(claims[claim_id].get("scope") or {}),
                "evidence_state": str(
                    claims[claim_id].get("evidence_state") or ""
                ),
            }
            for claim_id in item.get("claim_ids") or []
            if claim_id in claims
        ]
        result.append(item)
    return result


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()
