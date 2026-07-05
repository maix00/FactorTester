from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.order import Order, OrderStatus
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.order_lifecycle import _finalize_order


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


def _ctx_for(order, strategy):
    draft = EventDraft(EventKind.ORDER, order.timestamp, strategy, order)
    return FlowContext(
        timestamp=order.timestamp, event_queue=EventQueue(),
        active_strategies=frozenset({strategy}), drafts_by_strategy={strategy: [draft]},
    )


def test_scheduled_order_without_terminal_status_raises():
    s = Strategy(alias="S")
    order = Order(instrument=_product(), timestamp=pd.Timestamp("2024-01-01"),
                   quantity=1.0, intent_quantity=1.0, strategy=s, status=OrderStatus.SCHEDULED)
    account = BacktestRunState(strategy_configs={s: StrategyConfig(strategy=s)})
    with pytest.raises(RuntimeError, match="without terminal status"):
        _finalize_order(account, _ctx_for(order, s))


def test_rejected_order_is_recorded():
    s = Strategy(alias="S")
    order = Order(instrument=_product(), timestamp=pd.Timestamp("2024-01-01"),
                   quantity=1.0, intent_quantity=1.0, strategy=s, status=OrderStatus.REJECTED)
    order.set("reject_reason", "insufficient margin")
    order.reject_reason = "insufficient margin"
    account = BacktestRunState(strategy_configs={s: StrategyConfig(strategy=s)})
    _finalize_order(account, _ctx_for(order, s))
    assert order.status == OrderStatus.REJECTED
    assert order.reject_reason == "insufficient margin"


def test_cancelled_order_is_left_untouched():
    s = Strategy(alias="S")
    order = Order(instrument=_product(), timestamp=pd.Timestamp("2024-01-01"),
                   quantity=1.0, intent_quantity=1.0, strategy=s, status=OrderStatus.CANCELLED)
    account = BacktestRunState(strategy_configs={s: StrategyConfig(strategy=s)})
    _finalize_order(account, _ctx_for(order, s))
    assert order.status == OrderStatus.CANCELLED


def test_multiple_orders_in_one_batch_finalize_independently():
    s1, s2 = Strategy(alias="A"), Strategy(alias="B")
    order1 = Order(instrument=_product(), timestamp=pd.Timestamp("2024-01-01"),
                    quantity=1.0, intent_quantity=1.0, strategy=s1, status=OrderStatus.FILLED)
    order2 = Order(instrument=_product(), timestamp=pd.Timestamp("2024-01-01"),
                    quantity=1.0, intent_quantity=1.0, strategy=s2, status=OrderStatus.REJECTED)
    order2.set("reject_reason", "no liquidity")
    order2.reject_reason = "no liquidity"

    draft1 = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s1, order1)
    draft2 = EventDraft(EventKind.ORDER, pd.Timestamp("2024-01-01"), s2, order2)
    ctx = FlowContext(
        timestamp=pd.Timestamp("2024-01-01"), event_queue=EventQueue(),
        active_strategies=frozenset({s1, s2}), drafts_by_strategy={s1: [draft1], s2: [draft2]},
    )
    account = BacktestRunState(strategy_configs={s1: StrategyConfig(strategy=s1), s2: StrategyConfig(strategy=s2)})
    _finalize_order(account, ctx)
    assert order1.status == OrderStatus.FILLED
    assert order2.status == OrderStatus.REJECTED
