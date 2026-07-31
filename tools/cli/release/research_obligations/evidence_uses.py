"""Validation and projection helpers for branch-local EvidenceUse records."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from typing import Any


QUALIFICATIONS = (
    "unverifiable_fragment",
    "rejected",
    "unreviewed",
    "limited",
    "eligible",
)
_QUALIFICATION_RANK = {
    value: index for index, value in enumerate(QUALIFICATIONS)
}


def apply_evidence_use_deltas(
    current: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
    *,
    obligations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Apply explicit add/remove operations without copying uses implicitly."""
    values = [normalize_evidence_use(item) for item in current]
    by_id = {item["use_id"]: item for item in values}
    obligation_requirements = {
        f"obligation:{item['obligation_id']}": set(
            _requirement_refs(item.get("requirement_refs"))
        )
        for item in obligations
        if isinstance(item, dict) and item.get("obligation_id")
    }
    changed: set[str] = set()
    if not isinstance(deltas, list) or any(
        not isinstance(item, dict) for item in deltas
    ):
        raise ValueError("evidence_use_delta must be an object array")
    for delta in deltas:
        operation = str(delta.get("op") or "")
        if operation == "add":
            use = normalize_evidence_use(delta.get("use"))
            obligation_ref = use["obligation_ref"]
            allowed = obligation_requirements.get(obligation_ref)
            if allowed is None:
                raise ValueError(
                    f"EvidenceUse obligation does not exist: {obligation_ref}"
                )
            if not set(use["requirement_refs"]).issubset(allowed):
                raise ValueError(
                    "EvidenceUse requirement_refs must be covered by its "
                    "obligation"
                )
            existing = by_id.get(use["use_id"])
            if existing is not None and existing != use:
                raise ValueError("EvidenceUse identity collision")
            by_id[use["use_id"]] = use
            changed.add(use["use_id"])
        elif operation == "remove":
            use_id = _text(delta.get("use_id"), "use_id")
            if use_id not in by_id:
                raise ValueError(f"EvidenceUse does not exist: {use_id}")
            by_id.pop(use_id)
            changed.add(use_id)
        else:
            raise ValueError("EvidenceUse delta op must be add or remove")
    return list(by_id.values()), changed


