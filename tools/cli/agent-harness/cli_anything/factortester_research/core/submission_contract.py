"""Node-local machine contract for one Research Cycle transition.

This module deliberately describes transport protocol, not research semantics.
The server remains authoritative; the contract lets an Agent construct and
validate the next request without guessing field names from a Skill document.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


SCHEMA_VERSION = 2
MAX_TRANSITION_BYTES = 64 * 1024
MAX_REPORT_SUBMISSION_BYTES = 16 * 1024
MAX_TRIAL_PLAN_BYTES = 8 * 1024
MAX_EVIDENCE_ACTION_BYTES = 1024
_OBLIGATION_FIELDS = {
    "obligation_refs",
    "primary_obligation_ref",
    "secondary_obligation_refs",
}


def build_cycle_submission_contract(
    packet: dict[str, Any],
    *,
    edge_id: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one compact, reusable-ref-aware submission contract."""
    edges = {
        str(item.get("edge_id") or ""): item
        for item in packet.get("candidate_edges") or []
        if isinstance(item, dict)
    }
    if edge_id not in edges:
        raise ValueError("edge_id is not a current candidate edge")
    edge = edges[edge_id]
    obligations = [
        {
            "obligation_id": str(item.get("obligation_id") or ""),
            "question_summary": str(item.get("question_summary") or ""),
        }
        for item in packet.get("current_obligations") or []
        if isinstance(item, dict) and item.get("obligation_id")
    ]
    requirements = [
        {
            "requirement_id": str(item.get("requirement_id") or ""),
            "title_zh": str(item.get("title_zh") or ""),
            "mapped_obligation_refs": list(
                item.get("mapped_obligation_refs") or []
            ),
        }
        for item in packet.get("entry_requirements") or []
        if isinstance(item, dict)
    ]
    report_tasks = [
        item
        for item in (
            (packet.get("report_packet") or {}).get("required_tasks") or []
        )
        if isinstance(item, dict)
        and str(item.get("edge_id") or "") in {"node", edge_id}
    ]
    value = {
        "schema_version": SCHEMA_VERSION,
        "operation": "research_graph.cycle_advance",
        "context_ref": str(packet.get("context_ref") or ""),
        "graph_ref": str(packet.get("graph") or ""),
        "branch": {
            key: str((packet.get("branch") or {}).get(key) or "")
            for key in ("instance_id", "branch_id")
        },
        "transition": {
            "edge_id": edge_id,
            "from_node": str((packet.get("node") or {}).get("node_id") or ""),
            "to_node": str(edge.get("to_node") or ""),
            "required_research_evidence": list(
                edge.get("required_research_evidence") or []
            ),
            "required_transition_facts": list(
                edge.get("required_transition_facts") or []
            ),
            "review_requirement": str(
                edge.get("review_requirement") or "none"
            ),
        },
        "report_packet": {
            "required_tasks": report_tasks,
            "completion_rule": str(
                (packet.get("report_packet") or {}).get("completion_rule") or ""
            ),
            "data_policy": "Graph stores references and contracts only",
        },
        "reusable_refs": {
            "obligations": obligations,
            "requirements": requirements,
            "changed_evidence_refs": [
                str(item) for item in packet.get("changed_refs") or []
            ],
            "current_trial_plan_hash": (
                (packet.get("candidate_trial_frontier") or {}).get(
                    "current_trial_plan_hash"
                )
            ),
        },
        "wire_rules": {
            "trial_plan_obligation_fields": (
                "use bare obligation_id values; never obligation:<id> or "
                "research-cycle-object:obligation:<id>"
            ),
            "reviewer_task_ref": (
                "research-cycle-adjudication:<proposal_hash> for "
                "adjudication; research-cycle-closure:<proposal_hash> "
                "for closure"
            ),
            "report_submission": (
                "schema_version, fragment_hash and exact unique items only; "
                "each item has report_requirement_id, subject_ref, "
                "content_kind and item_hash"
            ),
            "report_document": (
                "local generic report document; attach report_requirement "
                "chips before research graphs node advance"
            ),
            "obligation_coverage": (
                "node advance reads branches/<branch>/obligations.json, "
                "replaces assessment coverage refs, and injects the "
                "hash-bound coverage submission; the Agent does not handwrite it"
            ),
            "evidence_envelope": (
                "schema_version 2; factual evidence cannot contain decision "
                "or obligation-delta fields"
            ),
            "agent_identity": (
                "provider, model and Skill identity are not protocol fields"
            ),
        },
        "request_schema": {
            "transport_required": [
                "instance_id", "branch_id", "edge_id", "evidence",
            ],
            "transport_optional": ["acting_profile_ref"],
            "evidence_cli_injected": [
                "obligation_coverage_submission",
            ],
            "evidence_required": [
                "agent_invocation_ids", "evidence_refs",
                "entry_requirement_assessments", "research_cycle",
                "report_submission", "obligation_coverage_submission",
            ],
            "evidence_server_owned": [
                "server_evidence", "report_lineage",
                "entry_resolution_delta",
                "entry_requirement_assessments_ref",
                "entry_requirement_assessment_receipts",
            ],
            "reference_grammar": {
                "trial_plan_obligation": "<bare-obligation-id>",
                "evidence": "evidence:<id>",
                "requirement": "requirement:<requirement-id>",
                "reviewer_adjudication_task": (
                    "research-cycle-adjudication:<proposal-sha256>"
                ),
                "reviewer_closure_task": (
                    "research-cycle-closure:<proposal-sha256>"
                ),
            },
            "report_requirements": {
                "node_refs": list(
                    packet.get("node_report_requirement_refs") or []
                ),
                "submission_fields": [
                    "schema_version", "fragment_hash", "items",
                ],
                "item_fields": [
                    "report_requirement_id", "subject_ref",
                    "content_kind", "item_hash",
                ],
            },
        },
        "budgets": {
            "transition_evidence_bytes": MAX_TRANSITION_BYTES,
            "report_submission_bytes": MAX_REPORT_SUBMISSION_BYTES,
            "trial_plan_bytes": MAX_TRIAL_PLAN_BYTES,
            "trial_plan_evidence_action_bytes": MAX_EVIDENCE_ACTION_BYTES,
        },
        "repair_hints": {
            "stale_contract": (
                "rerun research graphs node advance so it rebuilds the "
                "current contract; never edit context_ref or contract_hash"
            ),
            "unknown_field": (
                "remove fields absent from request_schema; server-owned "
                "fields are returned as receipts, not submitted"
            ),
            "obligation_ref": (
                "copy obligation_id from reusable_refs.obligations without "
                "an obligation: prefix"
            ),
            "reviewer_task_ref": (
                "prepare again with --evidence-file after proposal_hash is "
                "known, then reserve the exact returned task_ref"
            ),
            "report_coverage": (
                "generate report items for every current report requirement; "
                "do not reuse another node or edge's subject_ref"
            ),
        },
        "evidence_template": {
            "agent_invocation_ids": [],
            "evidence_refs": [],
            "entry_requirement_assessments": [],
            "research_cycle": {"schema_version": 1, "events": []},
            "report_submission": {
                "schema_version": 1,
                "fragment_hash": "<sha256>",
                "items": [],
            },
            "obligation_coverage_submission": {
                "source": "branches/<branch_id>/obligations.json",
                "agent_writes": False,
            },
        },
    }
    target_plan = packet.get("target_capability_plan")
    if isinstance(target_plan, dict):
        value["target_capability_plan"] = target_plan
    if evidence is not None:
        value["derived_requirements"] = _derived_requirements(evidence)
    value["contract_hash"] = _contract_hash(value)
    return value


