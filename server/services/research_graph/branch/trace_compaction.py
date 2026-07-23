"""Compact receipts for large, immutable transition audit documents."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from server.services.research_graph.protocol import json_hash
from server.services.research_graph.graph_objects import (
    prepare_graph_object,
)


ENTRY_ASSESSMENT_OBJECT_KIND = "entry_assessment_document"
RESEARCH_CYCLE_EVENTS_OBJECT_KIND = "research_cycle_event_bundle"


def compact_transition_trace(
    *,
    owner: str,
    instance_id: str,
    evidence: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Move repeated cold documents behind exact refs after validation."""
    value = deepcopy(evidence)
    objects: list[dict[str, Any]] = []
    assessments = value.pop("entry_requirement_assessments", None)
    if isinstance(assessments, list) and assessments:
        prepared = prepare_graph_object(
            owner,
            instance_id,
            ENTRY_ASSESSMENT_OBJECT_KIND,
            {
                "schema_version": 1,
                "assessments": assessments,
            },
        )
        objects.append(prepared)
        value["entry_requirement_assessments_ref"] = prepared[
            "object_ref"
        ]
        value["entry_requirement_assessment_receipts"] = (
            compact_entry_assessment_receipts(assessments)
        )
    cycle = value.get("research_cycle")
    if isinstance(cycle, dict):
        events = cycle.get("events")
        if isinstance(events, list) and events:
            prepared = prepare_graph_object(
                owner,
                instance_id,
                RESEARCH_CYCLE_EVENTS_OBJECT_KIND,
                {
                    "schema_version": 1,
                    "events": events,
                },
            )
            objects.append(prepared)
            compact_cycle = deepcopy(cycle)
            compact_cycle.pop("events", None)
            compact_cycle["events_ref"] = prepared["object_ref"]
            compact_cycle["event_receipts"] = (
                compact_research_cycle_event_receipts(events)
            )
            value["research_cycle"] = compact_cycle
    delta = value.get("entry_resolution_delta")
    if isinstance(delta, dict):
        value["entry_resolution_delta"] = (
            compact_entry_resolution_delta(delta)
        )
    return value, objects


def compact_entry_assessment_receipts(
    assessments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Retain decision identity while moving explanatory bodies cold."""
    receipts = []
    for item in assessments:
        applicability = item.get("applicability") or {}
        coverage = item.get("coverage") or {}
        effect = item.get("entry_effect") or {}
        receipts.append({
            "requirement_id": str(item.get("requirement_id") or ""),
            "requirement_revision": int(
                item.get("requirement_revision") or 0
            ),
            "assessment_hash": json_hash(item),
            "applicability_status": str(
                applicability.get("status") or ""
            ),
            "coverage_decision": str(coverage.get("decision") or ""),
            "entry_effect_status": str(effect.get("status") or ""),
            "obligation_refs": _refs(coverage.get("obligation_refs")),
            "limitation_refs": _refs(effect.get("limitation_refs")),
        })
    return receipts


def compact_entry_resolution_delta(
    delta: dict[str, Any],
) -> dict[str, Any]:
    """Drop repeated display text while preserving every status transition."""
    value = deepcopy(delta)
    items = value.get("items")
    if isinstance(items, list):
        value["items"] = [{
            key: deepcopy(item[key])
            for key in (
                "requirement_id",
                "change_kind",
                "resolution_status",
            )
            if key in item
        } for item in items if isinstance(item, dict)]
    return value


def compact_research_cycle_event_receipts(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project replay-independent audit indexes from validated full events."""
    return [
        _event_receipt(event)
        for event in events
        if isinstance(event, dict)
    ]


def _event_receipt(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("event_type") or "")
    if event_type in {"adjudication_proposed", "closure_proposed"}:
        proposal = event.get("proposal") or {}
        value = {
            "event_type": event_type,
            "proposal_id": str(proposal.get("proposal_id") or ""),
            "proposal_hash": _object_hash(proposal, "proposal_hash"),
        }
        if event_type == "adjudication_proposed":
            value.update({
                "recommended_action": str(
                    proposal.get("recommended_action") or ""
                ),
                "claim_deltas": _compact_deltas(
                    proposal.get("claim_evidence_delta"),
                    identifier="claim_id",
                ),
                "obligation_deltas": _compact_deltas(
                    proposal.get("obligation_delta"),
                    identifier="obligation_id",
                ),
            })
        else:
            value["disposition"] = str(
                proposal.get("disposition") or ""
            )
        return value
    if event_type in {"adjudication_decided", "closure_decided"}:
        decision = event.get("decision") or {}
        return {
            "event_type": event_type,
            "decision_id": str(decision.get("decision_id") or ""),
            "proposal_hash": str(decision.get("proposal_hash") or ""),
            "disposition": str(decision.get("disposition") or ""),
            "authority_class": str(
                decision.get("authority_class") or ""
            ),
        }
    return {
        key: deepcopy(event[key])
        for key in ("event_type", "from_hash", "to_hash", "reason")
        if key in event
    }


def _compact_deltas(
    value: Any,
    *,
    identifier: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        delta: dict[str, Any] = {
            key: str(item.get(key) or "")
            for key in (identifier, "from_state", "to_state")
        }
        for key in (
            "from_requirement_refs",
            "to_requirement_refs",
        ):
            if key in item:
                delta[key] = _refs(item.get(key))
        result.append(delta)
    return result


def _object_hash(value: Any, field: str) -> str:
    if not isinstance(value, dict):
        return ""
    declared = str(value.get(field) or "")
    if declared:
        return declared.removeprefix("sha256:")
    return json_hash(value)


def _refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(
        str(item) for item in value if isinstance(item, str) and item
    ))
