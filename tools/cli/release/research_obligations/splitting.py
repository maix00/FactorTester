"""Explicit obligation splitting without implicit Evidence inheritance."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def prepare_obligation_split(
    *,
    obligations: list[dict[str, Any]],
    evidence_uses: list[dict[str, Any]],
    parent_obligation_id: str,
    children: list[dict[str, Any]],
    child_evidence_use_delta: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build ordinary deltas for one audited parent-to-children split."""
    parent = next((
        item for item in obligations
        if item.get("obligation_id") == parent_obligation_id
    ), None)
    if parent is None:
        raise ValueError("split parent obligation does not exist")
    if parent.get("status") == "superseded":
        raise ValueError("split parent obligation is already superseded")
    if not isinstance(children, list) or len(children) < 2:
        raise ValueError("obligation split requires at least two children")
    if any(not isinstance(item, dict) for item in children):
        raise ValueError("obligation split children must be objects")

    parent_refs = set(_requirement_refs(parent.get("requirement_refs")))
    child_ids: set[str] = set()
    child_refs: set[str] = set()
    obligation_delta = [{
        "obligation_id": parent_obligation_id,
        "from_state": str(parent.get("status") or ""),
        "to_state": "superseded",
        "from_requirement_refs": sorted(parent_refs),
        "to_requirement_refs": [],
    }]
    for child in children:
        child_id = _text(child.get("obligation_id"), "child obligation_id")
        if child_id == parent_obligation_id or child_id in child_ids:
            raise ValueError("split child obligation_id must be unique")
        if any(item.get("obligation_id") == child_id for item in obligations):
            raise ValueError(f"split child obligation already exists: {child_id}")
        refs = set(_requirement_refs(child.get("requirement_refs")))
        if not refs:
            raise ValueError("each split child must cover a requirement")
        if not refs.issubset(parent_refs):
            raise ValueError(
                "split child requirement_refs must come from the parent"
            )
        child_ids.add(child_id)
        child_refs.update(refs)
        status = _text(child.get("status"), "child status")
        obligation_delta.append({
            "obligation_id": child_id,
            "from_state": "absent",
            "to_state": status,
            "obligation": deepcopy(child),
        })
    if child_refs != parent_refs:
        raise ValueError(
            "split children must collectively retain every parent requirement"
        )

    evidence_use_delta = [
        {"op": "remove", "use_id": str(item["use_id"])}
        for item in evidence_uses
        if item.get("obligation_ref") == f"obligation:{parent_obligation_id}"
    ]
    if not isinstance(child_evidence_use_delta, list):
        raise ValueError("child_evidence_use_delta must be an array")
    for delta in child_evidence_use_delta:
        if not isinstance(delta, dict) or delta.get("op") != "add":
            raise ValueError(
                "child_evidence_use_delta only accepts explicit add operations"
            )
        obligation_ref = str((delta.get("use") or {}).get("obligation_ref") or "")
        if obligation_ref.removeprefix("obligation:") not in child_ids:
            raise ValueError(
                "split EvidenceUse must bind one of the new child obligations"
            )
        evidence_use_delta.append(deepcopy(delta))

    return {
        "obligation_delta": obligation_delta,
        "evidence_use_delta": evidence_use_delta,
        "split_parent_ref": f"obligation:{parent_obligation_id}",
        "split_child_refs": [
            f"obligation:{item}" for item in sorted(child_ids)
        ],
    }


def _requirement_refs(value: Any) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError("requirement_refs must be a string array")
    return list(dict.fromkeys(
        item.removeprefix("requirement:") for item in value
    ))


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value