def validate_against_cycle_submission_contract(
    evidence: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Catch common wire mismatches before the real backend call."""
    if contract.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported cycle submission contract")
    allowed_obligations = {
        str(item.get("obligation_id") or "")
        for item in (
            (contract.get("reusable_refs") or {}).get("obligations") or []
        )
    }
    used_obligations = _obligation_values(evidence.get("trial_plan"))
    prefixed = sorted(
        value for value in used_obligations
        if value.startswith(("obligation:", "research-cycle-object:"))
    )
    if prefixed:
        raise ValueError(
            "TrialPlan obligation fields require bare obligation_id: "
            + ", ".join(prefixed)
        )
    unknown = sorted(set(used_obligations) - allowed_obligations)
    if unknown:
        raise ValueError(
            "TrialPlan references non-current obligations: "
            + ", ".join(unknown)
        )
    size = len(json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode())
    maximum = int(
        (contract.get("budgets") or {}).get(
            "transition_evidence_bytes"
        ) or MAX_TRANSITION_BYTES
    )
    if size > maximum:
        raise ValueError(
            f"transition evidence exceeds {maximum} bytes: {size}"
        )
    requirements = _derived_requirements(evidence)
    return {
        "contract_valid": True,
        "contract_hash": _validated_contract_hash(contract),
        "transition_evidence_bytes": size,
        "obligation_ids_checked": sorted(set(used_obligations)),
        **requirements,
    }


def validate_contract_for_current_packet(
    contract: dict[str, Any],
    packet: dict[str, Any],
    *,
    edge_id: str,
) -> dict[str, Any]:
    """Reject a stale or edited contract before submitting any mutation."""
    contract_hash = _validated_contract_hash(contract)
    expected = build_cycle_submission_contract(packet, edge_id=edge_id)
    for field in ("context_ref", "graph_ref", "branch", "transition"):
        if contract.get(field) != expected.get(field):
            raise ValueError(
                "submission contract is stale for the current branch; "
                "rerun research graphs node advance"
            )
    return {
        "contract_current": True,
        "contract_hash": contract_hash,
        "context_ref": str(contract.get("context_ref") or ""),
    }


def _obligation_values(value: Any, *, field: str = "") -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _OBLIGATION_FIELDS:
                if isinstance(item, str):
                    values.append(item)
                elif isinstance(item, list):
                    values.extend(
                        str(entry) for entry in item
                        if isinstance(entry, str)
                    )
                continue
            values.extend(_obligation_values(item, field=key))
    elif isinstance(value, list):
        for item in value:
            values.extend(_obligation_values(item, field=field))
    return values


def _derived_requirements(evidence: dict[str, Any]) -> dict[str, Any]:
    reviewer_task_refs: list[str] = []
    for event in (
        (evidence.get("research_cycle") or {}).get("events") or []
    ):
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "")
        proposal = event.get("proposal") or {}
        proposal_hash = str(proposal.get("proposal_hash") or "")
        if not proposal_hash:
            continue
        if event_type == "adjudication_proposed":
            reviewer_task_refs.append(
                f"research-cycle-adjudication:{proposal_hash}"
            )
        elif event_type == "closure_proposed":
            reviewer_task_refs.append(
                f"research-cycle-closure:{proposal_hash}"
            )
    return {
        "required_reviewer_task_refs": reviewer_task_refs,
        "required_agent_invocation_ids": list(dict.fromkeys(
            str(item)
            for item in evidence.get("agent_invocation_ids") or []
            if isinstance(item, str) and item
        )),
    }


def _contract_hash(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items()
               if key != "contract_hash"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validated_contract_hash(contract: dict[str, Any]) -> str:
    supplied = str(contract.get("contract_hash") or "")
    expected = _contract_hash(contract)
    if supplied != expected:
        raise ValueError(
            "submission contract hash mismatch; rerun research graphs "
            "node advance"
        )
    return expected
