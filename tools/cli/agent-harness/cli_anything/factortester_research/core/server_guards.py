"""Replay-safe guard facts derived from server-owned evidence."""

from __future__ import annotations

from typing import Any

from .evidence import validate_evidence_envelope


def derive_server_guard_facts(
    edge: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Recompute declared server-action facts without trusting booleans."""
    action = edge.get("server_action")
    if action == "bind_factor_semantics":
        return _factor_semantics_facts(evidence)
    if action != "bind_data_availability":
        return {}
    server_evidence = evidence.get("server_evidence")
    envelope = (
        server_evidence.get("data_availability")
        if isinstance(server_evidence, dict) else None
    )
    if not isinstance(envelope, dict):
        return {
            "data_availability_profile_bound": False,
            "requested_product_availability_present": False,
        }
    value = validate_evidence_envelope(envelope)
    if value.get("evidence_kind") != "data_availability":
        raise ValueError("data-contract edge requires availability evidence")
    facts = value.get("facts")
    profile = facts.get("profile") if isinstance(facts, dict) else None
    if not isinstance(profile, dict):
        raise ValueError("availability evidence requires facts.profile")
    products = profile.get("product_scope")
    entries = profile.get("entries")
    if not isinstance(products, list) or not isinstance(entries, list):
        raise ValueError("availability profile scope and entries are required")
    available = {
        str(item.get("product") or "")
        for item in entries
        if isinstance(item, dict) and item.get("status") == "available"
    }
    return {
        "data_availability_profile_bound": True,
        "requested_product_availability_present": all(
            isinstance(product, str) and product in available
            for product in products
        ),
    }


def _factor_semantics_facts(evidence: dict[str, Any]) -> dict[str, Any]:
    server_evidence = evidence.get("server_evidence")
    envelope = (
        server_evidence.get("factor_semantics")
        if isinstance(server_evidence, dict) else None
    )
    if not isinstance(envelope, dict):
        return {
            "factor_revision_manifests_bound": False,
            "selected_factor_semantics_resolved": False,
        }
    value = validate_evidence_envelope(envelope)
    if value.get("evidence_kind") != "factor_semantics":
        raise ValueError("factor-semantics edge requires factor evidence")
    facts = value.get("facts")
    refs = (
        facts.get("factor_revision_refs")
        if isinstance(facts, dict) else None
    )
    if not isinstance(refs, list) or not refs:
        raise ValueError("factor semantics requires revision references")
    return {
        "factor_revision_manifests_bound": True,
        "selected_factor_semantics_resolved": all(
            isinstance(item, dict)
            and item.get("resolution_status") == "resolved"
            for item in refs
        ),
    }
