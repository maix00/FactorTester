"""Deterministic obligation-delta and requirement-coverage projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .evidence_uses import (
    evidence_uses_for_requirement,
    meets_minimum_qualification,
)
from .definitions import validate_definition_candidate
from .scope_revalidation import revalidate_evidence_uses


_LIMITED_STATES = {"bounded", "serviced"}
_SATISFIED_STATES = {"discharged"}
_PENDING_STATES = {"open", "reopened"}
_DEFAULT_ACCEPTED_STATES = {"bounded", "serviced", "discharged"}


def apply_obligation_deltas(
    obligations: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Apply already accepted deltas, preserving complete obligation bodies."""
    if not isinstance(deltas, list) or any(
        not isinstance(item, dict) for item in deltas
    ):
        raise ValueError("obligation_delta must be an object array")
    projected = deepcopy(obligations)
    by_id = {
        str(item.get("obligation_id") or ""): item for item in projected
        if isinstance(item, dict) and item.get("obligation_id")
    }
    if len(by_id) != len(projected):
        raise ValueError("current obligations must have unique obligation_id")
    changed: set[str] = set()
    for delta in deltas:
        obligation_id = _required(delta, "obligation_id")
        from_state = _required(delta, "from_state")
        to_state = _required(delta, "to_state")
        obligation = by_id.get(obligation_id)
        if obligation is None:
            if from_state != "absent" or not isinstance(delta.get("obligation"), dict):
                raise ValueError("new obligation requires absent state and body")
            obligation = deepcopy(delta["obligation"])
            if (
                obligation.get("obligation_id") != obligation_id
                or obligation.get("status") != to_state
            ):
                raise ValueError("new obligation body does not match delta")
            obligation.setdefault("requirement_refs", [])
            projected.append(obligation)
            by_id[obligation_id] = obligation
        else:
            if str(obligation.get("status") or "") != from_state:
                raise ValueError(
                    f"obligation delta from_state is stale: {obligation_id}"
                )
            candidate = delta.get("obligation")
            if candidate is not None:
                if not isinstance(candidate, dict):
                    raise ValueError("obligation delta body must be an object")
                validate_definition_candidate(
                    obligation,
                    candidate,
                    obligation_id=obligation_id,
                    source="later obligation delta",
                )
            validate_definition_candidate(
                obligation,
                delta,
                obligation_id=obligation_id,
                source="later obligation delta",
            )
            before_refs = _refs(obligation.get("requirement_refs"))
            if "to_requirement_refs" in delta:
                if _refs(delta.get("from_requirement_refs")) != before_refs:
                    raise ValueError(
                        f"obligation requirement mapping is stale: {obligation_id}"
                    )
                obligation["requirement_refs"] = _refs(
                    delta.get("to_requirement_refs")
                )
            obligation["status"] = to_state
        changed.add(f"obligation:{obligation_id}")
    return projected, changed


def project_requirement_coverage(
    *,
    requirements: list[dict[str, Any]],
    obligations: list[dict[str, Any]],
    changed_obligation_refs: set[str] | None = None,
    evidence_uses: list[dict[str, Any]] | None = None,
    edge_required_ids: set[str] | None = None,
    node_required_ids: set[str] | None = None,
    title_overrides: dict[str, str] | None = None,
    enforce_evidence: bool = False,
) -> list[dict[str, Any]]:
    changed = changed_obligation_refs or set()
    required = edge_required_ids or set()
    node_required = (
        {
            _requirement_id(requirement)
            for requirement in requirements
        }
        if node_required_ids is None else node_required_ids
    )
    titles = title_overrides or {}
    rows = []
    for requirement in requirements:
        requirement_id = _requirement_id(requirement)
        mapped = [
            item for item in obligations
            if requirement_id in _refs(item.get("requirement_refs"))
        ]
        refs = [
            f"obligation:{item['obligation_id']}" for item in mapped
        ]
        statuses = [
            str(item.get("status") or "") for item in mapped
        ]
        edge_required = requirement_id in required
        accepted_states = _accepted_states(requirement)
        minimum_qualification = str(
            requirement.get("minimum_qualification") or "limited"
        )
        uses = evidence_uses_for_requirement(
            evidence_uses or [],
            requirement_id=requirement_id,
            obligation_refs=refs,
        )
        scope_revalidation = revalidate_evidence_uses(
            obligations=mapped,
            evidence_uses=uses,
            edge_scope=(
                (requirement.get("scope_policy") or {}).get(
                    "required_scope"
                )
            ),
        )
        rows.append({
            "requirement_id": requirement_id,
            "description": str(
                titles.get(requirement_id)
                or requirement.get("title_zh")
                or requirement.get("description_zh")
                or requirement.get("description")
                or ""
            ),
            "obligation_refs": refs,
            "obligation_statuses": statuses,
            "evidence_uses": uses,
            "changed": any(item in changed for item in refs),
            "node_required": requirement_id in node_required,
            "edge_required": edge_required,
            "accepted_states": sorted(accepted_states),
            "minimum_qualification": minimum_qualification,
            "scope_revalidation": scope_revalidation,
            "satisfaction": _satisfaction(
                statuses,
                edge_required=edge_required,
                accepted_states=accepted_states,
                evidence_uses=uses,
                obligations=mapped,
                minimum_qualification=minimum_qualification,
                enforce_evidence=enforce_evidence,
                scope_revalidation=scope_revalidation,
            ),
        })
    return rows


