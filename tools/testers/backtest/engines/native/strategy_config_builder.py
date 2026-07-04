"""Step 3.0 bootstrap: builds `state.strategy_configs` from already-resolved
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

from tools.testers.backtest.engines.native.ledger import (
    LedgerConfig,
    Ledger,
    StrategyConfig,
    ledger_config_field_values,
    ledger_config_from_mapping,
    ledger_identity,
    merge_ledger_configs,
)
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES
from tools.testers.backtest.modules.strategy_book import StrategyBookSimple, materialize_strategy_book_store
from tools.testers.settings.counterparty import (
    CounterPartyProfile,
    counterparty_profile,
    resolve_counterparty_profiles_by_ledger,
)

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.ledger import BacktestRunState

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
_DAILY_MARK_TO_MARKET_FLOWS = {
    "register_daily_mark_to_market_notices",
    "apply_daily_mark_to_market",
}
_MARGIN_NOTICE_FLOWS = {
    "register_margin_check_notices",
    "apply_margin_requirement_change",
    "handle_margin_liquidation_notice",
}
_LEDGER_LOOKUP_FLOWS = {
    "lookup_current_prices_on_ledger",
    "lookup_historical_fields_on_ledger",
}
_LEDGER_OWNED_SETTING_NAMES = {
    "initial_capital_major",
    "base_currency",
    "fee_mode",
    "fixed_fee_rate",
    "margin_mode",
    "fixed_margin_ratio",
    "accounting_mode",
    "daily_mark_to_market_enabled",
    "cost_basis_method",
    "use_int_position",
    "tradability_policy",
    "clearing_rounding_policy",
    "cash_reserve_ratio",
    "cash_reserve_major",
    "margin_call_mode",
    "liquidation_target_buffer",
}
_LEDGER_INFERRED_SETTING_NAMES = {
    # In Auto/Exact accounting, this is inferred from historical trading-rule
    # fields at the ledger/product timestamp. Materializing the UI default here
    # would short-circuit that inference and make every auto ledger behave as
    # explicitly enabled/disabled.
    "daily_mark_to_market_enabled",
}


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
    uses_dmtm = _uses_daily_mark_to_market_flow(resolved_settings)
    uses_margin_notice = _uses_margin_notice_flow(resolved_settings)
    if not uses_dmtm:
        excluded |= _DAILY_MARK_TO_MARKET_FLOWS
    if not uses_margin_notice:
        excluded |= _MARGIN_NOTICE_FLOWS
    if not (uses_dmtm or uses_margin_notice):
        excluded |= _LEDGER_LOOKUP_FLOWS
    strategy_kind = str(resolved_settings.get("strategy_kind") or "group")
    if strategy_kind == "long_short":
        excluded |= _GROUP_STRATEGY_FLOWS
    else:
        excluded |= _LONG_SHORT_STRATEGY_FLOWS
    return frozenset(names - excluded)


def _uses_daily_mark_to_market_flow(resolved_settings: Mapping[str, Any]) -> bool:
    engine_mode = str(resolved_settings.get("engine_mode", "auto") or "auto").lower()
    if engine_mode == "basic":
        return False
    if engine_mode in {"auto", "exact"}:
        return True
    accounting_mode = str(resolved_settings.get("accounting_mode", "Auto") or "Auto")
    if accounting_mode == "Basic":
        return False
    if accounting_mode == "Custom":
        return bool(resolved_settings.get("daily_mark_to_market_enabled", False))
    return True


def _uses_margin_notice_flow(resolved_settings: Mapping[str, Any]) -> bool:
    engine_mode = str(resolved_settings.get("engine_mode", "auto") or "auto").lower()
    if engine_mode == "basic":
        return False
    margin_mode = str(resolved_settings.get("margin_mode", "auto") or "auto").lower()
    if margin_mode in {"none", "zero"}:
        return False
    margin_call_mode = str(resolved_settings.get("margin_call_mode", "auto") or "auto").lower()
    return margin_call_mode != "off"


def _select_factor_flow(resolved_settings: Mapping[str, Any]) -> str:
    requested = str(resolved_settings.get("factor_mode", "auto") or "auto")
    if requested not in {"auto", "precomputed", "incremental"}:
        raise ValueError(f"unsupported factor_mode: {requested!r}")
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
    Flow names that materially consume that field). The Flow-name set is what
    `frontend_only_default` enforcement checks against `active_flow_names`
    to decide whether a missing value actually matters for this strategy."""
    entries: list[tuple[str, Any, Any, frozenset[str]]] = []
    for cls in _ALL_MODULE_CLASSES:
        module_flow_names = frozenset(flow.name for flow in getattr(cls, "flows", ()))
        for field_name, fd in getattr(cls, "fields", {}).items():
            ref = getattr(cls, field_name, None)
            if ref is not None:
                consuming_flow_names = frozenset(
                    flow.name for flow in getattr(cls, "flows", ())
                    if ref in getattr(flow, "inputs", ())
                )
                entries.append((field_name, ref, fd, consuming_flow_names or module_flow_names))
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
    *,
    flow_settings_by_alias: Mapping[str, Mapping[str, Any]] | None = None,
    strategies_by_alias: Mapping[str, Strategy] | None = None,
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
        flow_resolved = flow_settings_by_alias.get(alias, resolved) if flow_settings_by_alias else resolved
        strategy = strategies_by_alias.get(alias, Strategy(alias=alias)) if strategies_by_alias else Strategy(alias=alias)
        active_flow_names = _resolve_active_flow_names(flow_resolved)
        field_values: dict[Any, Any] = {}
        for field_name, ref, fd, owner_flow_names in entries:
            if field_name in resolved:
                if field_name in _LEDGER_OWNED_SETTING_NAMES:
                    continue
                field_values[ref] = resolved[field_name]
                continue
            if field_name in _LEDGER_OWNED_SETTING_NAMES:
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


