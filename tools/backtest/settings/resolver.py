"""Resolve shared and per-strategy values without implicit compatibility rules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import ScopePolicy, SettingDefinition, SettingScope
from .registry import ApplicationSettings


def resolve_strategy_settings(
    application: ApplicationSettings,
    *,
    scopes: Mapping[str, str],
    shared_values: Mapping[str, Any],
    strategy_values: Mapping[str, Mapping[str, Any]],
    strategy_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    unknown = (
        set(scopes) | set(shared_values) |
        {key for values in strategy_values.values() for key in values}
    ) - application.settings.keys()
    if unknown:
        raise ValueError(f"unknown backtest settings: {sorted(unknown)}")
    if set(strategy_values) - set(strategy_ids):
        raise ValueError("strategy settings contain unknown strategy ids")

    selected_scopes = {
        key: _resolve_scope(definition, scopes.get(key))
        for key, definition in application.settings.items()
    }
    resolved = {}
    for strategy_id in strategy_ids:
        values = {}
        overrides = strategy_values.get(strategy_id, {})
        for key, definition in application.settings.items():
            scope = selected_scopes[key]
            if scope == SettingScope.SHARED:
                value = shared_values.get(key, definition.default)
                if key in overrides:
                    raise ValueError(f"shared setting {key} cannot be overridden by {strategy_id}")
            else:
                value = overrides.get(key, definition.default)
                if key in shared_values:
                    raise ValueError(f"strategy setting {key} cannot be supplied as shared")
            _validate_value(definition, value)
            values[key] = value
        resolved[strategy_id] = values
    return resolved


def _resolve_scope(definition: SettingDefinition, requested: str | None) -> SettingScope:
    scope = definition.default_scope if requested is None else SettingScope(requested)
    if definition.scope_policy == ScopePolicy.SHARED_ONLY and scope != SettingScope.SHARED:
        raise ValueError(f"setting {definition.key} is shared-only")
    if definition.scope_policy == ScopePolicy.STRATEGY_ONLY and scope != SettingScope.STRATEGY:
        raise ValueError(f"setting {definition.key} is strategy-only")
    return scope


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
