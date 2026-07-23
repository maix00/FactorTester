"""Shared cash-constraint batch components and quantity application."""

from __future__ import annotations

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_flow import order_flow_store_for

from .orders import combine_preserving_reduction, split_reducing_and_increasing


def components(entries, positions):
    result = []
    for entry in entries:
        _strategy, order, ledger, _historical = entry
        position = positions[id(ledger)].get(order.instrument)
        prior = float(getattr(position, "quantity", 0.0) or 0.0)
        result.append((entry, *split_reducing_and_increasing(prior, float(order.quantity))))
    return result


def apply_scale(
    state, ctx, parts, constrained, scale, capacity, required, *,
    step: str, label: str, recalculate_fee: bool,
) -> None:
    from tools.testers.backtest.modules.cash_constraint.fees import estimate_signal_fee
    from tools.testers.backtest.modules.cash_rescale import _round_execution_scaled_quantity

    store = order_flow_store_for(state)
    prices = ctx.get(MarketDataModule.current_prices, {}) or {}
    for entry, reducing, increasing in parts:
        strategy, order, ledger, historical = entry
        if abs(increasing) <= 1e-12 or id(order) not in constrained:
            continue
        before = float(order.quantity)
        combined = combine_preserving_reduction(reducing, increasing, scale)
        rounded = _round_execution_scaled_quantity(state, strategy, order, combined)
        if abs(rounded) + 1e-12 < abs(reducing):
            rounded = reducing
        order.quantity = rounded
        if recalculate_fee:
            effective_price = order.get("effective_price")
            price = float(
                effective_price
                if effective_price is not None
                else prices[order.instrument]
            )
            order.set("fee_cost", estimate_signal_fee(
                state, ctx, strategy, ledger, order, historical,
                ledger.get(LedgerModule.positions, {}), price,
            ))
        if abs(rounded) <= 1e-12:
            order.set("reject_reason", "可用资金不足，增仓数量缩减为 0")
        store.record(order, step=step, label=label, timestamp=ctx.timestamp, details={
            "before_quantity": before, "after_quantity": rounded,
            "scale": scale, "available_cash": capacity, "required_cash": required,
        })


def add_cash(cash: DataMoney, delta: float) -> DataMoney:
    return cash + DataMoney.from_major(
        delta, currency=cash.currency, use_minor_units=cash.use_minor_units,
    )
