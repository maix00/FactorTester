"""Projected gross-notional valuation."""

from __future__ import annotations

from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_multiplier_from_fields,
)


def gross_notional(state, ctx, components, positions: dict[int, dict]) -> float:
    # Existing positions are marked on the causal close view.  Only products
    # touched by an order are overlaid with that order event's executable
    # price basis, so a next-open map cannot erase a held contract's close.
    snapshot = ctx.get(MarketDataModule.current_market_snapshot, {}) or {}
    close_prices = snapshot.get("close", {}) if isinstance(snapshot, dict) else {}
    prices = dict(close_prices) if isinstance(close_prices, dict) else {}
    execution_prices = ctx.get(MarketDataModule.current_prices, {}) or {}
    from tools.testers.backtest.modules.trading_rule import _lookup_product_value

    for component in components:
        product = component.order.instrument
        value = _lookup_product_value(execution_prices, product)
        if value is not None:
            prices[product] = value
    history_by_ledger = {id(item.ledger): item.historical for item in components}
    total = 0.0
    for ledger_key, historical in history_by_ledger.items():
        for product, entry in positions.get(ledger_key, {}).items():
            quantity = float(getattr(entry, "quantity", 0.0) or 0.0)
            if abs(quantity) <= 1e-12:
                continue
            multiplier = contract_multiplier_from_fields(
                historical, product,
                state=state, timestamp=ctx.timestamp,
            )
            price = _lookup_product_value(prices, product)
            if price is None:
                raise KeyError(
                    f"projected gross notional missing causal/execution price for {product}"
                )
            total += abs(quantity) * float(price) * multiplier
    return total
