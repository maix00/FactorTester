"""Invocation and output contracts for requirement resolver operations."""

from __future__ import annotations

from typing import Any


DETERMINISTIC_FACT = "deterministic_cli_fact"
AGENT_JUDGMENT = "requires_agent_judgment"
OPERATIONS = {
    "factortester.products.availability.source": DETERMINISTIC_FACT,
    "factortester.products.availability.coverage": DETERMINISTIC_FACT,
    "factortester.products.availability.depth": DETERMINISTIC_FACT,
    "factortester.products.availability.required-fields": DETERMINISTIC_FACT,
    "factortester-research.graph.trial-plan-check": DETERMINISTIC_FACT,
    "research-agent.requirement-checklist": AGENT_JUDGMENT,
}
TRIAL_PLAN_FACTS = {
    "trial_design_validity.controlled_variable_isolation",
}
DATA_AVAILABILITY_FACTS = {
    "data.source_availability": (
        "source",
        ["schema_version", "product_scope", "source_scope", "entries", "profile_hash"],
        ["product", "source", "status"],
        [],
    ),
    "data.temporal_coverage": (
        "coverage",
        ["schema_version", "as_of", "entries", "profile_hash"],
        ["coverage"],
        ["--expanded"],
    ),
    "data.granularity_and_depth": (
        "depth",
        ["schema_version", "entries", "profile_hash"],
        ["frequency", "data_kind", "market_depth"],
        ["--expanded"],
    ),
    "data.required_fields": (
        "required-fields",
        ["schema_version", "required_fields", "entries", "profile_hash"],
        ["required_fields"],
        ["--field", "<fields...>"],
    ),
}


def operation_contract(
    requirement_id: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if requirement_id in DATA_AVAILABILITY_FACTS:
        suffix, required, entry_fields, extra_argv = (
            DATA_AVAILABILITY_FACTS[requirement_id]
        )
        return (
            DETERMINISTIC_FACT,
            _cli_invocation(
                f"factortester.products.availability.{suffix}",
                ["products", "sources"],
                [
                    "factortester", "products", "availability",
                    "--product", "<products...>",
                    "--source", "<sources...>",
                    *extra_argv,
                    "--json",
                ],
            ),
            {
                **_schema(required),
                "required_entry_fields": entry_fields,
            },
        )
    if requirement_id in TRIAL_PLAN_FACTS:
        return (
            DETERMINISTIC_FACT,
            _cli_invocation(
                "factortester-research.graph.trial-plan-check",
                [
                    "trial_plan",
                    "validation_contract",
                    "action_input_summaries",
                    "run_spec_summaries",
                ],
                [
                    "factortester-research", "graph", "trial-plan-check",
                    "<document_file>", "--json",
                ],
            ),
            _schema([
                "passed",
                "ordered_action_ids",
                "declared_action_roles",
                "required_dependencies",
                "control_pairs",
            ]),
        )
    return (
        AGENT_JUDGMENT,
        {
            "operation_id": "research-agent.requirement-checklist",
            "transport": "agent_checklist",
            "checklist_fields": [
                "applicability",
                "rationale",
                "evidence_refs",
                "limitations",
                "first_trial_ref",
            ],
            "input_schema": _schema([
                "requirement_ref",
                "subject_ref",
                "scope_ref",
                "evidence_refs",
            ]),
        },
        _schema([
            "applicability",
            "decision",
            "rationale",
            "evidence_refs",
            "limitations",
            "first_trial_ref",
        ]),
    )


def valid_object_schema(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") == "object"
        and isinstance(value.get("required"), list)
        and bool(value["required"])
        and all(isinstance(item, str) and item for item in value["required"])
    )


def _cli_invocation(
    operation_id: str,
    required: list[str],
    argv: list[str],
) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "transport": "cli",
        "argv_template": argv,
        "input_schema": _schema(required),
    }


def _schema(required: list[str]) -> dict[str, Any]:
    return {"type": "object", "required": required}
