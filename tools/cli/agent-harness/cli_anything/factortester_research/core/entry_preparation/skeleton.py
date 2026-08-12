"""Editable authoring skeletons for selected current-node requirements."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_EDIT = "__EDIT__"


def build_entry_assessment_skeleton(
    *,
    next_packet: dict[str, Any],
    requirement_details: dict[str, dict[str, Any]],
    factor_facts: dict[str, Any],
    selected_requirement_ids: list[str],
) -> dict[str, Any]:
    """Build only the explicitly selected part of the current entry gate."""
    if not selected_requirement_ids:
        raise ValueError("at least one requirement ID must be selected")
    selected = list(dict.fromkeys(selected_requirement_ids))
    current = {
        str(item.get("requirement_id") or ""): item
        for item in next_packet.get("entry_requirements") or []
        if isinstance(item, dict)
    }
    inactive = [item for item in selected if item not in current]
    if inactive:
        raise ValueError(
            "requirement is not active at the current node: "
            + ", ".join(inactive)
        )
    missing = [item for item in selected if item not in requirement_details]
    if missing:
        raise ValueError(
            "selected requirement detail is missing: " + ", ".join(missing)
        )
    node = next_packet.get("node") or {}
    branch = next_packet.get("branch") or {}
    assessments = [
        _assessment_skeleton(
            alias=current[requirement_id],
            detail=requirement_details[requirement_id],
        )
        for requirement_id in selected
    ]
    return {
        "schema_version": 1,
        "context": {
            "graph_ref": str(next_packet.get("graph") or ""),
            "context_ref": str(next_packet.get("context_ref") or ""),
            "instance_id": str(branch.get("instance_id") or ""),
            "branch_id": str(branch.get("branch_id") or ""),
            "node_id": str(node.get("node_id") or ""),
        },
        "factor_facts": deepcopy(factor_facts),
        "selected_requirement_ids": selected,
        "editing_contract": {
            "applicability_statuses": [
                "applicable", "not_applicable", "undetermined",
            ],
            "coverage_decisions": [
                "create_new", "map_existing", "no_material_issue",
            ],
            "resolution_routes": [
                "existing_evidence", "cli_evidence", "trial",
                "capability_gap", "bounded_unknown",
            ],
            "reuse_statuses": [
                "none", "exact", "partial", "stale", "incompatible",
            ],
            "entry_effect_statuses": [
                "pass", "pass_limited", "blocked", "deferred",
            ],
            "first_action_kinds": [
                "cli_evidence", "trial_candidate", "capability_gap",
                "bounded_unknown", "none",
            ],
        },
        "assessments": assessments,
    }


def _assessment_skeleton(
    *,
    alias: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    requirement = detail.get("requirement")
    if not isinstance(requirement, dict):
        raise ValueError("requirement detail is missing its contract")
    requirement_id = str(requirement.get("requirement_id") or "")
    if requirement_id != str(alias.get("requirement_id") or ""):
        raise ValueError(f"requirement detail identity mismatch: {requirement_id}")
    reports = detail.get("report_requirements") or []
    if len(reports) != 1 or not isinstance(reports[0], dict):
        raise ValueError(
            f"requirement needs exactly one report binding: {requirement_id}"
        )
    mapped = [
        {
            "obligation_ref": (
                "obligation:" + str(item.get("obligation_id") or "")
            ),
            "status": str(item.get("status") or ""),
            "question_summary": str(item.get("question_summary") or ""),
            "detail_ref": str(item.get("detail_ref") or ""),
        }
        for item in detail.get("mapped_obligations") or []
        if isinstance(item, dict)
    ]
    report = reports[0]
    return {
        "requirement_id": requirement_id,
        "requirement_revision": int(requirement.get("revision") or 0),
        "title_zh": str(alias.get("title_zh") or ""),
        "question_zh": str(requirement.get("question_zh") or ""),
        "gate_policy": str(requirement.get("gate_policy") or ""),
        "guidance": {
            "industry_principle_zh": str(
                requirement.get("industry_principle_zh") or ""
            ),
            "industry_basis_refs": list(
                requirement.get("industry_basis_refs") or []
            ),
            "evidence_expected_zh": list(
                requirement.get("evidence_expected_zh") or []
            ),
            "not_sufficient_zh": list(
                requirement.get("not_sufficient_zh") or []
            ),
        },
        "existing_obligations": mapped,
        "applicability": {
            "status": _EDIT,
            "reason_zh": _EDIT,
            "fact_refs": [],
        },
        "coverage": {
            "decision": _EDIT,
            "obligation_refs": [
                item["obligation_ref"] for item in mapped
            ],
        },
        "resolution": {
            "route": _EDIT,
            "reuse_status": "none",
            "validation_refs": [],
        },
        "entry_effect": {
            "status": _EDIT,
            "limitation_refs": [],
        },
        "first_resolution_action": {
            "kind": _EDIT,
            "action_ref": "",
            "trial_ref": "",
            "description_zh": _EDIT,
        },
        "report": {
            "report_requirement_id": str(
                report.get("report_requirement_id") or ""
            ),
            "method_ref": str(report.get("method_ref") or ""),
            "subject_ref": "__AUTO_FROM_COVERAGE__",
            "content_kind": "list",
            "content_zh": [_EDIT],
            "fact_refs": [],
        },
    }
