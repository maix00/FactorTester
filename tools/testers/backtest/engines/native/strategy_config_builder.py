"""Step 3.0 bootstrap: builds `account.strategy_configs` from already-resolved
per-strategy settings dicts (the OLD ApplicationSettings/candidate-list/
broadcast+override machinery in `tools/testers/settings` has already run by
the time this is called — group/local settings resolution, factor/product-
path candidate selection, fallback chains, etc. This function does NOT
re-implement any of that; it only bridges the resulting flat dict of
{setting_key: value} per strategy into `StrategyConfig.field_values`, keyed
by the matching ExecutableModule FieldRef.

This is intentionally not any ExecutableModule's own Flow -- it's the one
piece of strategy-config resolution that isn't "owned" by a specific module
(no module both produces and consumes the entire settings dict), so it lives
at the scheduler-bootstrap level per the plan's step 3.0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from tools.testers.backtest.engines.native.ledger import StrategyConfig
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.ledger import AccountState

# Flow-name variants that are mutually exclusive within one module --
# `factor_mode` (an existing frontend setting, register_factor_execution_base)
# selects which one a strategy activates. "auto" has no real frequency-based
# heuristic implemented yet -- defaults to "signal_precomputed" (the cheaper,
# more common case) until one is built.
_FACTOR_MODE_TO_FLOW_NAME = {
    "precomputed": "signal_precomputed",
    "incremental": "signal_live",
    "auto": "signal_precomputed",
}


def _all_flow_names() -> set[str]:
    names: set[str] = set()
    for cls in _ALL_MODULE_CLASSES:
        for flow in getattr(cls, "flows", ()):
            names.add(flow.name)
    return names


def _resolve_active_flow_names(resolved_settings: Mapping[str, Any]) -> frozenset[str]:
    names = _all_flow_names()
    factor_mode = str(resolved_settings.get("factor_mode", "auto"))
    chosen = _FACTOR_MODE_TO_FLOW_NAME.get(factor_mode, "signal_precomputed")
    excluded = {"signal_live", "signal_precomputed"} - {chosen}
    return frozenset(names - excluded)


def _field_entries() -> list[tuple[str, Any, Any, frozenset[str]]]:
    """One entry per registered field: (field_name, FieldRef, FieldDefinition,
    owning module's Flow names). The Flow-name set is what
    `frontend_only_default` enforcement checks against `active_flow_names`
    to decide whether a missing value actually matters for this strategy."""
    entries: list[tuple[str, Any, Any, frozenset[str]]] = []
    for cls in _ALL_MODULE_CLASSES:
        owner_flow_names = frozenset(flow.name for flow in getattr(cls, "flows", ()))
        for field_name, fd in getattr(cls, "fields", {}).items():
            ref = getattr(cls, field_name, None)
            if ref is not None:
                entries.append((field_name, ref, fd, owner_flow_names))
    return entries


def build_strategy_configs(
    resolved_settings_by_alias: Mapping[str, Mapping[str, Any]],
) -> dict[Strategy, StrategyConfig]:
    """`resolved_settings_by_alias`: {shortAlias: {setting_key: value, ...}}
    -- one raw dict per strategy, taken directly from the frontend's
    flat_groups rows (NOT pre-defaulted by the old resolve_group_settings
    pipeline -- this function needs to tell "explicitly provided" apart from
    "missing", which a pre-defaulted dict would have already erased).

    For a field marked `frontend_only_default=True` (its `default` is a UI
    suggestion only): if a strategy activates any Flow owned by that field's
    module and the field is absent from that strategy's raw dict, this
    raises -- the old behavior of silently substituting the UI default was
    exactly the bug being fixed here. For an ordinary field, a missing value
    is materialized using `default` (a real, deliberate backend fallback).
    """
    entries = _field_entries()
    configs: dict[Strategy, StrategyConfig] = {}
    for alias, resolved in resolved_settings_by_alias.items():
        strategy = Strategy(alias=alias)
        active_flow_names = _resolve_active_flow_names(resolved)
        field_values: dict[Any, Any] = {}
        for field_name, ref, fd, owner_flow_names in entries:
            if field_name in resolved:
                field_values[ref] = resolved[field_name]
                continue
            module_active = bool(owner_flow_names & active_flow_names)
            if fd.frontend_only_default and module_active:
                raise ValueError(
                    f"strategy {alias!r} activates {ref.owner} but did not supply "
                    f"a value for required field {field_name!r} (its default is "
                    f"a frontend display suggestion only, not a backend fallback)")
            if not fd.frontend_only_default:
                field_values[ref] = fd.default
        configs[strategy] = StrategyConfig(
            strategy=strategy, active_flow_names=active_flow_names, field_values=field_values,
        )
    return configs


def apply_strategy_configs(account: "AccountState", resolved_settings_by_alias: Mapping[str, Mapping[str, Any]]) -> None:
    account.strategy_configs = build_strategy_configs(resolved_settings_by_alias)
