"""Build the post-resolution settings manifest for a native backtest.

The RunSpec records user intent.  Several native policies intentionally keep
that intent as ``auto`` until product data, historical rule fields, or the
execution plan is available.  This module records the values the same
resolvers used during replay selected, without introducing a second policy
implementation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from tools.testers.backtest.modules.engine import engine_mode_for
from tools.testers.backtest.modules.execution_capacity import effective_matching_model
from tools.testers.backtest.modules.factor_signal import _effective_signal_frequency
from tools.testers.backtest.modules.fee import (
    _resolve_fee_mode,
)
from tools.testers.backtest.modules.market_data import (
    contract_multiplier_from_product_fields,
    market_data_store_for,
    _historical_field_policy_for_engine,
    _transaction_fee_source_for_ledger_config,
)
from tools.testers.backtest.modules.margin import (
    _resolve_margin_call_mode_from_ledger_config,
    _resolve_margin_mode,
    product_uses_margin_accounting,
)
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.run_window import (
    warmup_window_for_strategy,
)
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.minor_unit import resolve_use_minor_units
from tools.testers.backtest.modules.trading_rule import (
    _effective_accounting_mode,
    _resolve_daily_mark_to_market_enabled_for_ledger,
    _resolve_method,
    _resolve_use_int_position,
)
from tools.testers.backtest.modules.volume_capacity import VolumeCapacityMode
from tools.testers.backtest.modules.ledger_impl.margin_ratios import market_margin_ratio


SCHEMA_VERSION = "effective-runtime-settings-v1"
_MARKET_RULE_FIELDS = (
    "CostBasisMethod",
    "DailyMarkToMarketEnabled",
    "LongMarginRatioByMoney",
    "ShortMarginRatioByMoney",
    "LongMarginRatioByVolume",
    "ShortMarginRatioByVolume",
    "VolumeMultiple",
    "OpenRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByMoney",
    "CloseRatioByVolume",
    "CloseTodayRatioByMoney",
    "CloseTodayRatioByVolume",
    "SettlementPrice",
    "PreSettlementPrice",
    "LastSettlementPrice",
    "MoneyCalculationPolicy",
)


def build_effective_runtime_settings(
    state: Any,
    *,
    settings_by_strategy: Mapping[str, Mapping[str, Any]] | None = None,
    products: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Return requested and effective values for every active strategy.

    The product rows are deliberately calculated after PRE_REPLAY has loaded
    field state.  They therefore describe the same historical/default field
    snapshot consumed by accounting and margin flows during replay.
    """
    requested = settings_by_strategy or {}
    store = market_data_store_for(state)
    run_products = _run_products(store, products)
    product_rows = {
        _product_name(product): _product_effective_values(state, product)
        for product in run_products
    }
    strategies: dict[str, Any] = {}
    ledgers: dict[str, Any] = {}
    for strategy, config in getattr(state, "strategy_configs", {}).items():
        alias = _strategy_name(strategy)
        ledger = state.ledger_for_strategy(strategy)
        ledger_config = state.ledger_config_for(ledger)
        ledger_id = _ledger_name(ledger)
        effective = _strategy_effective_values(
            state, strategy, config, ledger_config, store,
        )
        strategies[alias] = {
            "requested": _json_safe(dict(requested.get(alias, {}))),
            "effective": effective,
            "ledger_id": ledger_id,
        }
        ledgers.setdefault(ledger_id, {
            "requested": _json_safe(_ledger_requested_values(ledger_config)),
            "effective": _ledger_effective_values(
                state, strategy, config, ledger_config,
            ),
            "products": product_rows,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "strategies": strategies,
        "ledgers": ledgers,
        "market_data_plan": _market_data_plan(store),
    }


def _strategy_effective_values(state, strategy, config, ledger_config, store) -> dict[str, Any]:
    engine = engine_mode_for(config)
    factor_mode = (
        "precomputed" if config.uses_flow("signal_precomputed")
        else "incremental" if config.uses_flow("signal_live")
        else "custom"
    )
    warmup = warmup_window_for_strategy(
        config, config.get(_factor_ref()),
    )
    frequency = store.required_frequency_by_strategy.get(strategy)
    sources = store.required_data_source_by_strategy.get(strategy, ())
    raw_policy = getattr(store, "historical_field_policy", None) or "auto"
    matching = effective_matching_model(
        config,
        OrderExecutionModule.matching_model,
        VolumeCapacityMode.liquidity_mode,
    )
    return {
        "engine_mode": engine,
        "bar_open_visibility_delay": _value(
            config.get(EngineModule.bar_open_visibility_delay, "1us"), "1us",
        ),
        "bar_end_visibility_delay": _value(
            config.get(EngineModule.bar_end_visibility_delay, "0ns"), "0ns",
        ),
        "factor_mode": factor_mode,
        "warmup_mode": _value(config.get(_warmup_ref(), "auto"), "auto"),
        "warmup_window": str(warmup),
        "calendar_frequency": _value(
            _calendar_frequency(config), "auto",
        ),
        "signal_frequency": str(_effective_signal_frequency(config)),
        "data_source": [str(value) for value in sources],
        "frequency": str(getattr(frequency, "name", frequency or "")),
        "historical_field_policy": _historical_field_policy_for_engine(
            state, raw_policy,
        ),
        "liquidity_mode": _value(
            config.get(VolumeCapacityMode.liquidity_mode, "infinite"),
            "infinite",
        ),
        "matching_model": matching,
        "accounting_mode": _effective_accounting_mode(config, ledger_config),
        "fee_mode": _resolve_fee_mode(config, ledger_config),
        "transaction_fee_source": _transaction_fee_source_for_ledger_config(
            ledger_config,
        ),
        "margin_mode": _resolve_margin_mode(config, ledger_config),
        "margin_call_mode": _resolve_margin_call_mode_from_ledger_config(
            ledger_config,
        ),
        "use_int_position": _resolve_use_int_position(config, ledger_config),
        "use_minor_units": resolve_use_minor_units(config),
    }


def _ledger_requested_values(ledger_config: Any) -> dict[str, Any]:
    return {
        key: getattr(ledger_config, key, None)
        for key in (
            "fee_mode", "transaction_fee_source", "fixed_fee_rate",
            "margin_mode", "fixed_margin_ratio", "margin_call_mode",
            "liquidation_target_buffer", "accounting_mode",
            "daily_mark_to_market_enabled", "cost_basis_method",
            "use_int_position", "cash_reserve_ratio", "cash_reserve_major",
        )
    }


def _ledger_effective_values(state, strategy, config, ledger_config) -> dict[str, Any]:
    return {
        "accounting_mode": _effective_accounting_mode(config, ledger_config),
        "fee_mode": _resolve_fee_mode(config, ledger_config),
        "transaction_fee_source": _transaction_fee_source_for_ledger_config(
            ledger_config,
        ),
        "margin_mode": _resolve_margin_mode(config, ledger_config),
        "margin_call_mode": _resolve_margin_call_mode_from_ledger_config(
            ledger_config,
        ),
        "use_int_position": _resolve_use_int_position(config, ledger_config),
    }


def _product_effective_values(state, product: Any) -> dict[str, Any]:
    store = market_data_store_for(state)
    name = _product_name(product)
    fields = dict(store.field_state_store.get(name, {}))
    rows: dict[str, Any] = {
        "market_rule_fields": {
            key: _json_safe(fields[key])
            for key in _MARKET_RULE_FIELDS
            if key in fields
        },
    }
    for strategy, config in getattr(state, "strategy_configs", {}).items():
        ledger = state.ledger_for_strategy(strategy)
        ledger_config = state.ledger_config_for(ledger)
        try:
            method = _resolve_method(
                config,
                product,
                fields,
                require_exact=engine_mode_for(config) == "exact",
                ledger_config=ledger_config,
            )
            dmtm = _resolve_daily_mark_to_market_enabled_for_ledger(
                product, fields, ledger_config=ledger_config,
            )
            margin_accounting = product_uses_margin_accounting(
                fields, ledger_config,
            )
            multiplier = contract_multiplier_from_product_fields(
                fields,
                state=state,
                product=product,
                timestamp=None,
            )
            margin_ratio = market_margin_ratio(fields, 1.0, 1.0, multiplier)
            rows.setdefault("by_ledger", {})[
                _ledger_name(ledger)
            ] = {
                "cost_basis_method": method,
                "daily_mark_to_market_enabled": dmtm,
                "margin_accounting": margin_accounting,
                "market_margin_ratio": margin_ratio,
                "contract_multiplier": multiplier,
            }
        except (KeyError, ValueError) as exc:
            rows.setdefault("resolution_errors", []).append({
                "strategy": _strategy_name(strategy),
                "error": str(exc),
            })
    return rows


def _run_products(store, products: Sequence[Any] | None) -> list[Any]:
    selected: list[Any] = []
    for item in getattr(store, "load_plan", ()):
        product = item[0] if isinstance(item, (tuple, list)) else None
        if product is not None and product not in selected:
            selected.append(product)
    if selected:
        return selected
    return list(products or ())


def _market_data_plan(store) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in getattr(store, "load_plan", ()):
        if not isinstance(item, (tuple, list)) or len(item) < 3:
            continue
        product, frequency, source = item[:3]
        rows.append({
            "product": _product_name(product),
            "frequency": str(getattr(frequency, "name", frequency)),
            "data_source": str(
                getattr(source, "key", None)
                or getattr(source, "name", None)
                or source
            ),
        })
    return rows


def _factor_ref():
    from tools.testers.backtest.modules.factor import FactorModule

    return FactorModule.factor


def _warmup_ref():
    from tools.testers.backtest.modules.factor_signal import FactorSignalModule

    return FactorSignalModule.warmup_mode


def _calendar_frequency(config):
    from tools.testers.backtest.modules.factor_signal import FactorSignalModule

    return config.get(FactorSignalModule.calendar_frequency, "auto")


def _value(value: Any, fallback: Any) -> Any:
    return fallback if value is None or value == "" else value


def _strategy_name(strategy: Any) -> str:
    return str(
        getattr(strategy, "alias", None)
        or getattr(strategy, "name", None)
        or strategy
    )


def _product_name(product: Any) -> str:
    return str(getattr(product, "name", None) or product)


def _ledger_name(ledger: Any) -> str:
    return str(
        getattr(ledger, "ledger", None)
        or getattr(ledger, "name", None)
        or ledger
    )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)
