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
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.cash_pool import cash_for_ledger
from tools.testers.backtest.modules.strategy_book import StrategyBookModule, available_cash_for_ledger
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.margin import MarginModule
from tools.testers.backtest.modules.trading_rule import TradingRuleModule


class LedgerCashConstraintModule(ExecutableModule):
    key: ClassVar[str] = "cash_rescale"
    label: ClassVar[str] = "现金调整"

    constrain_to_ledger_cash: ClassVar[Flow] = Flow(
        "constrain_to_ledger_cash",
        inputs=(
            OrderConstructModule.orders,
            MarketDataModule.current_prices,
            MarketDataModule.current_historical_fields,
            FeeModule.fee_mode,
            FeeModule.fixed_fee_rate,
            MarginModule.margin_mode,
            MarginModule.fixed_margin_ratio,
            TradingRuleModule.accounting_mode,
            TradingRuleModule.cost_basis_method,
            TradingRuleModule.daily_mark_to_market_enabled,
            OrderConstructModule.quantity_rounding_policy,
            TradingRuleModule.use_int_position,
            StrategyBookModule.cash_reserve_ratio,
            StrategyBookModule.cash_reserve_major,
        ),
        outputs=(OrderConstructModule.orders,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=35,  # between construct_orders (30) and
                    # GroupMembershipModule.schedule_order_execution (40) --
                    # must haircut buy-side quantities BEFORE they're
                    # scheduled for execution, not after
        after=(OrderConstructModule.construct_orders,),
        description="按现金约束调整订单",
        compute=lambda state, ctx: _constrain_to_ledger_cash(state, ctx),
    )
    constrain_execution_to_ledger_cash: ClassVar[Flow] = Flow(
        "constrain_execution_to_ledger_cash",
        inputs=(
            MarketDataModule.current_prices,
            MarketDataModule.current_historical_fields,
            FeeModule.fee_mode,
            FeeModule.fixed_fee_rate,
            MarginModule.margin_mode,
            MarginModule.fixed_margin_ratio,
            TradingRuleModule.accounting_mode,
            TradingRuleModule.cost_basis_method,
            TradingRuleModule.daily_mark_to_market_enabled,
            OrderConstructModule.quantity_rounding_policy,
            TradingRuleModule.use_int_position,
            StrategyBookModule.cash_reserve_ratio,
            StrategyBookModule.cash_reserve_major,
        ),
        outputs=(OrderConstructModule.orders,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER,
        order=8,
        after=(FeeModule.resolve_fee_cost,),
        description="成交现金约束",
        compute=lambda state, ctx: constrain_order_batch_to_execution_cash(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (constrain_to_ledger_cash, constrain_execution_to_ledger_cash)


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
        orders = ctx.get_for(OrderConstructModule.orders, strategy, [])
        if not orders:
            continue
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        for order in orders:
            ledger = state.ledger_for(order)
            group = groups.setdefault(id(ledger), (ledger, []))
            group[1].append((strategy, [order], historical_fields))

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
        cash = cash_for_ledger(state, ledger)
        if cash is None:
            raise RuntimeError(f"ledger {getattr(ledger, 'ledger_id', ledger)!r} has no cash pool")
        raw_cash = cash.to_major()
        available = available_cash_for_ledger(state, ledger, raw_cash, reason="signal_order") + sell_proceeds
        if buy_cost <= available:
            continue
        scale = available / buy_cost
        for _strategy, orders, _historical_fields in entries:
            for o in orders:
                if o.quantity > 0:
                    before = float(o.quantity)
                    scaled = _round_execution_scaled_quantity(state, _strategy, o, float(o.quantity) * scale)
                    o.quantity = scaled
                    if abs(o.quantity) <= 1e-12:
                        o.set("reject_reason", "现金不足，订单数量缩减为 0")
                    store.record(
                        o,
                        step="cash_rescale",
                        label="按现金约束调整订单",
                        timestamp=ctx.timestamp,
                        details={
                            "before_quantity": before,
                            "after_quantity": float(o.quantity),
                            "scale": float(scale),
                            "available_cash": float(available),
                            "same_batch_sell_proceeds": float(sell_proceeds),
                        },
                    )


def constrain_order_batch_to_execution_cash(state, ctx) -> None:
    """Final ORDER-stage broker cash/margin check.

    This runs after execution price, slippage and fee have been resolved and
    before LedgerModule.apply_order_fill mutates the ledger. It is deliberately
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
        for order in orders:
            ledger = state.ledger_for(order)
            group = groups.setdefault(id(ledger), (ledger, []))
            group[1].append((strategy, [order], historical_fields))

    for ledger, entries in groups.values():
        cash = cash_for_ledger(state, ledger)
        if cash is None:
            raise KeyError(f"ledger {getattr(ledger, 'ledger_id', ledger)!r} has no cash field")
        available = available_cash_for_ledger(state, ledger, float(cash.to_major()), reason="execution_order")
        conservative_required = _execution_cash_required_upper_bound(state, ctx, ledger, entries)
        if conservative_required <= max(available, 0.0) + 1e-9:
            continue
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


def _execution_cash_required_upper_bound(state, ctx, ledger, entries: list[tuple[Any, list[Any], dict]]) -> float:
    """Conservative pre-check for the expensive simulated cash constraint.

    If this upper bound fits available cash, the exact sequential simulation
    cannot bind. The bound deliberately ignores same-batch releases and sell
    proceeds, and only counts fees, possible realized losses, and positive
    margin/notional requirements. When uncertain, it overestimates and lets the
    original exact path run.
    """
    prices = ctx.get(MarketDataModule.current_prices, {})
    positions = ledger.get(LedgerModule.positions, {})
    total = 0.0
    for strategy, orders, historical_fields in entries:
        config = state.config_for(strategy)
        ledger_config = state.ledger_config_for(ledger)
        for order in orders:
            price = float(order.get("effective_price", prices[order.instrument]))
            fee_cost = max(float(order.get("fee_cost", 0.0) or 0.0), 0.0)
            if _uses_margin_accounting_for_order(config, historical_fields, order.instrument, ledger_config):
                total += fee_cost + _margin_requirement_increase_upper_bound(
                    config,
                    positions,
                    order,
                    price,
                    historical_fields,
                    ledger_config,
                )
                total += max(-_realized_pnl_estimate_without_mutation(
                    config,
                    positions,
                    order,
                    price,
                    historical_fields,
                    ledger_config,
                ), 0.0)
            else:
                notional = contract_notional(price, order.quantity, historical_fields, order.instrument)
                total += max(notional + fee_cost, 0.0)
    return total


def _uses_margin_accounting_for_order(strategy_config, historical_fields: dict, product, ledger_config) -> bool:
    from tools.testers.backtest.modules.ledger_module import _uses_margin_accounting

    return _uses_margin_accounting(strategy_config, historical_fields, product, ledger_config)


def _margin_requirement_increase_upper_bound(
    strategy_config,
    positions: dict,
    order,
    price: float,
    historical_fields: dict,
    ledger_config,
) -> float:
    from tools.testers.backtest.modules.ledger_module import (
        _entry_margin_major,
        _resolved_margin_ratio_for_position_after_fill,
    )

    entry = positions.get(order.instrument)
    prior_quantity = float(getattr(entry, "quantity", 0.0) or 0.0)
    new_quantity = prior_quantity + float(order.quantity)
    before_margin = _entry_margin_major(entry) if entry is not None else 0.0
    multiplier = contract_multiplier_from_fields_for_bound(historical_fields, order.instrument)
    after_margin = abs(new_quantity) * price * multiplier * _resolved_margin_ratio_for_position_after_fill(
        strategy_config,
        historical_fields_for_bound(historical_fields, order.instrument),
        new_quantity,
        price,
        multiplier,
        ledger_config,
    )
    return max(after_margin - before_margin, 0.0)


def _realized_pnl_estimate_without_mutation(
    strategy_config,
    positions: dict,
    order,
    price: float,
    historical_fields: dict,
    ledger_config,
) -> float:
    from tools.testers.backtest.modules.ledger_module import _resolve_method, _same_direction
    from tools.testers.backtest.modules.engine import engine_mode_for

    entry = positions.get(order.instrument)
    if entry is None:
        return 0.0
    prior_quantity = float(getattr(entry, "quantity", 0.0) or 0.0)
    quantity = float(order.quantity)
    if prior_quantity == 0 or _same_direction(prior_quantity, quantity):
        return 0.0
    fields = historical_fields_for_bound(historical_fields, order.instrument)
    multiplier = contract_multiplier_from_fields_for_bound(historical_fields, order.instrument)
    method = _resolve_method(
        strategy_config,
        order.instrument,
        fields,
        require_exact=engine_mode_for(strategy_config) == "exact",
        ledger_config=ledger_config,
    )
    close_abs = min(abs(quantity), abs(prior_quantity))
    if method in {"FIFO", "LIFO", "HIFO"} and getattr(entry, "lots", None) is not None:
        return _lot_realized_pnl_without_mutation(entry.lots, method, close_abs, price, multiplier, prior_quantity)
    prior_cost = float(getattr(entry, "average_cost", None) or price)
    sign = 1.0 if prior_quantity > 0 else -1.0
    return close_abs * (price - prior_cost) * sign * multiplier


def _lot_realized_pnl_without_mutation(lots, method: str, close_abs: float, price: float, multiplier: float, prior_quantity: float) -> float:
    remaining = close_abs
    if method == "LIFO":
        iterator = reversed(lots)
    elif method == "HIFO":
        iterator = iter(sorted(lots, key=lambda lot: float(getattr(lot, "entry_price", 0.0)), reverse=True))
    else:
        iterator = iter(lots)
    raw = 0.0
    for lot in iterator:
        if remaining <= 1e-12:
            break
        take = min(remaining, abs(float(getattr(lot, "quantity", 0.0) or 0.0)))
        raw += take * (price - float(getattr(lot, "entry_price", price))) * multiplier
        remaining -= take
    return raw if prior_quantity > 0 else -raw


def contract_multiplier_from_fields_for_bound(historical_fields: dict, product) -> float:
    from tools.testers.backtest.modules.market_data import contract_multiplier_from_fields

    return contract_multiplier_from_fields(historical_fields, product)


def historical_fields_for_bound(historical_fields: dict, product) -> dict:
    from tools.testers.backtest.modules.market_data import historical_fields_for_product

    return historical_fields_for_product(historical_fields, product)


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
    from tools.testers.backtest.engines.native.position import Lot, ProductPosition

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
            margin_reserved=getattr(entry, "margin_reserved", None),
            settlement_price=getattr(entry, "settlement_price", None),
        )
    return cloned


def _round_execution_scaled_quantity(state, strategy, order, quantity: float) -> float:
    from tools.testers.backtest.modules.order_construct import OrderConstructModule, default_round_order_quantity
    from tools.testers.backtest.modules.market_data import market_data_store_for
    from tools.testers.backtest.modules.strategy_book import ledger_for_strategy_product
    from tools.testers.backtest.modules.trading_rule import _resolve_use_int_position

    lot_sizes = market_data_store_for(state).raw_input.get("lot_sizes") or {}
    policy = state.config_for(strategy).get(OrderConstructModule.quantity_rounding_policy, "floor_to_lot")
    lot_size = lot_sizes.get(order.instrument)
    if not lot_size:
        ledger = ledger_for_strategy_product(state, strategy, order.instrument)
        if _resolve_use_int_position(state.config_for(strategy), state.ledger_config_for(ledger)):
            lot_size = 1.0
    return default_round_order_quantity(quantity, lot_size, policy)


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
