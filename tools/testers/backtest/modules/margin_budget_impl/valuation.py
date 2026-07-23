"""Projected gross-notional valuation."""

from __future__ import annotations

from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_multiplier_from_fields,
)


def gross_notional(state, ctx, components, positions: dict[int, dict]) -> float:
    prices = ctx.get(MarketDataModule.current_prices, {}) or {}
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
            total += abs(quantity) * float(prices[product]) * multiplier
    return total
