"""Compact, dependency-bound reuse receipts for node entry assessments."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson

from .entry_requirements import checkpoint_obligations, requirement_map


def project_node_entry_resolution(
    *,
    previous_frame: dict[str, Any],
    graph: dict[str, Any],
    target_node: str,
    checkpoint: dict[str, Any] | None,
    scope: dict[str, str],
) -> dict[str, Any]:
    """Build the next node frame, reusing only unchanged accepted inputs."""
    value = previous_frame
    catalog = requirement_map(graph)
    receipts = {
        (
            str(item.get("entry_node") or ""),
            str(item.get("requirement_id") or ""),
        ): item
        for item in value.get("assessment_receipts") or []
        if isinstance(item, dict)
        and item.get("entry_node") and item.get("requirement_id")
    }

    target = next(
        (
            item for item in graph.get("nodes") or []
            if str(item.get("node_id") or "") == target_node
        ),
        None,
    )
    if target is None:
        raise ValueError(f"target Graph lacks {target_node} node")
    declared = [
        str(item) for item in target.get("entry_requirement_refs") or []
    ]
    reused = [
        requirement_id for requirement_id in declared
        if _receipt_matches(
            receipt=receipts.get((target_node, requirement_id)),
            requirement=catalog.get(requirement_id),
            checkpoint=checkpoint,
            scope=scope,
        )
    ]
    unresolved = [
        requirement_id for requirement_id in declared
        if requirement_id not in set(reused)
    ]
    reference_only = [
        requirement_id for requirement_id in unresolved
        if (target_node, requirement_id) in receipts
    ]
    return {
        "schema_version": 1,
        "reason": "node_entry",
        "status": "pending" if unresolved else "resolved",
        "resume_node": target_node,
        "unresolved_requirement_ids": unresolved,
        "resolved_requirement_ids": reused,
        "reused_requirement_ids": reused,
        "reference_only_requirement_ids": reference_only,
        "assessment_receipts": sorted(
            receipts.values(),
            key=lambda item: (item["entry_node"], item["requirement_id"]),
        ),
    }


def record_assessment_receipts(
    *, previous_frame: dict[str, Any], graph: dict[str, Any],
    checkpoint: dict[str, Any] | None, scope: dict[str, str],
    entry_node: str,
    accepted_assessments: list[dict[str, Any]], assessment_trace_ref: str,
) -> dict[str, Any]:
    """Attach compact accepted decisions without changing the resume node."""
    value = deepcopy(previous_frame)
    catalog = requirement_map(graph)
    receipts = {
        (
            str(item.get("entry_node") or ""),
            str(item.get("requirement_id") or ""),
        ): item
        for item in value.get("assessment_receipts") or []
        if isinstance(item, dict)
        and item.get("entry_node") and item.get("requirement_id")
    }
    for assessment in accepted_assessments:
        receipt = _receipt_from_assessment(
            assessment=assessment,
            requirement=catalog.get(
                str(assessment.get("requirement_id") or "")
            ),
            checkpoint=checkpoint,
            scope=scope,
            trace_ref=assessment_trace_ref,
            entry_node=entry_node,
        )
        if receipt is not None:
            receipts[(entry_node, receipt["requirement_id"])] = receipt
    value["assessment_receipts"] = sorted(
        receipts.values(),
        key=lambda item: (item["entry_node"], item["requirement_id"]),
    )
    return value


def _receipt_from_assessment(
    *, assessment: dict[str, Any], requirement: dict[str, Any] | None,
    checkpoint: dict[str, Any] | None, scope: dict[str, str], trace_ref: str,
    entry_node: str,
) -> dict[str, Any] | None:
    effect = assessment.get("entry_effect") or {}
    status = str(effect.get("status") or "")
    if requirement is None or status not in {"pass", "pass_limited"}:
        return None
    requirement_id = str(assessment.get("requirement_id") or "")
    coverage = assessment.get("coverage") or {}
    applicability = assessment.get("applicability") or {}
    resolution = assessment.get("resolution") or {}
    receipt = {
        "entry_node": entry_node,
        "requirement_id": requirement_id,
        "requirement_revision": int(requirement.get("revision") or 0),
        "semantic_hash": str(requirement.get("semantic_hash") or ""),
        "qualification": "eligible" if status == "pass" else "limited",
        "obligation_refs": _refs(coverage.get("obligation_refs")),
        "fact_refs": _refs(applicability.get("fact_refs")),
        "validation_refs": _refs(resolution.get("validation_refs")),
        "assessment_trace_ref": trace_ref,
    }
    receipt["input_hash"] = _input_hash(
        receipt=receipt,
        checkpoint=checkpoint,
        scope=scope,
    )
    receipt["receipt_hash"] = _hash(receipt)
    return receipt


def _receipt_matches(
    *, receipt: dict[str, Any] | None, requirement: dict[str, Any] | None,
    checkpoint: dict[str, Any] | None, scope: dict[str, str],
) -> bool:
    if not isinstance(receipt, dict) or requirement is None:
        return False
    if receipt.get("qualification") not in {"eligible", "limited"}:
        return False
    if (
        int(receipt.get("requirement_revision") or 0)
        != int(requirement.get("revision") or 0)
        or str(receipt.get("semantic_hash") or "")
        != str(requirement.get("semantic_hash") or "")
    ):
        return False
    return str(receipt.get("input_hash") or "") == _input_hash(
        receipt=receipt,
        checkpoint=checkpoint,
        scope=scope,
    )


def _input_hash(
    *, receipt: dict[str, Any], checkpoint: dict[str, Any] | None,
    scope: dict[str, str],
) -> str:
    by_id = {
        str(item.get("obligation_id") or ""): item
        for item in checkpoint_obligations(checkpoint)
    }
    obligations = [
        by_id.get(reference.removeprefix("obligation:"))
        for reference in _refs(receipt.get("obligation_refs"))
    ]
    return _hash({
        "requirement_id": receipt.get("requirement_id"),
        "entry_node": receipt.get("entry_node"),
        "requirement_revision": receipt.get("requirement_revision"),
        "semantic_hash": receipt.get("semantic_hash"),
        "scope": scope,
        "research_contract": {
            "contract_hash": (checkpoint or {}).get("contract_hash"),
            "methodology_hash": (checkpoint or {}).get("methodology_hash"),
        },
        "obligations": obligations,
        "fact_refs": _refs(receipt.get("fact_refs")),
        "validation_refs": _refs(receipt.get("validation_refs")),
    })


def _refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item)))


def _hash(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
