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
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.time_index_lookup import row_at
from .base import ExecutableModule, FieldDefinition, FieldRef


class OrderExecutionModule(ExecutableModule):
    key: ClassVar[str] = "order_execution"
    label: ClassVar[str] = "订单执行"

    execution_price_basis: ClassVar[FieldRef[str]] = FieldRef("execution_price_basis")
    order_type: ClassVar[FieldRef[str]] = FieldRef("order_type")
    matching_model: ClassVar[FieldRef[str]] = FieldRef("matching_model")
    execution_prices: ClassVar[FieldRef[Any]] = FieldRef("execution_prices")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "execution_price_basis": FieldDefinition(
            public=False, label="价格", default="open", control_template="select", tab="order",
            options=(("open", "下一 bar 开盘价"),),
            chip_template="价格: {value}", tab_label="订单执行", tab_order=120,
        ),
        "order_type": FieldDefinition(
            public=True, label="订单", default="market", control_template="select", tab="order",
            options=(("market", "市价单"), ("limit", "限价单")),
            chip_template="订单: {value}", tab_label="订单执行", tab_order=120,
        ),
        "matching_model": FieldDefinition(
            public=True, label="撮合", default="next_bar_full_fill", control_template="select", tab="order",
            options=(
                ("next_bar_full_fill", "下一 bar 全额成交"),
                ("bar_volume_limited", "按 bar 成交量限制"),
            ),
            chip_template="撮合: {value}", tab_label="订单执行", tab_order=120,
        ),
        "execution_prices": FieldDefinition(public=False),
    }

    resolve_execution_price: ClassVar[Flow] = Flow(
        "resolve_execution_price",
        inputs=(execution_price_basis, MarketDataModule.current_prices),
        outputs=(execution_prices,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER,
        order=5,
        compute=lambda account, ctx: _resolve_execution_price(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (resolve_execution_price,)


def _normalise_price_basis(value: object) -> str:
    basis = str(value or "open").lower()
    if basis != "open":
        raise ValueError("order execution is fixed to next-bar open price")
    return basis


def _price_table(account: Any, basis: str) -> pd.DataFrame:
    tables = getattr(account, "market_price_tables", None)
    if isinstance(tables, dict):
        table = tables.get(basis)
        if isinstance(table, pd.DataFrame) and not table.empty:
            return table
    raise KeyError(f"market data does not provide execution price basis {basis!r}")


def _execution_price_at(account: Any, order: Any, basis: str) -> float:
    timestamp = cast(pd.Timestamp, order.get("price_timestamp", order.timestamp))
    table = _price_table(account, basis)
    row = row_at(table, timestamp, asof=False)
    return float(cast(Any, row[order.instrument]))


def _resolve_execution_price(account: Any, ctx: Any) -> None:
    resolved: dict[Any, dict[Any, float]] = {}
    for strategy in ctx.active_strategies:
        config = account.config_for(strategy)
        basis = _normalise_price_basis(config.get(OrderExecutionModule.execution_price_basis, "open"))
        prices: dict[Any, float] = {}
        for order in ctx.payloads_for(strategy):
            price = _execution_price_at(account, order, basis)
            order.set("execution_price_basis", basis)
            order.set("effective_price", price)
            prices[order.instrument] = price
        ctx.set_for(OrderExecutionModule.execution_prices, strategy, prices)
        resolved[strategy] = prices
    ctx.set(OrderExecutionModule.execution_prices, resolved)
