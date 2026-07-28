"""Preflight validation that keeps failed batches free of orphan tree nodes."""

from __future__ import annotations

from typing import Any

from .tree_schema import identifier, validate_binding


def validate_batch_operations(operations: list[dict[str, Any]]) -> None:
    component_ids: set[str] = set()
    binding_ids: set[str] = set()
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("report batch operation must be an object")
        if operation.get("op") == "add":
            component_id = identifier(
                str(operation.get("component_id") or ""), "component_id",
            )
            if component_id in component_ids:
                raise ValueError("report batch duplicates component_id")
            component_ids.add(component_id)
            bindings = operation.get("bindings") or []
        elif operation.get("op") == "chip":
            bindings = [operation.get("binding")]
        else:
            continue
        for value in bindings:
            binding = validate_binding(value)
            if binding["binding_id"] in binding_ids:
                raise ValueError("report batch duplicates binding_id")
            binding_ids.add(binding["binding_id"])
