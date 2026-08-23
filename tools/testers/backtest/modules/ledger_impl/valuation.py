"""Ledger equity valuation."""

from __future__ import annotations

from tools.testers.backtest.modules.cash_pool import cash_for_ledger
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_notional,
)
from tools.testers.backtest.modules.trading_rule import mark_to_market


def basic_equity(state, ctx, *, equity_fn=None) -> None:
    from tools.testers.backtest.modules.ledger_module import LedgerModule

    equity_fn = equity_fn or ledger_equity
    equity_by_ledger: dict[int, float] = {}
    for strategy in ctx.active_strategies:
        ledger = state.ledger_for_strategy(strategy)
        cache_key = id(ledger)
        value = equity_by_ledger.get(cache_key)
        if value is None:
            prices = valuation_prices_for_equity(ctx, ledger=ledger)
            value = equity_fn(state, ctx, strategy, ledger, prices)
            equity_by_ledger[cache_key] = value
        ctx.set_for(LedgerModule.equity, strategy, value)


def valuation_prices_for_equity(ctx, *, ledger=None) -> dict:
    from tools.testers.backtest.modules.ledger_module import LedgerModule

    snapshot = ctx.get(MarketDataModule.current_market_snapshot, {}) or {}
    prices = None
    if isinstance(snapshot, dict):
        close = snapshot.get("close")
        if isinstance(close, dict):
            prices = close
    if prices is None:
        prices = ctx.get(MarketDataModule.current_prices)
    if ledger is None:
        return prices
    fill_prices = ctx.get(
        LedgerModule._order_fill_valuation_prices_ref, {},
    ).get(ledger.ledger_id, {})
    if not fill_prices:
        return prices
    return {**prices, **fill_prices}


def ledger_equity(state, ctx, strategy, ledger, prices: dict) -> float:
    from tools.testers.backtest.modules.ledger_module import LedgerModule

    cash = required_cash_for_ledger(state, ledger)
    positions = ledger.get(LedgerModule.positions, {})
    historical_fields = ctx.get_for(
        MarketDataModule.current_historical_fields,
        strategy,
        ctx.get(MarketDataModule.current_historical_fields, {}),
    )
    margin_products = {
        product
        for product, entry in positions.items()
        if abs(float(getattr(entry, "quantity", 0.0) or 0.0)) > 1e-12
        and getattr(entry, "margin_reserved", None) is not None
    }
    if margin_products:
        margin_occupied = sum(
            float(entry.margin_reserved.to_major())
            for product, entry in positions.items()
            if product in margin_products
        )
        floating_pnl = mark_to_market(
            ledger, state.config_for(strategy), prices, historical_fields,
            ledger_config=state.ledger_config_for(ledger),
            state=state, timestamp=ctx.timestamp, products=margin_products,
        ).to_major()
    else:
        margin_occupied = 0.0
        floating_pnl = 0.0
    market_value = sum(
        contract_notional(
            required_current_price(prices, product, ctx.timestamp),
            entry.quantity, historical_fields, product,
        )
        for product, entry in positions.items()
        if product not in margin_products
        and abs(float(getattr(entry, "quantity", 0.0) or 0.0)) > 1e-12
    )
    return cash.to_major() + margin_occupied + floating_pnl + market_value


def required_cash_for_ledger(state, ledger):
    cash = cash_for_ledger(state, ledger)
    if cash is None:
        raise RuntimeError(f"ledger {getattr(ledger, 'ledger_id', ledger)!r} has no cash pool")
    return cash


def required_current_price(prices: dict, product, timestamp) -> float:
    if isinstance(prices, dict) and product in prices:
        return float(prices[product])
    raise KeyError(
        f"current price missing for held product {product} at {timestamp}; "
        "current_prices is expected to be causal-ffilled by MarketDataModule, "
        "so this usually means the position product was not included in the "
        "loaded market-data universe"
    )
