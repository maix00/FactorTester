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

from tools.testers.backtest.engines.native.config import (
    LedgerConfig,
    StrategyConfig,
    ledger_config_field_values,
    ledger_config_from_mapping,
    merge_ledger_configs,
)
from tools.testers.backtest.engines.native.ledger import Ledger, ledger_identity
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES
from tools.testers.backtest.modules.strategy_book import StrategyBookSimple, materialize_strategy_book_store
from tools.testers.settings.counterparty import (
    CounterPartyProfile,
    counterparty_profile,
    resolve_counterparty_profiles_by_ledger,
)

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.state import BacktestRunState

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
_THRESHOLD_STRATEGY_FLOWS = {"threshold_signal_target"}
_LONG_SHORT_STRATEGY_FLOWS = {"compose_long_short_target"}
_TERM_CARRY_STRATEGY_FLOWS = {"term_carry_target"}
_STRATEGY_RUNTIME_FLOWS = {
    "strategy_runtime_on_start",
    "strategy_runtime_on_market_feed",
    "strategy_runtime_on_bar",
    "strategy_runtime_on_timer",
    "strategy_runtime_on_signal_intent",
    "strategy_runtime_on_order_event",
    "strategy_runtime_on_order_status_event",
    "strategy_runtime_on_position_event",
    "strategy_runtime_on_stop",
}
_DAILY_MARK_TO_MARKET_FLOWS = {
    "register_daily_mark_to_market_notices",
    "apply_daily_mark_to_market",
}
_MARGIN_NOTICE_FLOWS = {
    "register_margin_check_notices",
    "schedule_margin_check_notices",
    "apply_margin_requirement_change",
    "handle_margin_liquidation_notice",
}
_LEDGER_LOOKUP_FLOWS = {
    "lookup_current_prices_on_ledger",
    "lookup_historical_fields_on_ledger",
}
_LEDGER_OWNED_SETTING_NAMES = {
    "fee_mode",
    "transaction_fee_source",
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
    # The UI default is only a display fallback. Auto accounting must still be
    # able to infer FIFO when fee/DMTM fields require lot-level accounting,
    # including the case where margin_mode is explicitly closed.
    "cost_basis_method",
    # Auto accounting uses the native whole-contract policy unless a custom
    # ledger explicitly selects a boolean value.  Do not turn the UI default
    # into a persisted false before the runtime resolver sees it.
    "use_int_position",
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
    if chosen != "signal_precomputed" or not _has_strategy_intent_precompute_policy(resolved_settings):
        excluded.add("precompute_strategy_intents")
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
    strategy_kind = _strategy_intent_mode(resolved_settings)
    if strategy_kind == "custom":
        excluded |= _FACTOR_MODE_FLOWS | _LIVE_FACTOR_SUPPORT_FLOWS
        excluded |= (
            _GROUP_STRATEGY_FLOWS
            | _THRESHOLD_STRATEGY_FLOWS
            | _LONG_SHORT_STRATEGY_FLOWS
            | _TERM_CARRY_STRATEGY_FLOWS
            | {"precompute_strategy_intents"}
        )
        # Custom strategies may consume aggregate BAR events directly.  The
        # scheduler normally registers BAR events only for live factors, so
        # retain the producer here; BarEventModule filters strategies that do
        # not actually override Strategy.on_bar.
        excluded.discard("schedule_bar_events")
    elif strategy_kind == "long_short":
        excluded |= (
            _GROUP_STRATEGY_FLOWS
            | _THRESHOLD_STRATEGY_FLOWS
            | _TERM_CARRY_STRATEGY_FLOWS
        )
    elif strategy_kind == "term_carry":
        excluded |= (
            _GROUP_STRATEGY_FLOWS
            | _THRESHOLD_STRATEGY_FLOWS
            | _LONG_SHORT_STRATEGY_FLOWS
        )
    elif strategy_kind == "threshold":
        excluded |= (
            _GROUP_STRATEGY_FLOWS
            | _LONG_SHORT_STRATEGY_FLOWS
            | _TERM_CARRY_STRATEGY_FLOWS
        )
    else:
        excluded |= (
            _THRESHOLD_STRATEGY_FLOWS
            | _LONG_SHORT_STRATEGY_FLOWS
            | _TERM_CARRY_STRATEGY_FLOWS
        )
    if strategy_kind != "custom":
        excluded |= _STRATEGY_RUNTIME_FLOWS
    return frozenset(names - excluded)


def _strategy_intent_mode(resolved_settings: Mapping[str, Any]) -> str:
    return str(
        resolved_settings.get("strategy_intent_mode")
        or resolved_settings.get("strategy_kind")
        or "group"
    )


def _uses_daily_mark_to_market_flow(resolved_settings: Mapping[str, Any]) -> bool:
    engine_mode = str(resolved_settings.get("engine_mode", "auto") or "auto").lower()
    if engine_mode == "basic":
        return False
    accounting_mode = str(resolved_settings.get("accounting_mode", "Auto") or "Auto")
    if accounting_mode == "Basic":
        return False
    if accounting_mode == "Custom":
        raw_value = resolved_settings.get("daily_mark_to_market_enabled", "auto")
        value = "auto" if raw_value in (None, "") else str(raw_value).lower()
        return value != "false"
    margin_mode = str(resolved_settings.get("margin_mode", "auto") or "auto").lower()
    raw_dmtm = resolved_settings.get("daily_mark_to_market_enabled", "auto")
    configured_dmtm = "auto" if raw_dmtm in (None, "") else str(raw_dmtm).lower()
    if margin_mode in {"off", "none", "zero"} and configured_dmtm != "true":
        return False
    if engine_mode in {"auto", "exact"}:
        return True
    return True


def _uses_margin_notice_flow(resolved_settings: Mapping[str, Any]) -> bool:
    engine_mode = str(resolved_settings.get("engine_mode", "auto") or "auto").lower()
    if engine_mode == "basic":
        return False
    margin_mode = str(resolved_settings.get("margin_mode", "auto") or "auto").lower()
    if margin_mode in {"off", "none", "zero"}:
        return False
    margin_call_mode = str(resolved_settings.get("margin_call_mode", "auto") or "auto").lower()
    return margin_call_mode != "off"


def _has_strategy_intent_precompute_policy(resolved_settings: Mapping[str, Any]) -> bool:
    from tools.testers.backtest.modules.target import strategy_intent_policy_for

    strategy_kind = _strategy_intent_mode(resolved_settings)
    return strategy_intent_policy_for(strategy_kind) is not None


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
    rules = fd.rules()
    for source_key, mapping in rules.default_if.items():
        source_value = values_by_name.get(source_key)
        if source_value in mapping:
            return mapping[source_value]
        source_text = str(source_value)
        if source_text in mapping:
            return mapping[source_text]
    return fd.default_value()


def _field_visible_for_materialization(
    fd: Any,
    resolved: Mapping[str, Any],
    materialized: Mapping[Any, Any],
    entries: list[tuple[str, Any, Any, frozenset[str]]],
) -> bool:
    """Return whether a missing field's backend default should be materialized.

    ``visible_if`` is not only a UI concern for ledger-owned fields.  Hidden
    defaults such as fixed_fee_rate=0.0 when fee_mode=auto, or
    fixed_margin_ratio=1.0 when margin_mode=auto, are stale control defaults,
    not active ledger inputs.  Explicit values are handled before this helper;
    this only gates automatic default materialization.
    """
    visible_if = fd.rules().visible_if
    if not visible_if:
        return True
    values_by_name = dict(resolved)
    fields_by_name = {field_name: field_fd for field_name, _ref, field_fd, _flows in entries}
    refs_by_name = {field_name: ref for field_name, ref, _field_fd, _flows in entries}
    for field_name, ref in refs_by_name.items():
        if ref in materialized:
            values_by_name[field_name] = materialized[ref]
    for dep_key, allowed_values in visible_if.items():
        dep_name = str(dep_key)
        if dep_name in values_by_name:
            dep_value = values_by_name[dep_name]
        elif dep_name in fields_by_name:
            dep_value = _default_value_for_field(fields_by_name[dep_name], resolved, materialized, entries)
        else:
            dep_value = None
        allowed = set(allowed_values) if isinstance(allowed_values, (list, tuple, set)) else {allowed_values}
        if dep_value not in allowed and str(dep_value) not in {str(item) for item in allowed}:
            return False
    return True


def build_strategy_configs(
    resolved_settings_by_alias: Mapping[str, Mapping[str, Any]],
    *,
    flow_settings_by_alias: Mapping[str, Mapping[str, Any]] | None = None,
    strategies_by_alias: Mapping[str, Strategy] | None = None,
) -> dict[Strategy, StrategyConfig]:
    """`resolved_settings_by_alias`: {strategy_id: {setting_key: value, ...}}
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
            if field_name == "strategy_intent_mode" and "strategy_kind" in resolved and field_name not in resolved:
                field_values[ref] = resolved["strategy_kind"]
                continue
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
        config = StrategyConfig(
            strategy=strategy, active_flow_names=active_flow_names, field_values=field_values,
        )
        _validate_margin_budget_config(alias, config)
        configs[strategy] = config
    return configs


def _validate_margin_budget_config(alias: str, config: StrategyConfig) -> None:
    from tools.testers.backtest.modules.margin_budget import MarginBudgetModule

    target = float(config.get(MarginBudgetModule.target_margin_utilization, 0.30))
    maximum = float(config.get(MarginBudgetModule.max_margin_utilization, 0.40))
    tolerance = float(config.get(MarginBudgetModule.margin_utilization_tolerance, 0.01))
    if not 0 < target <= maximum < 1:
        raise ValueError(
            f"strategy {alias!r} margin utilization requires 0 < target <= max < 1"
        )
    if tolerance < 0:
        raise ValueError(f"strategy {alias!r} margin utilization tolerance must be non-negative")


def apply_strategy_configs(
    state: "BacktestRunState",
    resolved_settings_by_alias: Mapping[str, Mapping[str, Any]],
    *,
    strategy_book: object | None = None,
    ledger_configs: Mapping[str, Mapping[str, Any] | LedgerConfig] | None = None,
    counterparty: str | CounterPartyProfile | None = None,
    counterparty_by_strategy: Mapping[str, str | CounterPartyProfile | None] | None = None,
    counterparty_by_ledger: Mapping[str, str | CounterPartyProfile | None] | None = None,
    strategies_by_alias: Mapping[str, Strategy] | None = None,
) -> None:
    book = strategy_book or StrategyBookSimple()
    resolved = {str(alias): dict(settings) for alias, settings in resolved_settings_by_alias.items()}
    provided = strategies_by_alias or {}
    strategy_objects = {
        alias: provided.get(alias, Strategy(alias=alias))
        for alias in resolved
    }
    materialize_strategy_book_store(state, book, strategy_objects, resolved)
    _resolve_cash_pool_configs(resolved, state=state, strategies_by_alias=strategy_objects, strategy_book=book)
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


def _resolve_cash_pool_configs(
    resolved_settings_by_alias: Mapping[str, Mapping[str, Any]],
    *,
    state: "BacktestRunState",
    strategies_by_alias: Mapping[str, Strategy],
    strategy_book: object,
) -> None:
    from tools.testers.backtest.modules.cash_pool import register_cash_pool_config
    from tools.testers.backtest.modules.strategy_book import strategy_book_store_for

    store = strategy_book_store_for(state)
    config_resolver = getattr(strategy_book, "cash_pool_config_for_strategy_settings")
    for alias, settings in resolved_settings_by_alias.items():
        strategy = strategies_by_alias[str(alias)]
        for ledger in store.ledgers_for_strategy(state, strategy):
            config = config_resolver(
                state,
                strategy,
                ledger,
                settings,
            )
            register_cash_pool_config(
                state,
                store.cash_pool_for_ledger(ledger),
                config,
                source=f"strategy {alias!r}",
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
            and _ledger_owned_setting_should_materialize(key, settings[key], settings, entries)
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
            if not _ledger_owned_setting_should_materialize(
                field_name,
                resolved[field_name],
                resolved,
                entries,
                materialized_refs,
            ):
                continue
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
            if not _field_visible_for_materialization(fd, resolved, materialized_refs, entries):
                continue
            value = _default_value_for_field(fd, resolved, materialized_refs, entries)
        values[field_name] = value
        materialized_refs[ref] = value
    return values


def _ledger_owned_setting_should_materialize(
    field_name: str,
    value: Any,
    resolved: Mapping[str, Any],
    entries: list[tuple[str, Any, Any, frozenset[str]]],
    materialized: Mapping[Any, Any] | None = None,
) -> bool:
    for candidate_name, _ref, fd, _owner_flow_names in entries:
        if candidate_name == field_name:
            materialized_values = materialized or {}
            if _field_visible_for_materialization(fd, resolved, materialized_values, entries):
                return True
            if value == _default_value_for_field(fd, resolved, materialized_values, entries):
                return False
            if _is_disabled_margin_dependent_setting(field_name, resolved, materialized_values, entries):
                return False
            visible_if = fd.rules().visible_if
            raise ValueError(
                f"ledger-owned field {field_name!r} is only valid when {visible_if!r}; "
                f"got {value!r} under current settings"
            )
    return True


def _is_disabled_margin_dependent_setting(
    field_name: str,
    resolved: Mapping[str, Any],
    materialized: Mapping[Any, Any],
    entries: list[tuple[str, Any, Any, frozenset[str]]],
) -> bool:
    if field_name not in {"margin_call_mode", "liquidation_target_buffer"}:
        return False
    values_by_name = dict(resolved)
    for candidate_name, ref, _fd, _owner_flow_names in entries:
        if ref in materialized:
            values_by_name[candidate_name] = materialized[ref]
    margin_mode = str(values_by_name.get("margin_mode") or "").lower()
    return margin_mode in {"off", "none", "zero"}


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
