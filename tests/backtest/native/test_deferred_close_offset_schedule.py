from __future__ import annotations

import pandas as pd

from tools.products.Product import Product
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.order import (
    Order,
    OrderLegRole,
    OrderOffset,
)
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.group.execution import schedule_order_execution
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.order_execution import OrderExecutionModule


class _TradingDayResolver:
    def resolve_trading_day(self, timestamp, *, instrument):
        assert instrument == "P"
        return pd.Timestamp(timestamp).date()


def test_scheduler_reclassifies_close_today_before_deferred_order_event():
    strategy = Strategy(alias="S")
    product = Product(name="P", point_value=1, currency="CNY")
    state = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, field_values={
            GroupMembershipModule.execution_timing: "next_bar",
            OrderExecutionModule.execution_price_basis: "open",
        }),
    })
    signal_ts = pd.Timestamp("2025-01-02 15:00")
    execution_ts = pd.Timestamp("2025-01-03 09:00")
    state.market_data_store.current_prices_table = pd.DataFrame(
        {product: [100.0, 101.0]}, index=[signal_ts, execution_ts],
    )
    state.market_data_store.trading_day_resolver = _TradingDayResolver()
    order = Order(
        instrument=product,
        timestamp=signal_ts,
        quantity=-1,
        intent_quantity=-1,
        strategy=strategy,
        offset=OrderOffset.CLOSE_TODAY,
        leg_role=OrderLegRole.CLOSE_TODAY,
    )
    ctx = FlowContext(
        timestamp=signal_ts,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set_for(OrderConstructModule.orders, strategy, [order])

    schedule_order_execution(state, ctx)

    assert order.offset is OrderOffset.CLOSE_YESTERDAY
    assert order.leg_role is OrderLegRole.CLOSE_YESTERDAY
    assert order.get("offset_signal_trading_day") == "2025-01-02"
    assert order.get("offset_execution_trading_day") == "2025-01-03"