def requirement_title_overrides(
    ledger: dict[str, Any],
) -> dict[str, str]:
    """Preserve migrated presentation titles across later graph projections."""
    titles: dict[str, str] = {}
    sources = [
        ledger.get("current_projection", {}).get("requirement_coverage") or [],
        *[
            event.get("coverage_snapshot") or []
            for event in reversed(ledger.get("history") or [])
            if isinstance(event, dict)
        ],
    ]
    for rows in sources:
        for row in rows:
            requirement_id = str(row.get("requirement_id") or "").removeprefix(
                "requirement:"
            )
            title = str(row.get("description") or "").strip()
            if requirement_id and title and requirement_id not in titles:
                titles[requirement_id] = title
    return titles


def _satisfaction(
    statuses: list[str],
    *,
    edge_required: bool,
    accepted_states: set[str],
    evidence_uses: list[dict[str, Any]],
    obligations: list[dict[str, Any]],
    minimum_qualification: str,
    enforce_evidence: bool,
    scope_revalidation: dict[str, Any],
) -> str:
    values = set(statuses)
    accepted = values & accepted_states
    if accepted:
        if enforce_evidence and edge_required:
            passing_uses = set(
                scope_revalidation.get("passing_use_ids") or []
            )
            passing_obligations = set(
                scope_revalidation.get("passing_obligation_refs") or []
            )
            accepted_obligations = {
                f"obligation:{item.get('obligation_id')}"
                for item in obligations
                if str(item.get("status") or "") in accepted_states
            }
            passing_obligations &= accepted_obligations
            qualified = [
                item for item in evidence_uses
                if (
                    item["use_id"] in passing_uses
                    and item["obligation_ref"] in passing_obligations
                    and
                    item["scope_match"]["scope_compatibility"]
                    != "incompatible"
                    and meets_minimum_qualification(
                        item["qualification"], minimum_qualification,
                    )
                )
            ]
            if not qualified:
                return "missing"
            if (
                values & _SATISFIED_STATES
                and any(
                    item["qualification"] == "eligible"
                    for item in qualified
                )
            ):
                return "satisfied"
            return "limited"
        if values & _SATISFIED_STATES:
            return "satisfied"
        if values & _LIMITED_STATES:
            return "limited"
    if not values:
        return "missing" if edge_required else "pending"
    if values & _PENDING_STATES:
        return "missing" if edge_required else "pending"
    return "missing"


def _accepted_states(requirement: dict[str, Any]) -> set[str]:
    value = requirement.get("accepted_states")
    if value is None:
        return set(_DEFAULT_ACCEPTED_STATES)
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError("accepted_states must be a non-empty string array")
    return set(value)


def _requirement_id(value: dict[str, Any]) -> str:
    text = value.get("requirement_id")
    if not isinstance(text, str) or not text:
        raise ValueError("requirement_id is required")
    return text.removeprefix("requirement:")


def _required(value: dict[str, Any], field: str) -> str:
    text = value.get(field)
    if not isinstance(text, str) or not text:
        raise ValueError(f"{field} is required")
    return text


def _refs(value: Any) -> list[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError("requirement_refs must be a string array")
    return list(dict.fromkeys(
        item.removeprefix("requirement:") for item in value
    ))
