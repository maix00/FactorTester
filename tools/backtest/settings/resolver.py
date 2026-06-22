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
    engine = str(local_values.get("engine", application.settings["engine"].default))
    for group_id in group_ids:
        overrides = group_values.get(group_id, {})
        values: dict[str, Any] = {}
        setting_fallbacks: list[dict[str, Any]] = []
        for key, definition in application.settings.items():
            user_provided = key in local_values or key in overrides
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
            if (
                key not in local_values
                and key not in overrides
                and engine in definition.engine_defaults
            ):
                value = definition.engine_defaults[engine]
            _validate_value(definition, value)
            value, fallback = _resolve_engine_value(
                definition,
                value,
                engine,
                user_provided=user_provided,
            )
            if fallback is not None:
                setting_fallbacks.append(fallback)
            values[key] = value
        if setting_fallbacks:
            values["_setting_fallbacks"] = setting_fallbacks
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


def _resolve_engine_value(
    definition: SettingDefinition,
    value: Any,
    engine: str,
    *,
    user_provided: bool,
) -> tuple[Any, dict[str, Any] | None]:
    disabled = set(definition.disabled_values_by_engine.get(engine, ()))
    if str(value) not in disabled:
        return value, None
    fallback = definition.engine_defaults.get(engine, definition.default)
    _validate_value(definition, fallback)
    if str(fallback) in disabled:
        raise ValueError(
            f"setting {definition.key} has no executable default for engine {engine}"
        )
    diagnostic = {
        "setting_key": definition.key,
        "module": definition.module,
        "engine": engine,
        "requested_value": value,
        "applied_value": fallback,
        "reason": "engine_disabled_value",
    } if user_provided else None
    return fallback, diagnostic
