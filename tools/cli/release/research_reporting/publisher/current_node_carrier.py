"""Synthetic same-node carrier used for additive report-item publication."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .carrier import MAX_ITEMS


def current_node_carrier(
    carrier: dict[str, Any], *, checkpoint_ref: str, predecessor_ref: str,
    recorded_at: float, submission: dict[str, Any], item_refs: list[str],
) -> dict[str, Any]:
    value = deepcopy(carrier)
    value["checkpoint_ref"] = checkpoint_ref
    value["report_lineage"] = {"status": "linked", "predecessor_checkpoint_ref": predecessor_ref or str(carrier["checkpoint_ref"])}
    base = value["latest_transition"]
    bounded = item_refs[:MAX_ITEMS]
    value["omitted_evidence_count"] += len(item_refs) - len(bounded)
    value["latest_transition"] = {
        "step_ref": checkpoint_ref, "edge_ref": "graph-edge:__current_node_report__",
        "from_node": value["current_node"], "to_node": value["current_node"],
        "created_at": recorded_at, "evidence_refs": bounded, "trial_plan_refs": [],
        "obligation_refs": [], "claim_refs": [], "job_refs": [], "run_refs": [],
        "delta_refs": [], "obligation_changes": [], "claim_changes": [],
        "report_fragment_ref": "report-fragment:sha256:" + submission["fragment_hash"],
        "report_items": [{
            "report_item_ref": "report-item:sha256:" + item["item_hash"],
            "report_requirement_id": item["report_requirement_id"],
            "subject_ref": item["subject_ref"], "content_kind": item["content_kind"],
        } for item in submission["items"]],
    }
    value["job_refs"] = list(base.get("job_refs") or value["job_refs"])
    value["run_refs"] = list(base.get("run_refs") or value["run_refs"])
    return value
