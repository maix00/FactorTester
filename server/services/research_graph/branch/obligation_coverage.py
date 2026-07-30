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
    "node_required", "edge_required", "satisfaction",
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
) -> dict[str, Any]:
    if not isinstance(submitted, dict) or set(submitted) != _FIELDS:
        raise ValueError("obligation coverage submission fields are invalid")
    if submitted.get("schema_version") != 1:
        raise ValueError("obligation coverage schema_version must be 1")
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
    expected_rows = _project(
        _requirement_union(
            graph=graph,
            entry_requirements=compact_entry_requirements(
                graph=graph,
                node=current_node,
                checkpoint=checkpoint,
            ),
            edge_required_ids=edge_required_ids,
        ),
        list((checkpoint or {}).get("obligations") or []),
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
    submitted_rows = _rows(submitted.get("coverage"))
    if submitted_rows != expected_rows:
        raise ValueError(
            "obligation coverage does not match the accepted server projection"
        )
    missing = [
        item["requirement_id"] for item in expected_rows
        if item["edge_required"] and item["satisfaction"] not in _PASSING
    ]
    if missing:
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
    edge_required_ids: set[str],
    node_required_ids: set[str],
) -> list[dict[str, Any]]:
    rows = []
    for requirement in requirements:
        requirement_id = str(requirement["requirement_id"])
        mapped = [
            item for item in obligations
            if requirement_id in {
                str(ref).removeprefix("requirement:")
                for ref in item.get("requirement_refs") or []
            }
        ]
        statuses = [str(item.get("status") or "") for item in mapped]
        rows.append({
            "requirement_id": requirement_id,
            "obligation_refs": [
                f"obligation:{item['obligation_id']}" for item in mapped
            ],
            "obligation_statuses": statuses,
            "node_required": requirement_id in node_required_ids,
            "edge_required": requirement_id in edge_required_ids,
            "satisfaction": _satisfaction(
                statuses,
                edge_required=requirement_id in edge_required_ids,
            ),
        })
    return rows


def _satisfaction(
    statuses: list[str],
    *,
    edge_required: bool,
) -> str:
    values = set(statuses)
    if values & _SATISFIED_STATES:
        return "satisfied"
    if values & _LIMITED_STATES:
        return "limited"
    if not values or values & _PENDING_STATES:
        return "missing" if edge_required else "pending"
    return "missing" if edge_required else "pending"


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
        if (
            not isinstance(refs, list)
            or not all(
                isinstance(ref, str) and ref.startswith("obligation:")
                for ref in refs
            )
            or not isinstance(statuses, list)
            or not all(isinstance(status, str) for status in statuses)
            or not isinstance(item.get("edge_required"), bool)
            or not isinstance(item.get("node_required"), bool)
            or item.get("satisfaction") not in {
                "satisfied", "limited", "missing", "pending",
            }
        ):
            raise ValueError("obligation coverage row is invalid")
        result.append(deepcopy(item))
    return result


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()
