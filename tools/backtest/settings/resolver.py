"""Resolve schema defaults, local values, and sparse group overrides."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import ScopePolicy, SettingDefinition
from .registry import ApplicationSettings


def resolve_group_settings(
    application: ApplicationSettings,
    *,
    local_values: Mapping[str, Any],
    group_values: Mapping[str, Mapping[str, Any]],
    group_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Build complete settings using default -> local -> group precedence."""
    unknown_local = set(local_values) - application.settings.keys()
    unknown_group = {
        key for values in group_values.values() for key in values
    } - application.settings.keys()
    if unknown_local or unknown_group:
        raise ValueError(
            f"unknown backtest settings: {sorted(unknown_local | unknown_group)}"
        )
    if set(group_values) - set(group_ids):
        raise ValueError("group settings contain unknown group ids")

    resolved: dict[str, dict[str, Any]] = {}
    for group_id in group_ids:
        overrides = group_values.get(group_id, {})
        values: dict[str, Any] = {}
        for key, definition in application.settings.items():
            if (
                definition.scope_policy == ScopePolicy.GROUP_ONLY
                and key in local_values
            ):
                raise ValueError(f"group-only setting {key} cannot be set locally")
            value = local_values.get(key, definition.default)
            if key in overrides:
                if definition.scope_policy == ScopePolicy.LOCAL_ONLY:
                    raise ValueError(f"local-only setting {key} cannot be overridden")
                value = overrides[key]
            _validate_value(definition, value)
            values[key] = value
        resolved[group_id] = values
    return resolved


def _validate_value(definition: SettingDefinition, value: Any) -> None:
    if definition.options and value not in {option.value for option in definition.options}:
        raise ValueError(f"invalid value for {definition.key}: {value!r}")
    if definition.control_template == "number":
        if not isinstance(value, (int, float)):
            raise ValueError(f"setting {definition.key} requires a number")
        if definition.minimum is not None and value < definition.minimum:
            raise ValueError(f"setting {definition.key} is below minimum")
        if definition.maximum is not None and value > definition.maximum:
            raise ValueError(f"setting {definition.key} is above maximum")
