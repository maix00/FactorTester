"""Node-local capability resolution validation."""

from __future__ import annotations

from typing import Any


def validate_resolution_against_node(
    *,
    graph: dict[str, Any],
    node: dict[str, Any],
    resolution: dict[str, Any],
) -> None:
    required_ids = set(node.get("required_capabilities") or [])
    conditional_ids = {
        str(item.get("capability_id") or "")
        for item in node.get("conditional_capabilities") or []
    }
    descriptors = graph.get("capability_descriptors") or {}
    seen: set[str] = set()
    for key, allowed_ids in (
        ("bindings", required_ids),
        ("gaps", required_ids),
        ("triggered_conditional_bindings", conditional_ids),
        ("triggered_conditional_gaps", conditional_ids),
    ):
        for binding in resolution.get(key) or []:
            capability_id = str(binding.get("capability_id") or "")
            expected = descriptors.get(capability_id)
            descriptor_matches = bool(expected) and all((
                binding.get("capability_description")
                == expected.get("capability_description"),
                binding.get("descriptor_hash")
                == expected.get("descriptor_hash"),
            ))
            if (
                capability_id not in allowed_ids
                or capability_id in seen
                or not descriptor_matches
            ):
                raise ValueError(
                    f"capability descriptor mismatch: {capability_id}"
                )
            seen.add(capability_id)
    for condition in resolution.get("undetermined_conditions") or []:
        capability_id = str(condition.get("capability_id") or "")
        if capability_id not in conditional_ids or capability_id in seen:
            raise ValueError(
                f"capability descriptor mismatch: {capability_id}"
            )
        seen.add(capability_id)


def missing_required_capabilities(
    node: dict[str, Any],
    resolution: dict[str, Any],
) -> list[str]:
    bound_capabilities = {
        str(item.get("capability_id") or "")
        for key in ("bindings", "triggered_conditional_bindings")
        for item in resolution.get(key) or []
        if isinstance(item, dict)
    }
    return sorted(
        set(node.get("required_capabilities") or []) - bound_capabilities
    )
