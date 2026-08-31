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
    engine = str(local_values.get("engine", _default(application.settings["engine"])))
    for group_id in group_ids:
        overrides = group_values.get(group_id, {})
        values: dict[str, Any] = {}
        setting_fallbacks: list[dict[str, Any]] = []
        for key, definition in application.settings.items():
            user_provided = _effective_user_value_present(
                definition,
                key=key,
                local_values=local_values,
                overrides=overrides,
            )
            if (
                definition.scope_policy == ScopePolicy.GROUP_ONLY
                and key in local_values
            ):
                raise ValueError(f"group-only setting {key} cannot be set locally")
            value = local_values.get(key, _default(definition))
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
                            "reason": "local_only_group_value_ignored",
                        })
                else:
                    value = overrides[key]
            rules = _rules(definition)
            if not user_provided:
                conditional_default = _conditional_default(
                    application,
                    definition,
                    values=values,
                    local_values=local_values,
                    overrides=overrides,
                )
                if conditional_default is not _NO_CONDITIONAL_DEFAULT:
                    value = conditional_default
                elif engine in rules.engine_defaults:
                    value = rules.engine_defaults[engine]
            elif not _conditions_match(
                application,
                rules.editable_if,
                values=values,
                local_values=local_values,
                overrides=overrides,
            ):
                requested_value = value
                value = _conditional_default(
                    application,
                    definition,
                    values=values,
                    local_values=local_values,
                    overrides=overrides,
                )
                if value is _NO_CONDITIONAL_DEFAULT:
                    value = _default(definition)
                if requested_value != value:
                    setting_fallbacks.append({
                        "setting_key": definition.key,
                        "module": definition.module,
                        "engine": engine,
                        "requested_value": requested_value,
                        "applied_value": value,
                        "reason": "non_editable_value_ignored",
                    })
            try:
                value = _coerce_value(definition, value)
                _validate_value(definition, value)
            except ValueError:
                if user_provided:
                    raise
                value = rules.engine_defaults.get(engine, _default(definition))
                value = _coerce_value(definition, value)
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


_NO_CONDITIONAL_DEFAULT = object()


def _effective_user_value_present(
    definition: SettingDefinition,
    *,
    key: str,
    local_values: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> bool:
    """Return whether the selected scope supplies an effective value.

    A group override for a ``LOCAL_ONLY`` field is intentionally ignored.  It
    must therefore not suppress that field's registered conditional default.
    """
    if key in local_values:
        return True
    return key in overrides and definition.scope_policy != ScopePolicy.LOCAL_ONLY


def _condition_value(
    application: ApplicationSettings,
    key: str,
    *,
    values: Mapping[str, Any],
    local_values: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> Any:
    """Read a dependency using the same local/group precedence as settings."""
    if key in values:
        return values[key]
    definition = application.settings.get(key)
    if definition is None:
        return None
    if key in overrides and definition.scope_policy != ScopePolicy.LOCAL_ONLY:
        return overrides[key]
    if key in local_values:
        return local_values[key]
    return _default(definition)


def _conditions_match(
    application: ApplicationSettings,
    conditions: Mapping[str, Any],
    *,
    values: Mapping[str, Any],
    local_values: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> bool:
    """Evaluate registered conditions as an AND of dependency predicates."""
    for dependency, allowed_values in conditions.items():
        actual = _condition_value(
            application,
            dependency,
            values=values,
            local_values=local_values,
            overrides=overrides,
        )
        allowed = (
            allowed_values
            if isinstance(allowed_values, (tuple, list, set, frozenset))
            else (allowed_values,)
        )
        if actual not in allowed and str(actual) not in {str(item) for item in allowed}:
            return False
    return True


def _conditional_default(
    application: ApplicationSettings,
    definition: SettingDefinition,
    *,
    values: Mapping[str, Any],
    local_values: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> Any:
    """Resolve the first matching registered conditional default.

    The registration order is the priority order.  This matters when a broad
    engine default and a more specific profile default are both declared: the
    field owner can put the broad rule first and the profile rule second only
    when the latter is intended to win.  Current built-ins intentionally use
    engine rules first, so ``basic`` remains authoritative over a profile.
    """
    for dependency, mapping in _rules(definition).default_if.items():
        actual = _condition_value(
            application,
            dependency,
            values=values,
            local_values=local_values,
            overrides=overrides,
        )
        if actual in mapping:
            return mapping[actual]
        actual_text = str(actual)
        for expected, candidate in mapping.items():
            if str(expected) == actual_text:
                return candidate
    return _NO_CONDITIONAL_DEFAULT


def _resolve_setting_dependencies(
    application: ApplicationSettings,
    values: dict[str, Any],
    engine: str,
    local_values: Mapping[str, Any],
    overrides: Mapping[str, Any],
    setting_fallbacks: list[dict[str, Any]],
) -> None:
    # Order timing/price-basis are no longer public settings.  The executable
    # modules own their fixed next-bar-open defaults internally; settings
    # resolution only manages backend-registered user-visible fields.
    _ = (application, values, engine, local_values, overrides, setting_fallbacks)


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
    descriptor = definition.value_descriptor
    if descriptor is None or descriptor.value_type not in {"integer", "number"}:
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
    descriptor = definition.value_descriptor
    if descriptor is not None and descriptor.options:
        supported = {option[0] for option in descriptor.options}
        values = (
            value if descriptor.cardinality == "many"
            and isinstance(value, (list, tuple)) else (value,)
        )
        unsupported = [item for item in values if item not in supported]
        if unsupported:
            raise ValueError(f"invalid value for {definition.key}: {unsupported!r}")
    if descriptor is not None and descriptor.value_type in {"integer", "number"}:
        if not isinstance(value, (int, float)):
            raise ValueError(f"setting {definition.key} requires a number")
        if descriptor.minimum is not None and value < descriptor.minimum:
            raise ValueError(f"setting {definition.key} is below minimum")
        if descriptor.maximum is not None and value > descriptor.maximum:
            raise ValueError(f"setting {definition.key} is above maximum")


def _resolve_engine_value(
    definition: SettingDefinition,
    value: Any,
    engine: str,
    *,
    user_provided: bool,
) -> tuple[Any, dict[str, Any] | None]:
    rules = _rules(definition)
    disabled = set(rules.disabled_values.get(engine, ()))
    if str(value) not in disabled:
        return value, None
    fallback = rules.engine_defaults.get(engine, _default(definition))
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


def _field_spec(definition: SettingDefinition):
    return definition.field_spec()


def _rules(definition: SettingDefinition):
    spec = _field_spec(definition)
    assert spec.setting is not None
    return spec.setting.rules


def _default(definition: SettingDefinition) -> Any:
    spec = _field_spec(definition)
    assert spec.setting is not None
    return spec.setting.default
