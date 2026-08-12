"""Resolve the narrowest authored container for historical obligation changes."""

from __future__ import annotations

from typing import Any


_CONTAINER_KINDS = {"chapter", "section", "subsection", "special"}


def obligation_parents(
    *,
    contexts: list[dict[str, Any]],
    fallback_by_step: dict[str, str],
    snapshot: dict[str, Any],
) -> tuple[dict[str, str], list[str]]:
    """Prefer an explicit checkpoint component; record chapter fallbacks."""
    components = {
        str(item["component_id"]): item
        for item in snapshot["components"]
    }
    bound: dict[str, list[str]] = {}
    for binding in snapshot["bindings"]:
        step_ref = str(binding.get("target_ref") or "")
        component_id = str(binding.get("component_id") or "")
        component = components.get(component_id)
        if (
            binding.get("kind") != "checkpoint"
            or step_ref not in fallback_by_step
            or (binding.get("data") or {}).get("role") == "checkpoint_receipt"
            or component is None
            or component.get("display_kind") == "obligation_changes"
        ):
            continue
        parent = _nearest_container(component_id, components)
        if parent:
            bound.setdefault(step_ref, []).append(parent)
    result: dict[str, str] = {}
    fallback_steps: list[str] = []
    for context in contexts:
        step_ref = str(context["step_ref"])
        if context.get("side") != "target" or not context.get(
            "obligation_changes"
        ):
            continue
        candidates = list(dict.fromkeys(bound.get(step_ref) or []))
        deepest = _deepest_unique(candidates, components)
        if deepest:
            result[step_ref] = deepest
        else:
            result[step_ref] = fallback_by_step[step_ref]
            fallback_steps.append(step_ref)
    return result, fallback_steps


def _nearest_container(
    component_id: str,
    components: dict[str, dict[str, Any]],
) -> str:
    current = component_id
    seen: set[str] = set()
    while current:
        if current in seen:
            raise ValueError("report hierarchy contains a parent cycle")
        seen.add(current)
        component = components.get(current)
        if component is None:
            return ""
        if component["kind"] in _CONTAINER_KINDS:
            return current
        current = str(component.get("parent_id") or "")
    return ""


def _deepest_unique(
    candidates: list[str],
    components: dict[str, dict[str, Any]],
) -> str:
    if not candidates:
        return ""
    depths = {candidate: _depth(candidate, components) for candidate in candidates}
    maximum = max(depths.values())
    values = [candidate for candidate, depth in depths.items() if depth == maximum]
    return values[0] if len(values) == 1 else ""


def _depth(
    component_id: str,
    components: dict[str, dict[str, Any]],
) -> int:
    depth = 0
    current = component_id
    seen: set[str] = set()
    while current:
        if current in seen:
            raise ValueError("report hierarchy contains a parent cycle")
        seen.add(current)
        component = components.get(current)
        if component is None:
            break
        depth += 1
        current = str(component.get("parent_id") or "")
    return depth
