"""Resolve strategy fee policy for one ORDER batch."""

from __future__ import annotations

from tools.testers.backtest.modules.engine import engine_mode_for
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    contract_multiplier_from_product_fields,
    historical_fields_for_product,
)
from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.trading_rule import _resolve_method

from .market import market_fee_cost
from .mode import resolve_fee_mode
from .observability import record_fee_runtime_assumption


def resolve_fee_cost(state, ctx) -> None:
    prices = ctx.get(MarketDataModule.current_prices)
    audit_store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields, strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        for order in ctx.payloads_for(strategy):
            if order.get("reject_reason"):
                continue
            ledger = state.ledger_for(order)
            ledger_config = state.ledger_config_for(ledger)
            mode = resolve_fee_mode(config, ledger_config)
            fields = historical_fields_for_product(
                historical_fields, order.instrument,
            )
            record_fee_runtime_assumption(
                state,
                strategy=strategy,
                product=order.instrument,
                timestamp=ctx.timestamp,
                mode=mode,
                fields=fields,
            )
            fixed_rate = float(
                getattr(ledger_config, "fixed_fee_rate", None) or 0.0
            )
            effective_price = order.get("effective_price")
            price = float(
                effective_price
                if effective_price is not None
                else prices[order.instrument]
            )
            fixed_fee = resolve_fixed_fee_cost(
                mode, fixed_rate, order.quantity, price,
                contract_multiplier_from_product_fields(
                    fields,
                    state=state, product=order.instrument,
                    timestamp=ctx.timestamp,
                ),
            )
            if fixed_fee is not None:
                order.set("fee_cost", fixed_fee)
                record_fee(
                    audit_store, order, ctx.timestamp, mode,
                    {"fixed_rate": fixed_rate},
                )
                continue
            cost_method = _resolve_method(
                config, order.instrument, fields,
                require_exact=engine_mode_for(config) == "exact",
                ledger_config=ledger_config,
            )
            positions = ledger.get(LedgerModule.positions, {})
            order.set("fee_cost", market_fee_cost(
                order, price=price, fields=fields,
                position=positions.get(order.instrument),
                fee_mode=mode, cost_basis_method=cost_method,
            ))
            record_fee(audit_store, order, ctx.timestamp, mode)


def resolve_fixed_fee_cost(
    mode: str, fixed_rate: float, quantity: float,
    price: float, multiplier: float,
) -> float | None:
    if mode == "zero":
        return 0.0
    if mode == "fixed":
        return abs(quantity) * price * multiplier * fixed_rate
    return None


def record_fee(audit_store, order, timestamp, mode: str, details=None) -> None:
    audit_store.record(
        order, step="fee", label="计算手续费", timestamp=timestamp,
        details={"mode": mode, **(details or {})},
    )
