import pandas as pd
import pytest

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.market_events import (
    MarketFeedEvent,
    MarketFeedEventKind,
)
from tools.testers.backtest.engines.native.orders.enums import OrderStatus
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.engines.native.strategy_hooks import StrategyContext


def _context(strategy, kind, payload):
    return FlowContext(
        timestamp=pd.Timestamp("2025-01-01 09:00"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={strategy: [EventDraft(kind, pd.Timestamp("2025-01-01 09:00"), strategy, payload)]},
        event_kind=kind,
    )


def _strategy_with_hook(hook_name):
    def hook(self, ctx, payload):
        self.seen.append(hook_name)

    def init(self, **kwargs):
        super(type(self), self).__init__(**kwargs)
        self.seen = []

    return type(
        "HookStrategy",
        (Strategy,),
        {"__init__": init, hook_name: hook},
    )(alias=f"dispatch-{hook_name}")


@pytest.mark.parametrize(
    ("status", "hook_name"),
    [
        (OrderStatus.BLOCKED, "on_order_blocked"),
        (OrderStatus.SUBMITTED, "on_order_submitted"),
        (OrderStatus.ACCEPTED, "on_order_accepted"),
        (OrderStatus.PARTIALLY_FILLED, "on_order_partially_filled"),
        (OrderStatus.CANCEL_PENDING, "on_order_cancel_pending"),
        (OrderStatus.REPLACE_PENDING, "on_order_replace_pending"),
        (OrderStatus.FILLED, "on_order_filled"),
        (OrderStatus.CANCELLED, "on_order_canceled"),
        (OrderStatus.REJECTED, "on_order_rejected"),
        (OrderStatus.EXPIRED, "on_order_expired"),
    ],
)
def test_order_status_dispatches_to_specific_hook(status, hook_name):
    strategy = _strategy_with_hook(hook_name)
    order = type("OrderView", (), {"status": status})()

    from tools.testers.backtest.modules.strategy_hooks.dispatch import _call_order_event

    _call_order_event(
        object(),
        _context(strategy, EventKind.ORDER, order),
    )

    assert strategy.seen == [hook_name]


def test_book_snapshot_dispatches_to_specific_hook():
    strategy = _strategy_with_hook("on_book_snapshot")
    event = MarketFeedEvent(
        pd.Timestamp("2025-01-01 09:00"), "P1",
        MarketFeedEventKind.BOOK_SNAPSHOT,
        {"level": "L2_MBP", "bids": [], "asks": []},
    )

    from tools.testers.backtest.modules.strategy_hooks.dispatch import _call_market_feed

    _call_market_feed(object(), _context(strategy, EventKind.MARKET_FEED, event))

    assert strategy.seen == ["on_book_snapshot"]