def apply_strategy_configs(
    state: "BacktestRunState",
    resolved_settings_by_alias: Mapping[str, Mapping[str, Any]],
    *,
    strategy_book: object | None = None,
    ledger_configs: Mapping[str, Mapping[str, Any] | LedgerConfig] | None = None,
    counterparty: str | CounterPartyProfile | None = None,
    counterparty_by_strategy: Mapping[str, str | CounterPartyProfile | None] | None = None,
    counterparty_by_ledger: Mapping[str, str | CounterPartyProfile | None] | None = None,
) -> None:
    book = strategy_book or StrategyBookSimple()
    resolved = {str(alias): dict(settings) for alias, settings in resolved_settings_by_alias.items()}
    strategy_objects = {alias: Strategy(alias=alias) for alias in resolved}
    materialize_strategy_book_store(state, book, strategy_objects)
    state.ledger_configs = _resolve_ledger_configs(
        resolved,
        state=state,
        strategies_by_alias=strategy_objects,
        ledger_configs=ledger_configs,
        counterparty=counterparty,
        counterparty_by_strategy=counterparty_by_strategy,
        counterparty_by_ledger=counterparty_by_ledger,
    )
    flow_settings = _flow_settings_with_ledger_configs(resolved, state, strategy_objects, state.ledger_configs)
    state.strategy_configs = build_strategy_configs(
        resolved,
        flow_settings_by_alias=flow_settings,
        strategies_by_alias=strategy_objects,
    )


def _resolve_ledger_configs(
    resolved_settings_by_alias: Mapping[str, Mapping[str, Any]],
    *,
    state: "BacktestRunState",
    strategies_by_alias: Mapping[str, Strategy],
    ledger_configs: Mapping[str, Mapping[str, Any] | LedgerConfig] | None,
    counterparty: str | CounterPartyProfile | None,
    counterparty_by_strategy: Mapping[str, str | CounterPartyProfile | None] | None,
    counterparty_by_ledger: Mapping[str, str | CounterPartyProfile | None] | None,
) -> dict[Ledger, LedgerConfig]:
    from tools.testers.backtest.modules.strategy_book import strategy_book_store_for

    store = strategy_book_store_for(state)
    entries = _field_entries()
    explicit = {
        str(ledger_id): ledger_config_from_mapping(config)
        for ledger_id, config in (ledger_configs or {}).items()
    }
    profiles = resolve_counterparty_profiles_by_ledger(
        resolved_settings_by_alias,
        ledger_ids_by_alias={
            alias: tuple(sorted(ledger.name for ledger in store.ledgers_for_strategy(state, strategy)))
            for alias, strategy in strategies_by_alias.items()
        },
        counterparty=counterparty,
        counterparty_by_strategy=counterparty_by_strategy,
        counterparty_by_ledger=counterparty_by_ledger,
    )
    default_settings_by_ledger: dict[str, LedgerConfig] = {}
    explicit_settings_by_ledger: dict[str, LedgerConfig] = {}
    for alias, settings in resolved_settings_by_alias.items():
        strategy = strategies_by_alias[str(alias)]
        active_flow_names = _resolve_active_flow_names(settings)
        materialized = _materialized_ledger_owned_settings(settings, active_flow_names, entries)
        explicit_ledger_owned = {
            key: settings[key]
            for key in _LEDGER_OWNED_SETTING_NAMES
            if key in settings
        }
        default_config = ledger_config_from_mapping({
            key: value
            for key, value in materialized.items()
            if key not in explicit_ledger_owned
        })
        explicit_config = ledger_config_from_mapping(explicit_ledger_owned)
        for ledger in store.ledgers_for_strategy(state, strategy):
            _merge_strategy_ledger_config(
                default_settings_by_ledger,
                ledger.name,
                default_config,
                source=f"strategy {alias!r}",
            )
            _merge_strategy_ledger_config(
                explicit_settings_by_ledger,
                ledger.name,
                explicit_config,
                source=f"strategy {alias!r}",
            )
    ledger_ids = {
        ledger.name
        for strategy in strategies_by_alias.values()
        for ledger in store.ledgers_for_strategy(state, strategy)
    } | set(explicit) | set(profiles)
    result: dict[Ledger, LedgerConfig] = {}
    for ledger_id in ledger_ids:
        profile_config = _ledger_config_from_counterparty_profile(profiles.get(str(ledger_id)))
        result[ledger_identity(ledger_id)] = merge_ledger_configs(
            default_settings_by_ledger.get(str(ledger_id), LedgerConfig()),
            profile_config,
            explicit_settings_by_ledger.get(str(ledger_id), LedgerConfig()),
            explicit.get(str(ledger_id), LedgerConfig()),
        )
    return result


