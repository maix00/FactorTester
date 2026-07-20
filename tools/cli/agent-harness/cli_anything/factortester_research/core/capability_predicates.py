"""Bounded, deterministic predicates for conditional capabilities."""

from __future__ import annotations

from typing import Any


_UNKNOWN = object()


def _fact_value(facts: dict[str, Any], field: str) -> Any:
    value: Any = facts
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return _UNKNOWN
        value = value[part]
    return value


def evaluate_capability_predicate(
    predicate: dict[str, Any],
    facts: dict[str, Any],
) -> bool | None:
    """Evaluate a bounded predicate; None means semantic judgment is needed."""
    if not isinstance(predicate, dict):
        raise ValueError("capability predicate must be an object")
    if "any" in predicate:
        values = [
            evaluate_capability_predicate(item, facts)
            for item in predicate["any"]
        ]
        if any(value is True for value in values):
            return True
        if all(value is False for value in values):
            return False
        return None
    if "all" in predicate:
        values = [
            evaluate_capability_predicate(item, facts)
            for item in predicate["all"]
        ]
        if any(value is False for value in values):
            return False
        if all(value is True for value in values):
            return True
        return None
    field = str(predicate.get("field") or "")
    if not field:
        raise ValueError("leaf predicate requires field")
    value = _fact_value(facts, field)
    if value is _UNKNOWN:
        return None
    if "equals" in predicate:
        return value == predicate["equals"]
    if "in" in predicate:
        choices = predicate["in"]
        if not isinstance(choices, list):
            raise ValueError("predicate in must be an array")
        return value in choices
    if "contains_any" in predicate:
        choices = predicate["contains_any"]
        if not isinstance(choices, list):
            raise ValueError("predicate contains_any must be an array")
        if not isinstance(value, (list, tuple, set)):
            return False
        return any(item in value for item in choices)
    if "greater_than" in predicate:
        threshold = predicate["greater_than"]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not isinstance(threshold, (int, float))
            or isinstance(threshold, bool)
        ):
            raise ValueError(
                "predicate greater_than requires numeric value and threshold"
            )
        return value > threshold
    raise ValueError("unsupported capability predicate operator")
