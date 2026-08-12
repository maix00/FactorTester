"""Pure scope revalidation for Edge obligation coverage.

The Graph decides which obligation class an Edge requires.  This module
decides whether a branch-local EvidenceUse still applies to the *current*
research subject.  It deliberately understands only typed, explicit scope
fields; free-form names are never promoted to factor or product identities.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.cli.factor_subject_refs import validate_factor_subject_ref


_REF_FIELDS = ("factor_refs", "product_refs", "sample_refs", "source_refs")
_HASH_FIELDS = (
    "contract_hash", "methodology_hash", "trial_plan_hash", "run_spec_hash",
)
_SINGULAR_REFS = {
    "factor_ref": "factor_refs",
    "product_ref": "product_refs",
    "sample_ref": "sample_refs",
    "source_ref": "source_refs",
}


def current_edge_scope(checkpoint: dict[str, Any] | None) -> dict[str, Any]:
    """Project the current non-superseded Claim scope for Edge revalidation."""
    value = checkpoint or {}
    scopes = [
        item.get("scope") or {}
        for item in value.get("claims") or []
        if (
            isinstance(item, dict)
            and item.get("evidence_state") != "superseded"
        )
    ]
    result = merge_scopes(*scopes)
    for field in ("contract_hash", "methodology_hash", "trial_plan_hash"):
        text = str(value.get(field) or "").removeprefix("sha256:")
        if text:
            result[field] = text
    return result


def obligation_bound_scope(
    obligation: dict[str, Any],
    *,
    claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return scope explicitly bound by an obligation and its linked Claims."""
    claim_ids = {
        str(item) for item in obligation.get("claim_ids") or [] if str(item)
    }
    linked = [
        item.get("scope") or {}
        for item in claims or []
        if (
            isinstance(item, dict)
            and str(item.get("claim_id") or "") in claim_ids
            and item.get("evidence_state") != "superseded"
        )
    ]
    result = merge_scopes(obligation.get("scope") or {}, *linked)
    for field in ("contract_hash", "methodology_hash"):
        text = str(obligation.get(field) or "").removeprefix("sha256:")
        if text:
            result[field] = text
    return result


def revalidate_evidence_uses(
    *,
    obligations: list[dict[str, Any]],
    evidence_uses: list[dict[str, Any]],
    edge_scope: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a deterministic, explainable coverage result for one row.

    A use is eligible only when its requested scope covers the current Edge
    scope and does not introduce a typed subject dimension that the obligation
    itself failed to bind.  Multiple uses of one obligation may collectively
    cover a multi-valued scope.
    """
    required = normalize_scope(edge_scope or {})
    by_obligation = {
        f"obligation:{item.get('obligation_id')}": item
        for item in obligations
        if isinstance(item, dict) and item.get("obligation_id")
    }
    uses_by_obligation: dict[str, list[dict[str, Any]]] = {}
    for use in evidence_uses:
        ref = str(use.get("obligation_ref") or "")
        if ref in by_obligation:
            uses_by_obligation.setdefault(ref, []).append(use)

    passing_use_ids: list[str] = []
    passing_obligation_refs: list[str] = []
    failures: list[dict[str, Any]] = []
    for obligation_ref, obligation in by_obligation.items():
        bound = merge_scopes(
            obligation.get("coverage_scope") or {},
            obligation.get("scope") or {},
            *[
                item.get("scope") or {}
                for item in obligation.get("claim_scopes") or []
                if (
                    isinstance(item, dict)
                    and item.get("evidence_state") != "superseded"
                )
            ],
        )
        uses = uses_by_obligation.get(obligation_ref, [])
        result = _covers_scope(
            uses=uses,
            required=required,
            obligation_bound=bound,
        )
        if result["matched"]:
            passing_obligation_refs.append(obligation_ref)
            passing_use_ids.extend(result["use_ids"])
        else:
            failures.append({
                "obligation_ref": obligation_ref,
                "missing": result["missing"],
                "unbound": result["unbound"],
            })
    return {
        "policy": "current_claim_scope",
        "required_scope": required,
        "status": "matched" if passing_obligation_refs else "missing",
        "passing_obligation_refs": passing_obligation_refs,
        "passing_use_ids": list(dict.fromkeys(passing_use_ids)),
        "failures": failures,
    }


def merge_scopes(*values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        normalized = normalize_scope(value)
        for field in _REF_FIELDS:
            if field in normalized:
                result[field] = list(dict.fromkeys([
                    *result.get(field, []), *normalized[field],
                ]))
        for field in _HASH_FIELDS:
            candidate = normalized.get(field)
            if not candidate:
                continue
            existing = result.get(field)
            if existing not in (None, candidate):
                raise ValueError(f"conflicting research scope {field}")
            result[field] = candidate
        if "time_window" in normalized:
            window = normalized["time_window"]
            existing = result.get("time_window")
            if existing not in (None, window):
                raise ValueError("conflicting research scope time_window")
            result["time_window"] = window
    return result


def normalize_scope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for singular, plural in _SINGULAR_REFS.items():
        item = value.get(singular)
        if isinstance(item, str):
            result.setdefault(plural, []).append(
                _validate_typed_ref(plural, item)
            )
    for field in _REF_FIELDS:
        items = value.get(field)
        if isinstance(items, list):
            typed = [_validate_typed_ref(field, item) for item in items]
            if typed:
                result[field] = list(dict.fromkeys([
                    *result.get(field, []), *typed,
                ]))
    for field in _HASH_FIELDS:
        text = str(value.get(field) or "").removeprefix("sha256:")
        if text:
            result[field] = text
    window = value.get("time_window")
    if isinstance(window, dict) and set(window) == {"start", "end"}:
        result["time_window"] = deepcopy(window)
    return result


def _covers_scope(
    *,
    uses: list[dict[str, Any]],
    required: dict[str, Any],
    obligation_bound: dict[str, Any],
) -> dict[str, Any]:
    requested = [
        normalize_scope((item.get("scope_match") or {}).get("requested_scope"))
        for item in uses
        if (
            isinstance(item, dict)
            and (item.get("scope_match") or {}).get("scope_compatibility")
            != "incompatible"
        )
    ]
    combined = merge_scopes(*requested)
    unbound: list[str] = []
    for field in _REF_FIELDS:
        introduced = set(combined.get(field) or [])
        bound = set(obligation_bound.get(field) or [])
        if introduced and not introduced.issubset(bound):
            unbound.append(field)
    missing: list[str] = []
    for field in _REF_FIELDS:
        if not set(required.get(field) or []).issubset(
            set(combined.get(field) or [])
        ):
            missing.append(field)
    for field in _HASH_FIELDS:
        expected = required.get(field)
        if expected and combined.get(field) != expected:
            missing.append(field)
    if "time_window" in required and combined.get("time_window") != required[
        "time_window"
    ]:
        missing.append("time_window")
    matched = bool(uses) and not missing and not unbound
    return {
        "matched": matched,
        "missing": missing,
        "unbound": unbound,
        "use_ids": [str(item.get("use_id") or "") for item in uses]
        if matched else [],
    }


def _validate_typed_ref(field: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"research scope {field} must contain typed refs")
    if field == "factor_refs":
        return validate_factor_subject_ref(value)
    prefix = {
        "product_refs": "product:",
        "sample_refs": "sample:",
        "source_refs": "source:",
    }[field]
    if not value.startswith(prefix) or len(value) <= len(prefix):
        raise ValueError(f"research scope {field} contains an invalid ref")
    return value
