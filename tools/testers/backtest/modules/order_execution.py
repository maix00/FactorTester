"""OrderExecutionModule — fixed next-bar-open order execution.

`GroupMembershipModule` decides which bar an order targets and stores the
target price row on the order. This module turns that target row's open price
into the order's effective base fill price. Slippage, fees and ledger updates
then consume `order.effective_price`.
"""

from __future__ import annotations

from typing import Any, ClassVar, cast

import pandas as pd

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.market_data import MarketDataModule, market_price_tables_for
from tools.testers.backtest.modules.order_flow import order_flow_store_for
from tools.testers.backtest.modules.time_index_lookup import row_at
from .base import ExecutableModule, FieldDefinition, FieldRef


class OrderExecutionModule(ExecutableModule):
    key: ClassVar[str] = "order_execution"
    label: ClassVar[str] = "订单执行"

    execution_price_basis: ClassVar[FieldRef[str]] = FieldRef("execution_price_basis")
    volume_execution_price_basis: ClassVar[FieldRef[str]] = FieldRef("volume_execution_price_basis")
    order_type: ClassVar[FieldRef[str]] = FieldRef("order_type")
    matching_model: ClassVar[FieldRef[str]] = FieldRef("matching_model")
    execution_prices: ClassVar[FieldRef[Any]] = FieldRef("execution_prices")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "execution_price_basis": FieldDefinition(
            public=False, label="价格", default="open", control_template="select", tab="order",
            options=(("open", "下一 bar 开盘价"),),
            chip_template="价格: {value}", tab_label="订单执行", tab_order=120,
        ),
        "volume_execution_price_basis": FieldDefinition(
            public=True, label="容量撮合价格", default="close", control_template="select", tab="order",
            options=(("close", "执行 bar 收盘价"), ("vwap", "执行 bar VWAP"), ("twap", "执行 bar TWAP")),
            visible_when={"matching_model": ("auto", "bar_volume_limited")},
            chip_template="容量价格: {value}", tab_label="订单执行", tab_order=120,
            help_text="完整 execution-bar volume 只能在 bar 完成后使用；价格代理也在该时点确认。",
        ),
        "order_type": FieldDefinition(
            public=True, label="订单", default="market", control_template="select", tab="order",
            options=(("market", "市价单"), ("limit", "限价单")),
            chip_template="订单: {value}", tab_label="订单执行", tab_order=120,
        ),
        "matching_model": FieldDefinition(
            public=True, label="撮合", default="auto", control_template="select", tab="order",
            options=(
                ("auto", "按流动性模式自动"),
                ("next_bar_full_fill", "下一 bar 全额成交"),
                ("bar_volume_limited", "执行 bar 完成后按成交量限制"),
            ),
            chip_template="撮合: {value}", tab_label="订单执行", tab_order=120,
        ),
        "execution_prices": FieldDefinition(public=False, display_value_kind="execution_price_table"),
    }

    resolve_execution_price: ClassVar[Flow] = Flow(
        "resolve_execution_price",
        inputs=(execution_price_basis, MarketDataModule.current_prices, MarketDataModule.current_order_constraints),
        outputs=(execution_prices,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER,
        order=5,
        description="解析订单成交价",
        event_payload_inputs=("order",),
        compute=lambda state, ctx: _resolve_execution_price(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (resolve_execution_price,)


def _normalise_price_basis(value: object) -> str:
    basis = str(value or "open").lower()
    if basis not in {"open", "close", "vwap", "twap"}:
        raise ValueError(f"unsupported execution price basis: {basis!r}")
    return basis


def _price_table(state: Any, basis: str) -> pd.DataFrame:
    tables = market_price_tables_for(state)
    if isinstance(tables, dict):
        table = tables.get(basis)
        if isinstance(table, pd.DataFrame) and not table.empty:
            return table
    raise KeyError(f"market data does not provide execution price basis {basis!r}")


def _execution_price_at(state: Any, order: Any, basis: str) -> float:
    timestamp = cast(pd.Timestamp, order.get("price_timestamp", order.timestamp))
    table = _price_table(state, basis)
    row = row_at(table, timestamp, asof=False)
    return float(cast(Any, row[order.instrument]))


def _resolve_execution_price(state: Any, ctx: Any) -> None:
    resolved: dict[Any, dict[Any, float]] = {}
    constraints = ctx.get(MarketDataModule.current_order_constraints, {})
    current_prices = ctx.get(MarketDataModule.current_prices, {}) or {}
    store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        prices: dict[Any, float] = {}
        for order in ctx.payloads_for(strategy):
            basis = _normalise_price_basis(order.get(
                "execution_price_basis",
                config.get(OrderExecutionModule.execution_price_basis, "open"),
            ))
            if basis != "open" and order.get("matching_model") != "bar_volume_limited":
                raise ValueError("next-bar full-fill execution requires next-bar open price")
            price = current_prices.get(order.instrument)
            if price is None:
                price = _execution_price_at(state, order, basis)
            order.set("execution_price_basis", basis)
            order.set("effective_price", float(price))
            reject_reason = _reject_reason_for_order(order, constraints)
            if reject_reason:
                order.set("reject_reason", reject_reason)
                store.record(
                    order,
                    step="execution_constraint",
                    label="订单交易约束拒绝",
                    timestamp=ctx.timestamp,
                    details={"reject_reason": reject_reason},
                )
            else:
                store.record(
                    order,
                    step="resolve_execution_price",
                    label="解析成交价",
                    timestamp=ctx.timestamp,
                    details={"basis": basis, "price": float(price)},
                )
            prices[order.instrument] = float(price)
        ctx.set_for(OrderExecutionModule.execution_prices, strategy, prices)
        resolved[strategy] = prices
    ctx.set(OrderExecutionModule.execution_prices, resolved)


def _reject_reason_for_order(order: Any, constraints: Any) -> str | None:
    if not isinstance(constraints, dict):
        return "缺少订单交易约束"
    constraint = constraints.get(order.instrument)
    if constraint is None:
        return "缺少订单交易约束"
    if not bool(getattr(constraint, "tradable", True)):
        return str(getattr(constraint, "reason", "") or "当前不可交易")
    if float(getattr(order, "quantity", 0.0) or 0.0) > 0 and not bool(getattr(constraint, "can_buy", True)):
        return str(getattr(constraint, "reason", "") or "买入方向不可成交")
    if float(getattr(order, "quantity", 0.0) or 0.0) < 0 and not bool(getattr(constraint, "can_sell", True)):
        return str(getattr(constraint, "reason", "") or "卖出方向不可成交")
    return None
