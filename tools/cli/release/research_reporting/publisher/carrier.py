"""Validate the bounded, source-free checkpoint Carrier contract."""

from __future__ import annotations

from copy import deepcopy
import json
import math
import re
from typing import Any

from .identity import (
    bounded_text,
    chinese_text,
    reference,
    reject_prohibited,
    safe_id,
)


MAX_CARRIER_BYTES = 64 * 1024
MAX_ITEMS = 16
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CARRIER_FIELDS = {
    "schema_version", "workspace_ref", "work_package_ref", "branch_ref",
    "graph_ref", "checkpoint_ref", "research_cycle_ref", "title",
    "product_group", "current_node", "status", "decision_contract_hash",
    "methodology_hash", "trial_plan_hash", "evidence_refs",
    "omitted_evidence_count", "job_refs", "run_refs", "claims",
    "open_obligations", "closure", "report_lineage",
    "latest_transition",
}
_TRANSITION_FIELDS = {
    "step_ref", "edge_ref", "from_node", "to_node", "created_at",
    "evidence_refs", "trial_plan_refs", "obligation_refs", "claim_refs",
    "job_refs", "run_refs", "obligation_changes", "claim_changes",
    "delta_refs", "entry_resolution", "report_fragment_ref", "report_items",
}
_TRANSITION_OPTIONAL_FIELDS = {
    "delta_refs", "entry_resolution", "report_fragment_ref", "report_items",
}
_REPORT_ITEM_FIELDS = {
    "report_item_ref", "report_requirement_id", "subject_ref", "content_kind",
}
_ENTRY_RESOLUTION_FIELDS = {
    "reason", "assessed_requirement_ids", "reused_requirement_ids",
    "reference_only_requirement_ids", "unresolved_requirement_ids", "items",
    "resume_node",
}
_ENTRY_RESOLUTION_ITEM_FIELDS = {
    "requirement_id", "title_zh", "assessed", "change_kind",
    "resolution_status",
}
_ENTRY_RESOLUTION_STATUSES = {
    "assessed_pass", "assessed_limited", "reused", "reference_only",
    "unresolved", "not_applicable",
}
_ENTRY_RESOLUTION_CHANGE_KINDS = {
    "added", "revised", "metadata_only", "unchanged",
}
_CLAIM_FIELDS = {"claim_ref", "claim_type", "evidence_state"}
_OBLIGATION_FIELDS = {
    "obligation_ref", "status", "materiality", "question_summary",
}
_OBLIGATION_CHANGE_FIELDS = {"obligation_id", "from_state", "to_state"}
_CLAIM_CHANGE_FIELDS = {"claim_id", "from_state", "to_state"}


