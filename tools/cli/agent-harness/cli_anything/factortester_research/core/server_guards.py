"""Replay-safe guard facts derived from server-owned evidence."""

from __future__ import annotations

from typing import Any

from .evidence import validate_evidence_envelope

_DATA_REQUIREMENT_REFS = frozenset({
    "data-availability.scope",
})


def derive_server_guard_facts(
    edge: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Recompute declared server-action facts without trusting booleans."""
    action = edge.get("server_action")
    if action == "bind_job_attempt":
        return _job_attempt_facts(evidence)
    if action == "bind_factor_semantics":
        return _factor_semantics_facts(evidence)
    if action != "bind_data_availability":
        return {}
    server_evidence = evidence.get("server_evidence")
    availability_envelope = (
        server_evidence.get("data_availability")
        if isinstance(server_evidence, dict) else None
    )
    provenance_envelope = (
        server_evidence.get("data_provenance")
        if isinstance(server_evidence, dict) else None
    )
    if not isinstance(availability_envelope, dict):
        return {
            "data_availability_profile_bound": False,
            "material_data_obligations_adjudicated_or_not_triggered": False,
            "requested_product_availability_present": False,
        }
    availability = validate_evidence_envelope(availability_envelope)
    if availability.get("evidence_kind") != "data_availability":
        raise ValueError("data-contract edge requires availability evidence")
    availability_facts = availability.get("facts")
    if not isinstance(availability_facts, dict):
        raise ValueError("availability evidence requires facts")
    request = availability_facts.get("request")
    products = request.get("products") if isinstance(request, dict) else None
    statuses = availability_facts.get("product_status")
    if not isinstance(products, list) or not isinstance(statuses, list):
        raise ValueError("availability request and product_status are required")
    status_by_product = {
        str(item.get("product") or ""): item.get("available") is True
        for item in statuses
        if isinstance(item, dict)
    }
    present = all(
        isinstance(product, str) and status_by_product.get(product) is True
        for product in products
    )
    if present is not (
        availability_facts.get("requested_product_availability_present") is True
    ):
        raise ValueError("availability summary does not match product_status")

    if isinstance(provenance_envelope, dict):
        provenance = validate_evidence_envelope(provenance_envelope)
        if provenance.get("evidence_kind") != "data_contract":
            raise ValueError("data-contract edge requires provenance evidence")
        provenance_facts = provenance.get("facts")
        if not isinstance(provenance_facts, dict):
            raise ValueError("provenance evidence requires facts")
        if (
            provenance_facts.get("profile_ref")
            != availability_facts.get("profile_ref")
            or provenance.get("identity_refs")
            != availability.get("identity_refs")
        ):
            raise ValueError("availability and provenance identity mismatch")
        if provenance_facts.get("snapshot_status") not in {
            "recorded", "unavailable",
        }:
            raise ValueError("provenance evidence requires snapshot_status")
    checkpoint = evidence.get("research_cycle_checkpoint")
    required_fields_available = _required_market_fields_available(
        availability_facts
    )
    historical_catalog_bound = _historical_field_catalog_bound(
        availability_facts
    )
    bounded_scope = (
        present
        or (
            str(edge.get("to_node") or "") == "factor_semantics"
            and _material_data_obligations_are_bounded(checkpoint)
        )
    )
    return {
        "data_availability_profile_bound": True,
        "material_data_obligations_adjudicated_or_not_triggered": (
            _data_obligation_gate_satisfied(
                checkpoint,
            )
        ),
        "requested_product_availability_present": bounded_scope,
        "required_market_fields_available": required_fields_available,
        "historical_field_catalog_bound": historical_catalog_bound,
    }


def _required_market_fields_available(facts: dict[str, Any]) -> bool:
    request = facts.get("request")
    fields = request.get("fields") if isinstance(request, dict) else None
    statuses = facts.get("required_field_status")
    if not isinstance(fields, list) or not fields or not isinstance(statuses, list):
        return False
    acceptable = {"direct", "derived"}
    return bool(statuses) and all(
        isinstance(item, dict)
        and isinstance(item.get("statuses"), list)
        and bool(acceptable.intersection(item["statuses"]))
        for item in statuses
    )


def _historical_field_catalog_bound(facts: dict[str, Any]) -> bool:
    request = facts.get("request")
    if not isinstance(request, dict) or request.get("include_historical_fields") is not True:
        return False
    products = request.get("products")
    summary = facts.get("historical_field_summary")
    if not isinstance(products, list) or not isinstance(summary, list):
        return False
    bound = {
        str(item.get("product") or "")
        for item in summary
        if isinstance(item, dict)
    }
    return all(isinstance(product, str) and product in bound for product in products)


def _data_obligation_gate_satisfied(
    checkpoint: Any,
) -> bool:
    relevant = _material_data_obligations(checkpoint)
    return not any(
        item.get("status") in {"open", "reopened"} for item in relevant
    )


def _material_data_obligations_are_bounded(checkpoint: Any) -> bool:
    relevant = _material_data_obligations(checkpoint)
    return bool(relevant) and not any(
        item.get("status") in {"open", "reopened"} for item in relevant
    )


def _material_data_obligations(checkpoint: Any) -> list[dict[str, Any]]:
    obligations = (
        checkpoint.get("obligations")
        if isinstance(checkpoint, dict)
        else None
    )
    if not isinstance(obligations, list):
        obligations = []
    return [
        item for item in obligations
        if isinstance(item, dict)
        and item.get("materiality") == "decision_blocking"
        and _is_data_obligation(item)
    ]


def _is_data_obligation(item: dict[str, Any]) -> bool:
    refs = set(item.get("requirement_refs") or [])
    if refs & _DATA_REQUIREMENT_REFS or any(
        str(ref).startswith("data.") for ref in refs
    ):
        return True
    return (
        str(item.get("obligation_kind") or "").startswith("data_")
        or (
            isinstance(item.get("discharge_criterion"), dict)
            and item["discharge_criterion"].get("rule_ref")
            == "research-rule:data-availability-exact-scope"
        )
    )


def _job_attempt_facts(evidence: dict[str, Any]) -> dict[str, Any]:
    server_evidence = evidence.get("server_evidence")
    envelope = (
        server_evidence.get("job_attempt")
        if isinstance(server_evidence, dict) else None
    )
    empty = {
        "terminal_job_evidence_retained": False,
        "terminal_job_trusted": False,
        "net_return_series_available": False,
    }
    if not isinstance(envelope, dict):
        return empty
    value = validate_evidence_envelope(envelope)
    if value.get("evidence_kind") != "job_attempt":
        raise ValueError("backtest edge requires JobAttempt evidence")
    facts = value.get("facts")
    assurance = facts.get("assurance") if isinstance(facts, dict) else None
    if not isinstance(assurance, dict):
        raise ValueError("JobAttempt evidence requires assurance facts")
    return {
        "terminal_job_evidence_retained": True,
        "terminal_job_trusted": (
            facts.get("status") == "succeeded"
            and assurance.get("disposition") == "trusted"
            and assurance.get("anomaly_codes") == []
        ),
        "net_return_series_available": (
            facts.get("net_return_series_available") is True
            and isinstance(facts.get("net_return_series_ref"), str)
            and facts["net_return_series_ref"] in value["artifact_refs"]
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
            "frozen_factor_formulas_bound": False,
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
        "frozen_factor_formulas_bound": True,
        "selected_factor_semantics_resolved": all(
            isinstance(item, dict)
            and item.get("resolution_status") == "resolved"
            for item in refs
        ),
    }
