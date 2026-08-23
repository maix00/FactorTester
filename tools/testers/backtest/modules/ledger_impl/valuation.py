"""Ledger equity valuation."""

from __future__ import annotations

from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_notional,
)
from tools.testers.backtest.modules.trading_rule import mark_to_market


def basic_equity(state, ctx, *, equity_fn=None) -> None:
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    from tools.testers.backtest.modules.strategy_book import cash_pool_id_for_ledger

    equity_fn = equity_fn or ledger_equity
    equity_by_pool: dict[str, float] = {}
    for strategy in ctx.active_strategies:
        ledger = state.ledger_for_strategy(strategy)
        cache_key = cash_pool_id_for_ledger(state, ledger)
        value = equity_by_pool.get(cache_key)
        if value is None:
            value = cash_pool_equity(state, ctx, ledger, equity_fn=equity_fn)
            equity_by_pool[cache_key] = value
        ctx.set_for(LedgerModule.equity, strategy, value)


def cash_pool_equity(state, ctx, anchor_ledger, *, equity_fn=None) -> float:
    """Value one pool once in its base currency, including every account."""
    from tools.testers.backtest.modules.cash_pool import (
        account_cash_or_zero,
        cash_amount_to_pool_base,
        cash_pool_cash_major,
    )
    from tools.testers.backtest.modules.margin import _strategy_for_ledger
    from tools.testers.backtest.modules.strategy_book import ledgers_for_cash_pool

    equity_fn = equity_fn or ledger_equity
    total = cash_pool_cash_major(state, anchor_ledger, timestamp=ctx.timestamp)
    for ledger_ref in ledgers_for_cash_pool(state, anchor_ledger):
        ledger = state.ledgers.get(ledger_ref)
        if ledger is None:
            continue
        owner = _strategy_for_ledger(state, ledger.ledger)
        if owner is None:
            continue
        prices = valuation_prices_for_equity(ctx, ledger=ledger)
        account_cash = float(account_cash_or_zero(state, ledger).to_major())
        non_cash = float(equity_fn(state, ctx, owner, ledger, prices)) - account_cash
        total += cash_amount_to_pool_base(
            state, ledger, non_cash, timestamp=ctx.timestamp,
        )
    return total


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
    from tools.testers.backtest.modules.cash_pool import account_cash_or_zero

    return account_cash_or_zero(state, ledger)


def required_current_price(prices: dict, product, timestamp) -> float:
    if isinstance(prices, dict) and product in prices:
        return float(prices[product])
    raise KeyError(
        f"current price missing for held product {product} at {timestamp}; "
        "current_prices is expected to be causal-ffilled by MarketDataModule, "
        "so this usually means the position product was not included in the "
        "loaded market-data universe"
    )
