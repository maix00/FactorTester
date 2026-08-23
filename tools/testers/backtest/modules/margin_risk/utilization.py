"""Cash-pool utilization after DMTM or historical margin-rule changes."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping


def margin_limit_state(state: Any, ctx: Any, ledger: Any, required: float) -> tuple[float, float]:
    return margin_limit_states(state, ctx, {ledger.ledger: required})[ledger.ledger]


def margin_limit_states(
    state: Any,
    ctx: Any,
    required_by_ledger: Mapping[Any, float],
) -> dict[Any, tuple[float, float]]:
    """Value each affected cash pool once for a batch of margin checks."""
    from tools.testers.backtest.modules.cash_pool import (
        account_cash_or_zero,
        cash_amount_to_pool_base,
        cash_pool_cash_major,
    )
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

    requested = {
        ledger_ref: float(required)
        for ledger_ref, required in required_by_ledger.items()
        if ledger_ref in state.ledgers
    }
    ledgers_by_pool: dict[str, list[Any]] = defaultdict(list)
    for ledger_ref in requested:
        ledger = state.ledgers[ledger_ref]
        ledgers_by_pool[cash_pool_id_for_ledger(state, ledger)].append(ledger)

    result: dict[Any, tuple[float, float]] = {}
    for pool_id, requested_ledgers in ledgers_by_pool.items():
        pool_ledgers = [
            state.ledgers[item]
            for item in ledgers_for_cash_pool(state, requested_ledgers[0])
            if item in state.ledgers
        ] or requested_ledgers
        prices = _pool_valuation_prices(ctx, pool_ledgers, LedgerModule, MarketDataModule)
        cash_major = cash_pool_cash_major(
            state, requested_ledgers[0], timestamp=ctx.timestamp,
        )
        equity_parts: list[float] = []
        required_parts: list[float] = []
        owners: dict[Any, Any] = {}
        for item in pool_ledgers:
            item_owner = _strategy_for_ledger(state, item.ledger)
            if item_owner is None:
                continue
            owners[item.ledger] = item_owner
            account_cash = float(account_cash_or_zero(state, item).to_major())
            equity_parts.append(cash_amount_to_pool_base(
                state, item,
                float(_ledger_equity(state, ctx, item_owner, item, prices)) - account_cash,
                timestamp=ctx.timestamp,
            ))
            item_required = requested.get(item.ledger)
            if item_required is None:
                item_required = sum(
                    _required_margin_for_position(
                        state, ctx, state.ledger_config_for(item), product, position,
                    )
                    for product, position in item.get(LedgerModule.positions, {}).items()
                    if abs(float(getattr(position, "quantity", 0.0) or 0.0)) > 1e-12
                )
            required_parts.append(cash_amount_to_pool_base(
                state, item, item_required, timestamp=ctx.timestamp,
            ))

        total_equity = cash_major + math.fsum(equity_parts)
        total_required = math.fsum(required_parts)

        utilization = float("inf") if total_equity <= 0 else total_required / total_equity
        for ledger in requested_ledgers:
            required = requested[ledger.ledger]
            owner = owners.get(ledger.ledger)
            if owner is None:
                result[ledger.ledger] = (0.0, 0.0)
                continue
            if total_equity <= 0:
                result[ledger.ledger] = (utilization, required)
                continue
            maximum = settings_for_pool(
                state, pool_id, state.config_for(owner), MarginBudgetModule,
            ).maximum
            pool_excess = max(total_required - total_equity * maximum, 0.0)
            share = required / total_required if total_required > 1e-12 else 0.0
            result[ledger.ledger] = (utilization, pool_excess * share)
    return result


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
