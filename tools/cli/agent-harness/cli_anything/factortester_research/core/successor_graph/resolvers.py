"""Typed resolver bindings and activation audit for Graph v9 requirements."""

from __future__ import annotations

from typing import Any

from .resolver_contracts import (
    AGENT_JUDGMENT,
    DETERMINISTIC_FACT,
    OPERATIONS,
    operation_contract,
    valid_object_schema,
)


_KINDS = {DETERMINISTIC_FACT, AGENT_JUDGMENT}
_STATIC_LOOKUPS = {
    "factortester-research.graph.requirement-detail",
    "factortester.research-graph.requirement-detail",
}


def build_requirement_resolver_bindings(
    catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return one explicit resolver contract per requirement."""
    return [
        _binding(item)
        for item in catalog["requirements"]
    ]


def resolver_binding_ref(requirement_id: str) -> str:
    return f"resolver-binding:{requirement_id}@1"


def validate_requirement_resolver_activation(
    graph: dict[str, Any],
) -> dict[str, Any]:
    """Audit the entire immutable catalog, independent of branch context."""
    requirements = (
        graph.get("requirement_catalog", {}).get("requirements") or []
    )
    bindings = graph.get("requirement_resolver_bindings") or []
    failures: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        binding_id = str(binding.get("binding_id") or "")
        if not binding_id or binding_id in by_id:
            failures.append("invalid_or_duplicate_binding_id")
            continue
        by_id[binding_id] = binding
    covered: set[str] = set()
    for requirement in requirements:
        requirement_id = str(requirement.get("requirement_id") or "")
        binding_ref = str(requirement.get("resolver_binding_ref") or "")
        binding = by_id.get(binding_ref)
        if binding is None:
            failures.append("missing_requirement_binding")
            continue
        if binding.get("requirement_ref") != requirement_id:
            failures.append("requirement_binding_mismatch")
        covered.add(requirement_id)
        _audit_binding(binding, failures)
    declared_requirements = {
        str(item.get("requirement_id") or "") for item in requirements
    }
    bound_requirements = {
        str(item.get("requirement_ref") or "") for item in bindings
    }
    if bound_requirements != declared_requirements:
        failures.append("resolver_catalog_coverage_mismatch")
    return {
        "passed": not failures,
        "requirement_count": len(requirements),
        "binding_count": len(bindings),
        "deterministic_fact_count": sum(
            item.get("resolver_kind") == DETERMINISTIC_FACT
            for item in bindings
        ),
        "agent_judgment_count": sum(
            item.get("resolver_kind") == AGENT_JUDGMENT
            for item in bindings
        ),
        "covered_requirement_count": len(covered),
        "failure_codes": sorted(set(failures)),
    }


def _binding(requirement: dict[str, Any]) -> dict[str, Any]:
    requirement_id = str(requirement["requirement_id"])
    kind, invocation, output = operation_contract(requirement_id)
    return {
        "binding_id": resolver_binding_ref(requirement_id),
        "requirement_ref": requirement_id,
        "resolver_kind": kind,
        "approval_status": "builtin_approved",
        "invocation_contract": invocation,
        "output_contract": output,
    }


def _audit_binding(binding: dict[str, Any], failures: list[str]) -> None:
    kind = str(binding.get("resolver_kind") or "")
    if kind not in _KINDS:
        failures.append("invalid_resolver_kind")
    if binding.get("approval_status") != "builtin_approved":
        failures.append("resolver_not_approved")
    invocation = binding.get("invocation_contract")
    if not isinstance(invocation, dict):
        failures.append("missing_invocation_contract")
        return
    operation_id = str(invocation.get("operation_id") or "")
    if operation_id in _STATIC_LOOKUPS:
        failures.append("static_contract_lookup")
    operation_kind = OPERATIONS.get(operation_id)
    if operation_kind is None:
        failures.append("unknown_resolver_operation")
    elif operation_kind != kind:
        failures.append("resolver_operation_kind_mismatch")
    if kind == DETERMINISTIC_FACT:
        if invocation.get("transport") != "cli":
            failures.append("deterministic_resolver_transport_mismatch")
        argv = invocation.get("argv_template")
        if not isinstance(argv, list) or not all(
            isinstance(item, str) and item for item in argv
        ):
            failures.append("missing_cli_argv_template")
    elif (
        invocation.get("transport") != "agent_checklist"
        or not isinstance(invocation.get("checklist_fields"), list)
        or not invocation["checklist_fields"]
    ):
        failures.append("missing_agent_checklist_contract")
    if not valid_object_schema(invocation.get("input_schema")):
        failures.append("missing_invocation_input_schema")
    if not valid_object_schema(binding.get("output_contract")):
        failures.append("missing_resolver_output_contract")
