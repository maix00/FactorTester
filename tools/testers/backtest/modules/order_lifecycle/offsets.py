"""Execution-day correction for deferred close offsets."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.order import (
    OrderLegRole,
    OrderOffset,
)


def reclassify_deferred_close_today(
    order: Any,
    *,
    signal_timestamp: Any,
    market_timestamp: Any,
    trading_day_resolver: Any,
) -> bool:
    """Age CLOSE_TODAY when its executable market bar crosses trading day."""
    if (
        order.offset is not OrderOffset.CLOSE_TODAY
        or trading_day_resolver is None
    ):
        return False
    instrument = str(order.instrument)
    signal_day = trading_day_resolver.resolve_trading_day(
        signal_timestamp, instrument=instrument,
    )
    execution_day = trading_day_resolver.resolve_trading_day(
        market_timestamp, instrument=instrument,
    )
    if signal_day == execution_day:
        return False
    order.set("original_offset", OrderOffset.CLOSE_TODAY.value)
    order.set("offset_reclassification_reason", "execution_trading_day_changed")
    order.set("offset_signal_trading_day", str(signal_day))
    order.set("offset_execution_trading_day", str(execution_day))
    order.offset = OrderOffset.CLOSE_YESTERDAY
    order.leg_role = OrderLegRole.CLOSE_YESTERDAY
    return True
