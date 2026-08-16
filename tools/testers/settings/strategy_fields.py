"""Registered group-strategy setting keys and validation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .applications import backtest_setting_registry

GROUP_TEST_APPLICATION = "group_test"

ALLOCATION_POLICY = "allocation_policy"
REBALANCE_TRIGGER = "rebalance_trigger"
POSITION_POLICY = "position_policy"
EXECUTION_TIMING = "execution_timing"
EXECUTION_PRICE_BASIS = "execution_price_basis"
EXECUTION_DELAY_BARS = "execution_delay_bars"
OBSOLETE_REBALANCE_MODE = "rebalance_mode"


def registered_option_values(key: str) -> frozenset[str]:
    """Return allowed option values from the backend settings registry."""

    app = backtest_setting_registry.get(GROUP_TEST_APPLICATION)
    defaults = app.manifest().get("defaults") or {}
    item = defaults.get(key) or {}
    options = item.get("value_descriptor", {}).get("options") or []
    values = frozenset(str(option.get("value")) for option in options if "value" in option)
    if values:
        return values
    field = _registered_module_field(key)
    if field is None:
        return frozenset()
    descriptor = field.descriptor_for(key)
    return frozenset(str(value) for value, _label in descriptor.options)


def registered_default_value(key: str) -> Any:
    """Return the default value from the backend settings registry."""

    app = backtest_setting_registry.get(GROUP_TEST_APPLICATION)
    defaults = app.manifest().get("defaults") or {}
    item = defaults.get(key) or {}
    if "value" not in item:
        field = _registered_module_field(key)
        if field is None:
            raise ValueError(f"missing registered default for strategy setting: {key}")
        return field.default
    return item["value"]


def _registered_module_field(key: str) -> Any | None:
    from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES

    for cls in _ALL_MODULE_CLASSES:
        field = getattr(cls, "fields", {}).get(key)
        if field is not None:
            return field
    return None


def strategy_value(config: Mapping[str, Any], key: str) -> str:
    """Read a strategy setting, falling back to the registered default."""

    value = config[key] if key in config else registered_default_value(key)
    value = str(value)
    allowed = registered_option_values(key)
    if allowed and value not in allowed:
        raise ValueError(f"unsupported {key}: {value}")
    return value


def required_strategy_value(config: Mapping[str, Any], key: str) -> str:
    """Read a required strategy setting that must have been resolved by registry."""

    if key not in config:
        raise ValueError(f"missing registered strategy setting: {key}")
    return strategy_value(config, key)


def validate_resolved_strategy_settings(config: Mapping[str, Any]) -> None:
    """Validate that runtime strategy config uses the registered split semantics."""

    if OBSOLETE_REBALANCE_MODE in config:
        raise ValueError(
            f"{OBSOLETE_REBALANCE_MODE} is obsolete; use "
            f"{REBALANCE_TRIGGER} and {POSITION_POLICY}"
        )
    required_strategy_value(config, REBALANCE_TRIGGER)
    required_strategy_value(config, POSITION_POLICY)
    strategy_value(config, EXECUTION_TIMING)
    strategy_value(config, EXECUTION_PRICE_BASIS)
