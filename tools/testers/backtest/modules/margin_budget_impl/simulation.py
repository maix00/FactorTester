"""Execution-price portfolio simulation for the hard margin limit."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from typing import Any

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.modules.market_data import MarketDataModule

from .valuation import gross_notional


@dataclass(frozen=True)
class OrderComponent:
    strategy: Any
    order: Any
    ledger: Any
    historical: dict
    reducing: float
    increasing: float
    product_fields: dict | None = None


@dataclass(frozen=True)
class PortfolioProjection:
    positions: dict[int, dict]
    cash: DataMoney
    margin: float
    equity: float
    utilization: float
    gross_notional: float


def project_components(
    state: Any,
    ctx: Any,
    components: list[OrderComponent],
    positions: dict[int, dict],
    cash: DataMoney,
    starting_equity: float,
    starting_margin: float,
    *,
    include_reducing: bool,
    increasing_scale: float,
) -> PortfolioProjection:
    from tools.testers.backtest.modules.cash_rescale import _clone_positions_for_cash_check

    working = {key: _clone_positions_for_cash_check(value) for key, value in positions.items()}
    current_cash = cash
    total_delta = 0.0
    prices = ctx.get(MarketDataModule.current_prices, {}) or {}
    strategy_configs: dict[Any, Any] = {}
    ledger_configs: dict[int, tuple[Any, Any]] = {}
    for component in components:
        strategy_config = strategy_configs.get(component.strategy)
        if strategy_config is None:
            strategy_config = state.config_for(component.strategy)
            strategy_configs[component.strategy] = strategy_config
        ledger_key = id(component.ledger)
        ledger_entry = ledger_configs.get(ledger_key)
        if ledger_entry is None or ledger_entry[0] is not component.ledger:
            ledger_entry = (component.ledger, state.ledger_config_for(component.ledger))
            ledger_configs[ledger_key] = ledger_entry
        ledger_config = ledger_entry[1]
        quantities = []
        if include_reducing and abs(component.reducing) > 1e-12:
            quantities.append(component.reducing)
        scaled = component.increasing * increasing_scale
        if abs(scaled) > 1e-12:
            quantities.append(scaled)
        for quantity in quantities:
            delta = _apply_quantity(
                state, ctx, component, quantity, working, current_cash,
                strategy_config=strategy_config,
                ledger_config=ledger_config,
                prices=prices,
            )
            total_delta += delta
            current_cash = _add_cash(current_cash, delta)
    margin = margin_reserved(state, ctx, components, working)
    equity = starting_equity + total_delta + (margin - starting_margin)
    gross = gross_notional(state, ctx, components, working)
    utilization = float("inf") if equity <= 0 else margin / equity
    return PortfolioProjection(working, current_cash, margin, equity, utilization, gross)


def _apply_quantity(
    state, ctx, component, quantity, positions, cash, *,
    strategy_config=None, ledger_config=None, prices=None,
) -> float:
    from tools.testers.backtest.modules.cash_constraint.fees import estimate_signal_fee
    from tools.testers.backtest.modules.cash_rescale import _estimated_execution_cash_delta

    candidate = copy(component.order)
    candidate.quantity = quantity
    prices = prices if prices is not None else ctx.get(MarketDataModule.current_prices, {}) or {}
    effective_price = candidate.get("effective_price")
    price = float(
        effective_price
        if effective_price is not None
        else prices[candidate.instrument]
    )
    candidate.set("effective_price", price)
    candidate.set("fee_cost", estimate_signal_fee(
        state, ctx, component.strategy, component.ledger, candidate,
        component.historical, positions[id(component.ledger)], price,
        strategy_config=strategy_config,
        ledger_config=ledger_config,
        product_fields=component.product_fields,
    ))
    from tools.testers.backtest.modules.cash_pool import (
        account_cash_or_zero,
        cash_amount_to_pool_base,
    )

    delta = _estimated_execution_cash_delta(
        account_cash_or_zero(state, component.ledger),
        positions[id(component.ledger)],
        strategy_config,
        candidate,
        component.historical,
        ledger_config,
        prices,
        product_fields=component.product_fields,
    )
    return cash_amount_to_pool_base(
        state, component.ledger, delta, timestamp=ctx.timestamp,
        include_conversion_cost=True,
    )


def margin_reserved(state, ctx, components, positions: dict[int, dict]) -> float:
    from tools.testers.backtest.modules.cash_pool import cash_amount_to_pool_base

    ledgers = {id(component.ledger): component.ledger for component in components}
    return sum(
        cash_amount_to_pool_base(
            state, ledgers[ledger_key], float(entry.margin_reserved.to_major()),
            timestamp=ctx.timestamp,
        )
        for ledger_key, ledger_positions in positions.items()
        for entry in ledger_positions.values()
        if getattr(entry, "margin_reserved", None) is not None
    )


def _add_cash(cash: DataMoney, delta: float) -> DataMoney:
    return cash + DataMoney.from_major(
        delta, currency=cash.currency, use_minor_units=cash.use_minor_units,
    )
