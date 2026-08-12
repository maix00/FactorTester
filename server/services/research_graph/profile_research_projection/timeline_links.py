"""Resolvable object references exposed by one compact timeline step."""

from __future__ import annotations

from typing import Any

from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
)


def object_hrefs(
    *,
    step: dict[str, Any],
    evidence: dict[str, Any],
    instance_id: str,
    branch_id: str,
    trace_id: str,
) -> list[str]:
    refs = [
        *step["obligation_refs"], *step["claim_refs"], *step["delta_refs"],
        *step["run_refs"], *step["run_spec_refs"],
    ]
    plan = evidence.get("trial_plan")
    if isinstance(plan, dict):
        try:
            canonical = canonical_trial_plan(plan)
        except ValueError:
            canonical = None
        if canonical is not None:
            available = {
                "trial-plan:" + canonical["trial_plan_id"],
                "trial-plan:sha256:" + trial_plan_hash(canonical),
            }
            refs.extend(ref for ref in step["trial_plan_refs"] if ref in available)
    evidence_refs = {
        "evidence:" + str(item.get("envelope_hash"))
        for item in _evidence_envelopes(evidence.get("server_evidence"))
    }
    refs.extend(ref for ref in step["evidence_refs"] if ref in evidence_refs)
    return [
        (
            f"/api/research-graph-instances/{instance_id}/branches/"
            f"{branch_id}/cycle-objects/{_object_type(ref)}/"
            f"{ref.split(':', 1)[1]}?trace_id={trace_id}"
        )
        for ref in refs
    ]


def _evidence_envelopes(value: Any):
    if isinstance(value, dict):
        if (
            value.get("schema_version") == 2
            and isinstance(value.get("envelope_hash"), str)
            and isinstance(value.get("evidence_kind"), str)
        ):
            yield value
            return
        for child in value.values():
            yield from _evidence_envelopes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _evidence_envelopes(child)


def _object_type(reference: str) -> str:
    kind = reference.split(":", 1)[0]
    return {
        "trial-plan": "trial_plan",
        "runspec": "run_spec",
    }.get(kind, kind)