def canonical_carrier(carrier: Any) -> dict[str, Any]:
    if not isinstance(carrier, dict) or set(carrier) != _CARRIER_FIELDS:
        raise ValueError("checkpoint carrier fields are invalid")
    reject_prohibited(carrier)
    encoded = json.dumps(
        carrier, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_CARRIER_BYTES:
        raise ValueError(f"checkpoint carrier exceeds {MAX_CARRIER_BYTES} bytes")
    value = deepcopy(carrier)
    if value["schema_version"] != 2:
        raise ValueError("checkpoint carrier schema_version must be 2")
    for field in (
        "workspace_ref", "work_package_ref", "branch_ref", "checkpoint_ref",
        "research_cycle_ref",
    ):
        reference(value[field], field)
    for field in ("title", "product_group", "current_node", "status", "graph_ref"):
        bounded_text(value[field], field)
    for field in ("decision_contract_hash", "methodology_hash"):
        if not isinstance(value[field], str) or not _SHA256.fullmatch(value[field]):
            raise ValueError(f"{field} must be lowercase sha256")
    _validate_lineage(value["report_lineage"])
    trial_plan_hash = value["trial_plan_hash"]
    if (
        not isinstance(trial_plan_hash, str)
        or (trial_plan_hash and not _SHA256.fullmatch(trial_plan_hash))
    ):
        raise ValueError("trial_plan_hash must be empty or lowercase sha256")
    cycle_prefix = "research-cycle:sha256:"
    if (
        not value["research_cycle_ref"].startswith(cycle_prefix)
        or not _SHA256.fullmatch(value["research_cycle_ref"][len(cycle_prefix):])
    ):
        raise ValueError("research_cycle_ref must identify a complete projection")
    omitted_count = value["omitted_evidence_count"]
    if (
        type(omitted_count) is not int
        or omitted_count < 0
        or omitted_count > 2_147_483_647
    ):
        raise ValueError("omitted_evidence_count must be a non-negative integer")
    for field in ("evidence_refs", "job_refs", "run_refs"):
        value[field] = _references(value[field], field)
    value["claims"] = _objects(value["claims"], _CLAIM_FIELDS, "claims")
    for item in value["claims"]:
        reference(item["claim_ref"], "claim_ref")
        bounded_text(item["claim_type"], "claim_type")
        bounded_text(item["evidence_state"], "evidence_state")
    value["open_obligations"] = _objects(
        value["open_obligations"], _OBLIGATION_FIELDS, "open_obligations",
    )
    for item in value["open_obligations"]:
        reference(item["obligation_ref"], "obligation_ref")
        for field in ("status", "materiality", "question_summary"):
            bounded_text(item[field], field, maximum=1000)
    _validate_closure(value["closure"])
    value["latest_transition"] = _canonical_transition(
        value["latest_transition"]
    )
    return value


def _validate_lineage(lineage: Any) -> None:
    if not isinstance(lineage, dict) or set(lineage) not in ({
        "status", "predecessor_checkpoint_ref",
    }, {
        "status", "predecessor_checkpoint_ref", "source_branch_ref",
    }):
        raise ValueError("report_lineage fields are invalid")
    status = lineage["status"]
    predecessor = lineage["predecessor_checkpoint_ref"]
    if status == "history_incomplete":
        raise ValueError(
            "research history is incomplete; restart from a trusted root"
        )
    if status == "root":
        if predecessor != "":
            raise ValueError("root report lineage cannot have a predecessor")
        return
    if status != "linked":
        raise ValueError("report_lineage status is invalid")
    reference(predecessor, "report_lineage.predecessor_checkpoint_ref")
    if not predecessor.startswith("trace:"):
        raise ValueError("report lineage predecessor must be a trace ref")
    if "source_branch_ref" in lineage:
        reference(lineage["source_branch_ref"], "report_lineage.source_branch_ref")
        if not lineage["source_branch_ref"].startswith("graph-branch:"):
            raise ValueError("report lineage source must be a graph branch ref")


def _validate_closure(closure: Any) -> None:
    if closure is None:
        return
    if not isinstance(closure, dict) or set(closure) != {
        "proposal_ref", "disposition",
    }:
        raise ValueError("closure fields are invalid")
    reference(closure["proposal_ref"], "closure.proposal_ref")
    bounded_text(closure["disposition"], "closure.disposition")


def _canonical_transition(transition: Any) -> dict[str, Any]:
    if not isinstance(transition, dict):
        raise ValueError("latest_transition fields are invalid")
    fields = set(transition)
    required = _TRANSITION_FIELDS - _TRANSITION_OPTIONAL_FIELDS
    if not (required <= fields <= _TRANSITION_FIELDS):
        raise ValueError("latest_transition fields are invalid")
    transition.setdefault("delta_refs", [])
    for field in ("step_ref", "edge_ref"):
        reference(transition[field], field)
    for field in ("from_node", "to_node"):
        bounded_text(transition[field], field)
    timestamp = transition["created_at"]
    if (
        not isinstance(timestamp, (int, float))
        or not math.isfinite(timestamp)
        or timestamp < 0
    ):
        raise ValueError(
            "latest_transition.created_at must be finite and non-negative"
        )
    transition["created_at"] = float(timestamp)
    for field in (
        "evidence_refs", "trial_plan_refs", "obligation_refs", "claim_refs",
        "job_refs", "run_refs", "delta_refs",
    ):
        transition[field] = _references(transition[field], field)
    for field, item_fields, identifier_field in (
        ("obligation_changes", _OBLIGATION_CHANGE_FIELDS, "obligation_id"),
        ("claim_changes", _CLAIM_CHANGE_FIELDS, "claim_id"),
    ):
        transition[field] = _objects(transition[field], item_fields, field)
        for item in transition[field]:
            safe_id(item[identifier_field], identifier_field)
            bounded_text(item["from_state"], "from_state")
            bounded_text(item["to_state"], "to_state")
    if "entry_resolution" in transition:
        transition["entry_resolution"] = _entry_resolution(
            transition["entry_resolution"]
        )
    if "report_fragment_ref" in transition or "report_items" in transition:
        if not (
            isinstance(transition.get("report_fragment_ref"), str)
            and transition["report_fragment_ref"].startswith(
                "report-fragment:sha256:"
            )
            and _SHA256.fullmatch(
                transition["report_fragment_ref"].removeprefix(
                    "report-fragment:sha256:"
                )
            )
        ):
            raise ValueError("report_fragment_ref must identify sha256")
        transition["report_items"] = _objects(
            transition.get("report_items"), _REPORT_ITEM_FIELDS, "report_items",
        )
        bindings = []
        for item in transition["report_items"]:
            reference(item["report_item_ref"], "report_item_ref")
            if not item["report_item_ref"].startswith("report-item:sha256:"):
                raise ValueError("report_item_ref must identify sha256")
            if not _SHA256.fullmatch(
                item["report_item_ref"].removeprefix("report-item:sha256:")
            ):
                raise ValueError("report_item_ref must identify sha256")
            for field in (
                "report_requirement_id", "subject_ref", "content_kind",
            ):
                bounded_text(item[field], field, maximum=256)
            bindings.append((
                item["report_requirement_id"], item["subject_ref"]
            ))
        if len(bindings) != len(set(bindings)):
            raise ValueError("report item bindings must be unique")
    return transition


def _entry_resolution(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _ENTRY_RESOLUTION_FIELDS:
        raise ValueError("entry_resolution fields are invalid")
    result = deepcopy(value)
    for field in ("reason", "resume_node"):
        text = result[field]
        if not isinstance(text, str) or len(text.encode()) > 128:
            raise ValueError(f"entry_resolution.{field} must be bounded text")
        if text:
            safe_id(text, f"entry_resolution.{field}")
    id_fields = (
        "assessed_requirement_ids", "reused_requirement_ids",
        "reference_only_requirement_ids", "unresolved_requirement_ids",
    )
    all_ids: set[str] = set()
    for field in id_fields:
        identifiers = result[field]
        if not isinstance(identifiers, list) or len(identifiers) > MAX_ITEMS:
            raise ValueError(f"entry_resolution.{field} must be bounded")
        for identifier in identifiers:
            safe_id(identifier, f"entry_resolution.{field}")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError(f"entry_resolution.{field} must be unique")
        all_ids.update(identifiers)
    result["items"] = _objects(
        result["items"], _ENTRY_RESOLUTION_ITEM_FIELDS,
        "entry_resolution.items",
    )
    item_ids = []
    for item in result["items"]:
        item_ids.append(safe_id(
            item["requirement_id"],
            "entry_resolution.item.requirement_id",
        ))
        chinese_text(
            item["title_zh"], "entry_resolution.item.title_zh", maximum=256,
        )
        if type(item["assessed"]) is not bool:
            raise ValueError("entry_resolution.item.assessed must be boolean")
        if item["change_kind"] not in _ENTRY_RESOLUTION_CHANGE_KINDS:
            raise ValueError("entry_resolution.item.change_kind is invalid")
        if item["resolution_status"] not in _ENTRY_RESOLUTION_STATUSES:
            raise ValueError("entry_resolution.item.resolution_status is invalid")
    if len(set(item_ids)) != len(item_ids) or set(item_ids) != all_ids:
        raise ValueError("entry_resolution.items must cover changed requirements")
    return result


def _objects(value: Any, fields: set[str], label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ValueError(f"{label} must be a bounded array")
    if any(not isinstance(item, dict) or set(item) != fields for item in value):
        raise ValueError(f"{label} item fields are invalid")
    return value


def _references(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ValueError(f"{field} must be a bounded reference array")
    for item in value:
        reference(item, field)
    return list(value)
