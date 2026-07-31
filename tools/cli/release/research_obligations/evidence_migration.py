"""One-time ledger/report upgrade for fragment-bound EvidenceUse."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .ledger import append_event, canonicalize_ledger
from .projection import project_requirement_coverage
from .reporting import obligation_change_operations


def migrate_ledger_evidence_v2(
    ledger: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Upgrade historical snapshots and return report replacement operations."""
    value = deepcopy(ledger)
    replacements: list[dict[str, Any]] = []
    migrated_events = 0
    for event in value["history"]:
        if event.get("event_type") not in {
            "obligation_change", "obligation_split",
        }:
            continue
        event.setdefault("evidence_use_delta", [])
        event.setdefault("changed_evidence_use_ids", [])
        event.setdefault("evidence_uses_snapshot", [])
        event["coverage_snapshot"] = _upgrade_coverage(
            event.get("coverage_snapshot") or [],
            event.get("obligations_snapshot") or [],
            event.get("evidence_uses_snapshot") or [],
        )
        historical_ids = event.get("report_components")
        operations, component_ids = obligation_change_operations(
            event=event,
            parent_id="migration-parent",
            component_ids=historical_ids,
        )
        if historical_ids != component_ids:
            raise ValueError(
                "historical obligation report component identity is invalid"
            )
        for operation in operations:
            replacement = deepcopy(operation)
            replacement["op"] = "replace"
            replacement.pop("parent_id", None)
            replacements.append(replacement)
        migrated_events += 1
    projection = value["current_projection"]
    projection["requirement_coverage"] = _upgrade_coverage(
        projection.get("requirement_coverage") or [],
        projection.get("obligations") or [],
        projection.get("evidence_uses") or [],
    )
    value = canonicalize_ledger(value)
    value = append_event(
        value,
        event_type="evidence_migrated",
        payload={
            "migration": "fragment-bound-evidence-use-v2",
            "migrated_obligation_event_count": migrated_events,
            "report_replacement_count": len(replacements),
            "legacy_evidence_disposition": "unverifiable_fragment",
        },
    )
    return value, replacements


def _upgrade_coverage(
    rows: list[dict[str, Any]],
    obligations: list[dict[str, Any]],
    evidence_uses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requirements = [{
        "requirement_id": str(row["requirement_id"]),
        "title_zh": str(row.get("description") or ""),
        "accepted_states": list(
            row.get("accepted_states")
            or ["bounded", "serviced", "discharged"]
        ),
        "minimum_qualification": str(
            row.get("minimum_qualification") or "limited"
        ),
    } for row in rows]
    return project_requirement_coverage(
        requirements=requirements,
        obligations=obligations,
        evidence_uses=evidence_uses,
        changed_obligation_refs={
            str(reference)
            for row in rows if row.get("changed")
            for reference in row.get("obligation_refs") or []
        },
        edge_required_ids={
            str(row["requirement_id"])
            for row in rows if row.get("edge_required")
        },
        node_required_ids={
            str(row["requirement_id"])
            for row in rows if row.get("node_required", True)
        },
        title_overrides={
            str(row["requirement_id"]): str(row.get("description") or "")
            for row in rows
        },
        enforce_evidence=False,
    )
