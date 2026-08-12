"""Cash-pool configuration registration and strategy projection."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from tools.testers.backtest.engines.native.config import CashPoolConfig
from tools.testers.backtest.engines.native.ledger import Ledger

from .merge import merge_compatible, validate_margin_budget


def cash_pool_config_for_ledger(state: object, ledger: str | Ledger | object) -> CashPoolConfig:
    from tools.testers.backtest.modules.cash_pool import cash_pool_store_for
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    return cash_pool_store_for(state).config_by_pool.get(
        cash_pool_id_for_ledger(state, ledger), CashPoolConfig(),
    )


def register_cash_pool_config(
    state: object, cash_pool_id: str, config: CashPoolConfig, *, source: str,
) -> None:
    from tools.testers.backtest.modules.cash_pool import cash_pool_store_for

    store = cash_pool_store_for(state)
    pool_id = str(cash_pool_id)
    existing = store.config_by_pool.get(pool_id)
    merged = config if existing is None else merge_compatible(
        existing, config, cash_pool_id=pool_id, source=source,
    )
    validate_margin_budget(merged, cash_pool_id=pool_id)
    store.config_by_pool[pool_id] = merged


def cash_pool_config_from_strategy_config(strategy_config: Any) -> CashPoolConfig:
    from tools.testers.backtest.modules.cash_pool import CashPoolModule
    from tools.testers.backtest.modules.margin_budget import MarginBudgetModule

    return CashPoolConfig(
        initial_capital_major=_optional(strategy_config.get(CashPoolModule.initial_capital_major, None), float),
        base_currency=_optional(strategy_config.get(CashPoolModule.base_currency, None), str),
        currency_conversion_fee_rate=_optional(
            strategy_config.get(CashPoolModule.currency_conversion_fee_rate, None), float,
        ),
        target_margin_utilization=_optional(
            strategy_config.get(MarginBudgetModule.target_margin_utilization, None), float,
        ),
        max_margin_utilization=_optional(
            strategy_config.get(MarginBudgetModule.max_margin_utilization, None), float,
        ),
        margin_utilization_tolerance=_optional(
            strategy_config.get(MarginBudgetModule.margin_utilization_tolerance, None), float,
        ),
    )


def ensure_cash_pool_config_for_strategy_ledger(
    state: object, strategy_config: Any, ledger: str | Ledger | object, *, source: str,
) -> CashPoolConfig:
    from tools.testers.backtest.modules.cash_pool import cash_pool_store_for
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    pool_id = cash_pool_id_for_ledger(state, ledger)
    config = cash_pool_config_from_strategy_config(strategy_config)
    existing = cash_pool_store_for(state).config_by_pool.get(pool_id)
    if existing is not None:
        config = replace(config, **{
            key: None if getattr(existing, key) is not None else getattr(config, key)
            for key in (
                "target_margin_utilization", "max_margin_utilization",
                "margin_utilization_tolerance",
            )
        })
    register_cash_pool_config(state, pool_id, config, source=source)
    return cash_pool_store_for(state).config_by_pool.get(pool_id, CashPoolConfig())


def _optional(value: object, cast):
    return None if value in (None, "") else cast(value)
