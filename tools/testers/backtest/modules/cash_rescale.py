"""LedgerCashConstraintModule — cash and margin availability checks.

The SIGNAL flow is an early estimate: it uses the signal timestamp prices
because that is all order construction is allowed to know. The ORDER-stage
helper below is the final broker constraint: after the real execution price,
slippage and fee are known, it proportionally haircuts orders that would make
their shared ledger cash negative.
"""

from __future__ import annotations

from collections import deque
from typing import Any, ClassVar

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.order import OrderStatus
from tools.testers.backtest.engines.native.fields import ExecutableModule
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule, contract_notional
from tools.testers.backtest.modules.order_book import OrderBookModule
from tools.testers.backtest.modules.order_flow import order_flow_store_for


class LedgerCashConstraintModule(ExecutableModule):
    key: ClassVar[str] = "cash_rescale"
    label: ClassVar[str] = "现金调整"

    constrain_to_ledger_cash: ClassVar[Flow] = Flow(
        "constrain_to_ledger_cash",
        inputs=(OrderBookModule.orders, MarketDataModule.current_prices, MarketDataModule.current_historical_fields),
        outputs=(OrderBookModule.orders,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=35,  # between construct_orders (30) and
                    # GroupMembershipModule.schedule_order_execution (40) --
                    # must haircut buy-side quantities BEFORE they're
                    # scheduled for execution, not after
        after=(OrderBookModule.construct_orders,),
        description="按现金约束调整订单",
        compute=lambda state, ctx: _constrain_to_ledger_cash(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (constrain_to_ledger_cash,)


def _constrain_to_ledger_cash(state, ctx) -> None:
    """Groups by ledger, not by strategy: two strategies sharing one
    CustomBroker ledger_id draw on the same pool of cash in this batch, so
    the haircut must be computed against their COMBINED buy cost vs that one
    ledger's cash -- computing it per strategy against the ledger's full
    balance would let each strategy independently assume it can spend the
    whole pool, jointly overspending it."""
    prices = ctx.get(MarketDataModule.current_prices)
    store = order_flow_store_for(state)

    groups: dict[int, tuple[Any, list[tuple[Any, list[Any], dict]]]] = {}
    for strategy in ctx.active_strategies:
        orders = ctx.get_for(OrderBookModule.orders, strategy, [])
        if not orders:
            continue
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        ledger = state.ledger_for_strategy(strategy)
        group = groups.setdefault(id(ledger), (ledger, []))
        group[1].append((strategy, orders, historical_fields))

    for ledger, entries in groups.values():
        buy_cost = sum(
            contract_notional(prices[o.instrument], o.quantity, historical_fields, o.instrument)
            for _strategy, orders, historical_fields in entries
            for o in orders if o.quantity > 0
        )
        if buy_cost <= 0:
            continue
        sell_proceeds = sum(
            -contract_notional(prices[o.instrument], o.quantity, historical_fields, o.instrument)
            for _strategy, orders, historical_fields in entries
            for o in orders if o.quantity < 0
        )
        available = ledger.get(LedgerModule.cash).to_major() + sell_proceeds
        if buy_cost <= available:
            continue
        scale = available / buy_cost
        for _strategy, orders, _historical_fields in entries:
            for o in orders:
                if o.quantity > 0:
                    before = float(o.quantity)
                    o.quantity *= scale
                    store.record(
                        o,
                        step="cash_rescale",
                        label="按现金约束调整订单",
                        timestamp=ctx.timestamp,
                        details={
                            "before_quantity": before,
                            "scale": float(scale),
                            "available_cash": float(available),
                            "same_batch_sell_proceeds": float(sell_proceeds),
                        },
                    )


def constrain_order_batch_to_execution_cash(state, ctx) -> None:
    """Final ORDER-stage broker cash/margin check.

    This runs after execution price, slippage and fee have been resolved and
    before LedgerModule.cash_update mutates the ledger. It is deliberately
    grouped by ledger, not by strategy, so strategies that share a ledger also
    share its available cash.
    """
    store = order_flow_store_for(state)
    groups: dict[int, tuple[Any, list[tuple[Any, list[Any], dict]]]] = {}
    for strategy in ctx.active_strategies:
        orders = [
            order for order in ctx.payloads_for(strategy)
            if order.status != OrderStatus.CANCELLED and not order.get("reject_reason")
        ]
        if not orders:
            continue
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        ledger = state.ledger_for_strategy(strategy)
        group = groups.setdefault(id(ledger), (ledger, []))
        group[1].append((strategy, orders, historical_fields))

    for ledger, entries in groups.values():
        cash = ledger.get(LedgerModule.cash)
        if cash is None:
            raise KeyError(f"ledger {getattr(ledger, 'ledger_id', ledger)!r} has no cash field")
        available = float(cash.to_major())
        required_orders: list[tuple[Any, Any, float]] = []
        released = 0.0
        simulated_positions = _clone_positions_for_cash_check(ledger.get(LedgerModule.positions, {}))
        simulated_cash = cash
        for strategy, orders, historical_fields in entries:
            config = state.config_for(strategy)
            ledger_config = state.ledger_config_for(ledger)
            for order in orders:
                cash_delta = _estimated_execution_cash_delta(
                    simulated_cash,
                    simulated_positions,
                    config,
                    order,
                    historical_fields,
                    ledger_config,
                    ctx.get(MarketDataModule.current_prices, {}),
                )
                if cash_delta < -1e-12:
                    required_orders.append((strategy, order, -cash_delta))
                elif cash_delta > 1e-12:
                    released += cash_delta
                simulated_cash = simulated_cash + DataMoney.from_major(
                    cash_delta,
                    currency=cash.currency,
                    use_minor_units=cash.use_minor_units,
                )
        capacity = available + released
        required = sum(amount for _strategy, _order, amount in required_orders)
        if required <= max(capacity, 0.0) + 1e-9:
            continue
        if required <= 0 or capacity <= 0:
            scale = 0.0
        else:
            scale = capacity / required
        for strategy, order, _amount in required_orders:
            before = float(order.quantity)
            scaled = _round_execution_scaled_quantity(state, strategy, order, before * scale)
            order.quantity = scaled
            actual_scale = 0.0 if abs(before) <= 1e-12 else float(scaled / before)
            _scale_linear_fee_fields(order, actual_scale)
            if abs(order.quantity) <= 1e-12:
                order.set("reject_reason", "现金不足，订单数量缩减为 0")
            store.record(
                order,
                step="execution_cash_constraint",
                label="成交现金约束",
                timestamp=ctx.timestamp,
                details={
                    "before_quantity": before,
                    "after_quantity": float(order.quantity),
                    "scale": float(actual_scale),
                    "raw_scale": float(scale),
                    "available_cash": float(capacity),
                    "required_cash": float(required),
                },
            )


def _estimated_execution_cash_delta(
    cash: DataMoney,
    positions: dict,
    strategy_config,
    order,
    historical_fields: dict,
    ledger_config,
    current_prices: dict,
) -> float:
    from tools.testers.backtest.modules.ledger_module import (
        _apply_margin_accounting_fill,
        _uses_margin_accounting,
    )

    price = float(order.get("effective_price", current_prices[order.instrument]))
    fee_cost = float(order.get("fee_cost", 0.0) or 0.0)
    if _uses_margin_accounting(strategy_config, historical_fields, order.instrument, ledger_config):
        after = _apply_margin_accounting_fill(
            cash,
            positions,
            strategy_config,
            order.instrument,
            quantity=float(order.quantity),
            price=price,
            fee_cost=fee_cost,
            historical_fields=historical_fields,
            ledger_config=ledger_config,
        )
        return float(after.to_major() - cash.to_major())
    return -(
        contract_notional(price, order.quantity, historical_fields, order.instrument)
        + fee_cost
    )


def _clone_positions_for_cash_check(positions: dict) -> dict:
    from tools.testers.backtest.engines.native.ledger import Lot, ProductPosition

    cloned = {}
    for product, entry in positions.items():
        lots = getattr(entry, "lots", None)
        cloned[product] = ProductPosition(
            quantity=getattr(entry, "quantity", 0.0),
            average_cost=getattr(entry, "average_cost", None),
            lots=deque(
                Lot(
                    quantity=lot.quantity,
                    entry_price=lot.entry_price,
                    multiplier=lot.multiplier,
                    is_today=lot.is_today,
                )
                for lot in lots
            ) if lots is not None else None,
            equity_occupied=getattr(entry, "equity_occupied", None),
            settlement_price=getattr(entry, "settlement_price", None),
        )
    return cloned


def _round_execution_scaled_quantity(state, strategy, order, quantity: float) -> float:
    from tools.testers.backtest.modules.position_sizing import PositionSizingModule, _round_one
    from tools.testers.backtest.modules.market_data import market_data_store_for

    lot_sizes = market_data_store_for(state).raw_input.get("lot_sizes") or {}
    policy = state.config_for(strategy).get(PositionSizingModule.quantity_rounding_policy, "floor_to_lot")
    return _round_one(quantity, lot_sizes.get(order.instrument), policy)


def _scale_linear_fee_fields(order, scale: float) -> None:
    for key in (
        "fee_cost",
        "fee_open_quantity",
        "fee_close_quantity",
        "fee_close_today_quantity",
        "fee_close_yesterday_quantity",
    ):
        value = order.get(key, None)
        if value is not None:
            order.set(key, float(value) * scale)