def normalize_evidence_use(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("EvidenceUse must be an object")
    required = {
        "evidence_ref", "evidence_title_zh", "obligation_ref",
        "requirement_refs", "rationale_zh", "qualification", "scope_match",
    }
    optional = {"use_id"}
    if not required.issubset(value) or set(value) - required - optional:
        raise ValueError("EvidenceUse fields are invalid")
    evidence_ref = _text(value["evidence_ref"], "evidence_ref")
    if not evidence_ref.startswith("evidence:"):
        raise ValueError("EvidenceUse evidence_ref is invalid")
    obligation_ref = _text(value["obligation_ref"], "obligation_ref")
    if not obligation_ref.startswith("obligation:"):
        raise ValueError("EvidenceUse obligation_ref is invalid")
    title = _text(value["evidence_title_zh"], "evidence_title_zh")
    rationale = _text(value["rationale_zh"], "rationale_zh")
    qualification = _text(value["qualification"], "qualification")
    if qualification not in _QUALIFICATION_RANK:
        raise ValueError("EvidenceUse qualification is invalid")
    scope_match = deepcopy(value["scope_match"])
    if not isinstance(scope_match, dict):
        raise ValueError("EvidenceUse scope_match must be an object")
    compatibility = scope_match.get("scope_compatibility")
    if compatibility not in {"compatible", "limited", "incompatible"}:
        raise ValueError(
            "EvidenceUse scope_match.scope_compatibility is invalid"
        )
    for field in ("matched_by", "conflicts", "limitations"):
        items = scope_match.get(field, [])
        if not isinstance(items, list) or any(
            not isinstance(item, str) for item in items
        ):
            raise ValueError(f"EvidenceUse scope_match.{field} is invalid")
        scope_match[field] = list(dict.fromkeys(items))
    requested_scope = scope_match.get("requested_scope")
    if not isinstance(requested_scope, dict) or not requested_scope:
        raise ValueError(
            "EvidenceUse scope_match.requested_scope must be a non-empty object"
        )
    scope_match["requested_scope"] = deepcopy(requested_scope)
    normalized = {
        "evidence_ref": evidence_ref,
        "evidence_title_zh": title,
        "obligation_ref": obligation_ref,
        "requirement_refs": _requirement_refs(value["requirement_refs"]),
        "rationale_zh": rationale,
        "qualification": qualification,
        "scope_match": scope_match,
    }
    expected = evidence_use_id(normalized)
    supplied = value.get("use_id")
    if supplied not in (None, expected):
        raise ValueError("EvidenceUse use_id does not match its content")
    return {"use_id": expected, **normalized}


def validate_evidence_use_object(
    use: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Verify frozen title, fragment presence and requested scope locally."""
    normalized = normalize_evidence_use(use)
    if evidence.get("evidence_ref") != normalized["evidence_ref"]:
        raise ValueError("EvidenceUse object reference mismatch")
    envelope = evidence.get("envelope") or {}
    title = str(
        envelope.get("title_zh") or envelope.get("title") or ""
    ).strip()
    if title != normalized["evidence_title_zh"]:
        raise ValueError("EvidenceUse evidence_title_zh is stale")
    fragments = evidence.get("fragments")
    if not isinstance(fragments, list) or not fragments:
        raise ValueError(
            "EvidenceUse requires fragment-bound Evidence; historical "
            "source-wide Evidence is not eligible"
        )
    _validate_requested_scope(
        evidence.get("applicability") or {},
        normalized["scope_match"]["requested_scope"],
    )
    if normalized["scope_match"]["scope_compatibility"] == "incompatible":
        raise ValueError("incompatible Evidence cannot be used")
    return normalized


def validate_requested_scope(
    applicability: dict[str, Any],
    requested: dict[str, Any],
) -> None:
    """Public pure validator used by CLI and server-side admission replay."""
    _validate_requested_scope(applicability, requested)


def evidence_use_id(value: dict[str, Any]) -> str:
    payload = {
        field: value[field]
        for field in (
            "evidence_ref", "evidence_title_zh", "obligation_ref",
            "requirement_refs", "rationale_zh", "qualification", "scope_match",
        )
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return "evidence-use:sha256:" + hashlib.sha256(encoded).hexdigest()


def evidence_uses_for_requirement(
    evidence_uses: list[dict[str, Any]],
    *,
    requirement_id: str,
    obligation_refs: list[str],
) -> list[dict[str, Any]]:
    allowed = set(obligation_refs)
    return [
        normalize_evidence_use(item)
        for item in evidence_uses
        if (
            item.get("obligation_ref") in allowed
            and requirement_id in _requirement_refs(
                item.get("requirement_refs")
            )
        )
    ]


def meets_minimum_qualification(
    qualification: str, minimum: str,
) -> bool:
    if minimum not in _QUALIFICATION_RANK:
        raise ValueError("minimum_qualification is invalid")
    return _QUALIFICATION_RANK.get(qualification, -1) >= (
        _QUALIFICATION_RANK[minimum]
    )


def _requirement_refs(value: Any) -> list[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError("EvidenceUse requirement_refs is invalid")
    return list(dict.fromkeys(
        item.removeprefix("requirement:") for item in value
    ))


def _validate_requested_scope(
    applicability: dict[str, Any],
    requested: dict[str, Any],
) -> None:
    if not isinstance(applicability, dict):
        raise ValueError("Evidence applicability is invalid")
    allowed = {
        "product_refs", "factor_refs", "sample_refs", "source_refs",
        "contract_hash", "methodology_hash", "trial_plan_hash",
        "run_spec_hash", "time_window",
    }
    if set(requested) - allowed:
        raise ValueError("EvidenceUse requested_scope fields are invalid")
    for field in (
        "product_refs", "factor_refs", "sample_refs", "source_refs",
    ):
        values = requested.get(field)
        if values is None:
            continue
        if not isinstance(values, list) or not values:
            raise ValueError(f"requested_scope.{field} is invalid")
        if not set(values).issubset(set(applicability.get(field) or [])):
            raise ValueError(f"EvidenceUse {field} is outside Evidence scope")
    for field in (
        "contract_hash", "methodology_hash", "trial_plan_hash",
        "run_spec_hash",
    ):
        if field in requested and requested[field] != applicability.get(field):
            raise ValueError(f"EvidenceUse {field} is outside Evidence scope")
    if "time_window" in requested:
        if not _contains_window(
            applicability.get("time_window"), requested["time_window"],
        ):
            raise ValueError("EvidenceUse time_window is outside Evidence scope")


def _contains_window(available: Any, requested: Any) -> bool:
    if not isinstance(available, dict) or not isinstance(requested, dict):
        return False
    try:
        available_start = date.fromisoformat(str(available["start"])[:10])
        available_end = date.fromisoformat(str(available["end"])[:10])
        requested_start = date.fromisoformat(str(requested["start"])[:10])
        requested_end = date.fromisoformat(str(requested["end"])[:10])
    except (KeyError, TypeError, ValueError):
        return False
    return available_start <= requested_start <= requested_end <= available_end


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()
