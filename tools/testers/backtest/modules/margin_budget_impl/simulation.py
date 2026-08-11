"""Execution-price portfolio simulation for the hard margin limit."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from typing import Any

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.modules.ledger_module import LedgerModule
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
            )
            total_delta += delta
            current_cash = _add_cash(current_cash, delta)
    margin = margin_reserved(working)
    equity = starting_equity + total_delta + (margin - starting_margin)
    gross = gross_notional(state, ctx, components, working)
    utilization = float("inf") if equity <= 0 else margin / equity
    return PortfolioProjection(working, current_cash, margin, equity, utilization, gross)


def _apply_quantity(
    state, ctx, component, quantity, positions, cash, *,
    strategy_config=None, ledger_config=None,
) -> float:
    from tools.testers.backtest.modules.cash_constraint.fees import estimate_signal_fee
    from tools.testers.backtest.modules.cash_rescale import _estimated_execution_cash_delta

    candidate = copy(component.order)
    candidate.quantity = quantity
    prices = ctx.get(MarketDataModule.current_prices, {}) or {}
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
    ))
    return _estimated_execution_cash_delta(
        cash,
        positions[id(component.ledger)],
        strategy_config,
        candidate,
        component.historical,
        ledger_config,
        prices,
    )


def margin_reserved(positions: dict[int, dict]) -> float:
    return sum(
        float(entry.margin_reserved.to_major())
        for ledger_positions in positions.values()
        for entry in ledger_positions.values()
        if getattr(entry, "margin_reserved", None) is not None
    )


def _add_cash(cash: DataMoney, delta: float) -> DataMoney:
    return cash + DataMoney.from_major(
        delta, currency=cash.currency, use_minor_units=cash.use_minor_units,
    )
