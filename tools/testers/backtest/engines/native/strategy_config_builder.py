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
    from tools.testers.backtest.engines.native.ledger import RunState

_FACTOR_MODE_FLOWS = {"signal_live", "signal_precomputed"}
_LIVE_FACTOR_SUPPORT_FLOWS = {"schedule_bar_events"}
_TERM_STRUCTURE_FLOWS = {
    "expand_term_structure",
    "resolve_tradable_target_weights",
    "register_force_close_notices",
    "register_rollover_notices",
    "handle_delivery_force_close_notice",
    "handle_rollover_notice",
}
_GROUP_STRATEGY_FLOWS = {"group_quantile_membership"}
_LONG_SHORT_STRATEGY_FLOWS = {"compose_long_short_target"}


def _all_flow_names() -> set[str]:
    names: set[str] = set()
    for cls in _ALL_MODULE_CLASSES:
        for flow in getattr(cls, "flows", ()):
            names.add(flow.name)
    return names


def _resolve_active_flow_names(resolved_settings: Mapping[str, Any]) -> frozenset[str]:
    names = _all_flow_names()
    chosen = _select_factor_flow(resolved_settings)
    excluded = _FACTOR_MODE_FLOWS - {chosen}
    if chosen != "signal_live":
        excluded |= _LIVE_FACTOR_SUPPORT_FLOWS
    if str(resolved_settings.get("engine_mode", "auto") or "auto").lower() == "basic":
        excluded |= _TERM_STRUCTURE_FLOWS
    strategy_kind = str(resolved_settings.get("strategy_kind") or "group")
    if strategy_kind == "long_short":
        excluded |= _GROUP_STRATEGY_FLOWS
    else:
        excluded |= _LONG_SHORT_STRATEGY_FLOWS
    return frozenset(names - excluded)


def _select_factor_flow(resolved_settings: Mapping[str, Any]) -> str:
    requested = str(resolved_settings.get("factor_mode", "auto") or "auto")
    if requested not in {"auto", "precomputed", "incremental"}:
        requested = "auto"
    can_vectorize = _factor_supports_vectorized(resolved_settings.get("factor"))
    if requested == "precomputed":
        if not can_vectorize:
            raise ValueError(
                "factor_mode='precomputed' requires a vectorizable factor; "
                "use factor_mode='incremental' or 'auto' for live-only factors"
            )
        return "signal_precomputed"
    if requested == "incremental":
        if not _factor_supports_incremental(resolved_settings.get("factor")):
            raise ValueError("factor_mode='incremental' requires an incrementally compilable factor")
        return "signal_live"
    if can_vectorize:
        return "signal_precomputed"
    if not _factor_supports_incremental(resolved_settings.get("factor")):
        raise ValueError("factor_mode='auto' selected live execution, but factor is not incrementally compilable")
    return "signal_live"


def _factor_supports_vectorized(factor: Any) -> bool:
    if factor is None:
        return True
    flag = getattr(factor, "supports_vectorized", None)
    if callable(flag):
        return bool(flag())
    if flag is not None:
        return bool(flag)
    expr = getattr(factor, "expression", None) or getattr(factor, "_expr", None)
    expr_flag = getattr(expr, "supports_vectorized", None)
    if callable(expr_flag):
        return bool(expr_flag())
    if expr_flag is not None:
        return bool(expr_flag)
    return True


def _factor_supports_incremental(factor: Any) -> bool:
    if factor is None:
        return True
    flag = getattr(factor, "supports_incremental", None)
    if callable(flag):
        return bool(flag())
    if flag is not None:
        return bool(flag)
    expr = getattr(factor, "expression", None) or getattr(factor, "_expr", None)
    expr_flag = getattr(expr, "supports_incremental", None)
    if callable(expr_flag):
        return bool(expr_flag())
    if expr_flag is not None:
        return bool(expr_flag)
    return True


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


def _default_value_for_field(
    fd: Any,
    resolved: Mapping[str, Any],
    materialized: Mapping[Any, Any],
    entries: list[tuple[str, Any, Any, frozenset[str]]],
) -> Any:
    values_by_name = dict(resolved)
    for field_name, ref, _fd, _owner_flow_names in entries:
        if ref in materialized:
            values_by_name[field_name] = materialized[ref]
    for source_key, mapping in (fd.default_when or {}).items():
        source_value = values_by_name.get(source_key)
        if source_value in mapping:
            return mapping[source_value]
        source_text = str(source_value)
        if source_text in mapping:
            return mapping[source_text]
    return fd.default


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
                field_values[ref] = _default_value_for_field(fd, resolved, field_values, entries)
        configs[strategy] = StrategyConfig(
            strategy=strategy, active_flow_names=active_flow_names, field_values=field_values,
        )
    return configs


def apply_strategy_configs(account: "RunState", resolved_settings_by_alias: Mapping[str, Mapping[str, Any]]) -> None:
    account.strategy_configs = build_strategy_configs(resolved_settings_by_alias)