def _merge_strategy_ledger_config(
    target: dict[str, LedgerConfig],
    ledger_id: str,
    config: LedgerConfig,
    *,
    source: str,
) -> None:
    if not ledger_config_field_values(config):
        return
    existing = target.get(ledger_id)
    if existing is None:
        target[ledger_id] = config
        return
    _raise_on_conflicting_ledger_config(existing, config, ledger_id=ledger_id, source=source)
    target[ledger_id] = merge_ledger_configs(existing, config)


def _materialized_ledger_owned_settings(
    resolved: Mapping[str, Any],
    active_flow_names: frozenset[str],
    entries: list[tuple[str, Any, Any, frozenset[str]]],
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    materialized_refs: dict[Any, Any] = {}
    for field_name, ref, fd, owner_flow_names in entries:
        if field_name not in _LEDGER_OWNED_SETTING_NAMES:
            continue
        if field_name in resolved:
            value = resolved[field_name]
        else:
            if field_name in _LEDGER_INFERRED_SETTING_NAMES:
                continue
            module_active = bool(owner_flow_names & active_flow_names)
            if fd.frontend_only_default and module_active:
                raise ValueError(
                    f"ledger-owned field {field_name!r} is required because {ref.owner} is active "
                    "but only has a frontend display default"
                )
            if fd.frontend_only_default:
                continue
            value = _default_value_for_field(fd, resolved, materialized_refs, entries)
        values[field_name] = value
        materialized_refs[ref] = value
    return values


def _raise_on_conflicting_ledger_config(left: LedgerConfig, right: LedgerConfig, *, ledger_id: str, source: str) -> None:
    for key in _LEDGER_OWNED_SETTING_NAMES:
        left_value = getattr(left, key, None)
        right_value = getattr(right, key, None)
        if left_value is None or right_value is None or left_value == right_value:
            continue
        raise ValueError(
            f"ledger {ledger_id!r} receives conflicting {key}: {left_value!r} vs {right_value!r} from {source}"
        )


def _ledger_config_from_counterparty_profile(profile_id: str | None) -> LedgerConfig:
    if not profile_id:
        return LedgerConfig()
    profile = counterparty_profile(profile_id)
    if profile is None:
        raise ValueError(f"unknown counterparty profile: {profile_id!r}")
    values: dict[str, Any] = {}
    for ref, value in profile.field_defaults.items():
        values[ref.name] = value
    return ledger_config_from_mapping(values)


def _flow_settings_with_ledger_configs(
    resolved_settings_by_alias: Mapping[str, Mapping[str, Any]],
    state: "BacktestRunState",
    strategies_by_alias: Mapping[str, Strategy],
    ledger_configs: Mapping[Ledger, LedgerConfig],
) -> dict[str, dict[str, Any]]:
    from tools.testers.backtest.modules.strategy_book import strategy_book_store_for

    store = strategy_book_store_for(state)
    result = {str(alias): dict(settings) for alias, settings in resolved_settings_by_alias.items()}
    for alias, settings in result.items():
        strategy = strategies_by_alias[alias]
        values_by_field: dict[str, set[Any]] = {}
        for ledger in store.ledgers_for_strategy(state, strategy):
            for key, value in ledger_config_field_values(
                ledger_configs.get(ledger, LedgerConfig())
            ).items():
                values_by_field.setdefault(key, set()).add(value)
        for key, values in values_by_field.items():
            if key in settings:
                continue
            if len(values) > 1:
                raise ValueError(
                    f"strategy {alias!r} maps to ledgers with conflicting {key}: "
                    f"{sorted(str(value) for value in values)}"
                )
            settings[key] = next(iter(values))
    return result
