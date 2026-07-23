from __future__ import annotations

import pandas as pd
import pytest

from tools.testers.backtest.engines.native.order import (
    Order,
    OrderLegRole,
    OrderOffset,
)
from tools.testers.backtest.modules.order_lifecycle.offsets import (
    reclassify_deferred_close_today,
)


class _TradingDays:
    def __init__(self, days):
        self.days = iter(days)

    def resolve_trading_day(self, _timestamp, *, instrument):
        assert instrument == "P"
        return next(self.days)


def _order(offset=OrderOffset.CLOSE_TODAY):
    return Order(
        instrument="P",
        timestamp=pd.Timestamp("2025-01-02 15:00"),
        quantity=-1,
        intent_quantity=-1,
        strategy="S",
        offset=offset,
        leg_role=OrderLegRole.CLOSE_TODAY,
    )


def test_close_today_becomes_yesterday_across_execution_trading_day():
    order = _order()

    changed = reclassify_deferred_close_today(
        order,
        signal_timestamp="2025-01-02 15:00",
        market_timestamp="2025-01-03 09:00",
        trading_day_resolver=_TradingDays(["2025-01-02", "2025-01-03"]),
    )

    assert changed is True
    assert order.offset is OrderOffset.CLOSE_YESTERDAY
    assert order.leg_role is OrderLegRole.CLOSE_YESTERDAY
    assert order.get("original_offset") == "close_today"
    assert order.get("offset_reclassification_reason") == (
        "execution_trading_day_changed"
    )


def test_night_session_same_trading_day_stays_close_today():
    order = _order()

    changed = reclassify_deferred_close_today(
        order,
        signal_timestamp="2025-01-02 15:00",
        market_timestamp="2025-01-02 21:00",
        trading_day_resolver=_TradingDays(["2025-01-03", "2025-01-03"]),
    )

    assert changed is False
    assert order.offset is OrderOffset.CLOSE_TODAY


@pytest.mark.parametrize(
    "offset",
    [OrderOffset.OPEN, OrderOffset.CLOSE, OrderOffset.CLOSE_YESTERDAY],
)
def test_other_offsets_are_not_reclassified(offset):
    order = _order(offset)

    changed = reclassify_deferred_close_today(
        order,
        signal_timestamp="2025-01-02 15:00",
        market_timestamp="2025-01-03 09:00",
        trading_day_resolver=_TradingDays([]),
    )

    assert changed is False
    assert order.offset is offset
