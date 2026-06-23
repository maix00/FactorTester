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
                    requested_value = overrides[key]
                    if requested_value != value:
                        setting_fallbacks.append({
                            "setting_key": definition.key,
                            "module": definition.module,
                            "engine": engine,
                            "requested_value": requested_value,
                            "applied_value": value,
                            "reason": "local_only_group_override",
                        })
                else:
                    value = overrides[key]
            if (
                key not in local_values
                and key not in overrides
                and engine in definition.engine_defaults
            ):
                value = definition.engine_defaults[engine]
            try:
                value = _coerce_value(definition, value)
                _validate_value(definition, value)
            except ValueError:
                if definition.key == "time_precision":
                    raise
                requested_value = value
                value = definition.engine_defaults.get(engine, definition.default)
                value = _coerce_value(definition, value)
                _validate_value(definition, value)
                if user_provided:
                    setting_fallbacks.append({
                        "setting_key": definition.key,
                        "module": definition.module,
                        "engine": engine,
                        "requested_value": requested_value,
                        "applied_value": value,
                        "reason": "invalid_setting_value",
                    })
            value, fallback = _resolve_engine_value(
                definition,
                value,
                engine,
                user_provided=user_provided,
            )
            if fallback is not None:
                setting_fallbacks.append(fallback)
            values[key] = value
        _resolve_setting_dependencies(
            application,
            values,
            engine,
            local_values,
            overrides,
            setting_fallbacks,
        )
        if setting_fallbacks:
            values["_setting_fallbacks"] = setting_fallbacks
        resolved[group_id] = values
    return resolved


def _resolve_setting_dependencies(
    application: ApplicationSettings,
    values: dict[str, Any],
    engine: str,
    local_values: Mapping[str, Any],
    overrides: Mapping[str, Any],
    setting_fallbacks: list[dict[str, Any]],
) -> None:
    timing = str(values.get("execution_timing") or "next_bar")
    basis = str(values.get("execution_price_basis") or "close")
    if timing == "same_bar" and basis == "open":
        _replace_setting_value(
            application,
            values,
            "execution_price_basis",
            "close",
            engine,
            local_values,
            overrides,
            setting_fallbacks,
            reason="incompatible_setting_value",
        )
        basis = "close"
    if basis == "vwap":
        _replace_setting_value(
            application,
            values,
            "execution_price_basis",
            "close",
            engine,
            local_values,
            overrides,
            setting_fallbacks,
            reason="unavailable_market_price_basis",
        )


def _replace_setting_value(
    application: ApplicationSettings,
    values: dict[str, Any],
    key: str,
    applied_value: Any,
    engine: str,
    local_values: Mapping[str, Any],
    overrides: Mapping[str, Any],
    setting_fallbacks: list[dict[str, Any]],
    *,
    reason: str,
) -> None:
    requested_value = values.get(key)
    if requested_value == applied_value:
        return
    definition = application.settings[key]
    values[key] = applied_value
    if key in local_values or key in overrides:
        setting_fallbacks.append({
            "setting_key": definition.key,
            "module": definition.module,
            "engine": engine,
            "requested_value": requested_value,
            "applied_value": applied_value,
            "reason": reason,
        })


def _coerce_value(definition: SettingDefinition, value: Any) -> Any:
    if definition.control_template != "number":
        return value
    if isinstance(value, bool):
        raise ValueError(f"setting {definition.key} requires a number")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"setting {definition.key} requires a number")
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"setting {definition.key} requires a number") from exc
    raise ValueError(f"setting {definition.key} requires a number")


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
