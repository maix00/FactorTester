"""Cash-pool utilization after DMTM or historical margin-rule changes."""

from __future__ import annotations

import math
from typing import Any


def margin_limit_state(state: Any, ctx: Any, ledger: Any, required: float) -> tuple[float, float]:
    from tools.testers.backtest.modules.cash_pool import cash_for_ledger
    from tools.testers.backtest.modules.ledger_module import LedgerModule, _ledger_equity
    from tools.testers.backtest.modules.margin import (
        _required_margin_for_position,
        _strategy_for_ledger,
    )
    from tools.testers.backtest.modules.margin_budget import MarginBudgetModule
    from tools.testers.backtest.modules.margin_budget_impl.models import settings_for_pool
    from tools.testers.backtest.modules.market_data import MarketDataModule
    from tools.testers.backtest.modules.strategy_book import (
        cash_pool_id_for_ledger,
        ledgers_for_cash_pool,
    )

    owner = _strategy_for_ledger(state, ledger.ledger)
    if owner is None:
        return 0.0, 0.0
    pool_ledgers = [
        state.ledgers[item]
        for item in ledgers_for_cash_pool(state, ledger)
        if item in state.ledgers
    ] or [ledger]
    prices = _pool_valuation_prices(ctx, pool_ledgers, LedgerModule, MarketDataModule)
    cash = cash_for_ledger(state, ledger)
    cash_major = float(cash.to_major()) if cash is not None else 0.0
    total_equity = cash_major
    total_required = 0.0
    for item in pool_ledgers:
        item_owner = _strategy_for_ledger(state, item.ledger)
        if item_owner is None:
            continue
        total_equity += float(_ledger_equity(
            state, ctx, item_owner, item, prices,
        )) - cash_major
        item_required = required if item is ledger else sum(
            _required_margin_for_position(
                state, ctx, state.ledger_config_for(item), product, position,
            )
            for product, position in item.get(LedgerModule.positions, {}).items()
            if abs(float(getattr(position, "quantity", 0.0) or 0.0)) > 1e-12
        )
        total_required += item_required
    if total_equity <= 0:
        return float("inf"), required
    pool_id = cash_pool_id_for_ledger(state, ledger)
    maximum = settings_for_pool(
        state, pool_id, state.config_for(owner), MarginBudgetModule,
    ).maximum
    utilization = total_required / total_equity
    pool_excess = max(total_required - total_equity * maximum, 0.0)
    share = required / total_required if total_required > 1e-12 else 0.0
    return utilization, pool_excess * share


def _pool_valuation_prices(ctx, ledgers, ledger_module, market_data_module) -> dict:
    """Resolve the latest causal traded-price view for held products.

    Settlement belongs exclusively to the DMTM flow.  Margin utilization is a
    non-settlement risk check, so a settlement snapshot must never override
    the causal close/current traded-price view here.
    """
    from tools.testers.backtest.modules.trading_rule import _lookup_product_value

    snapshot = ctx.get(market_data_module.current_market_snapshot, {}) or {}
    sources = (
        snapshot.get("close") or {},
        ctx.get(market_data_module.current_prices, {}) or {},
    )
    prices: dict[Any, float] = {}
    for ledger in ledgers:
        for product, position in ledger.get(ledger_module.positions, {}).items():
            if abs(float(getattr(position, "quantity", 0.0) or 0.0)) <= 1e-12:
                continue
            for source in sources:
                value = _lookup_product_value(source, product)
                if value is not None and math.isfinite(value) and value > 0.0:
                    prices[product] = value
                    break
    return prices
