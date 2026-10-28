"""Exchange trading-day handling for deferred close offsets.

Daily settlement is an independent accounting rule. A pending close-today
instruction ages to close-yesterday solely when its actual execution trading
day differs from its signal trading day. Call this once at the execution
decision using trading-day identities already attached to the signal and
Nautilus event; do not scan bars or maintain a separate rollover timeline.

    This only normalizes a deferred close instruction. It does not maintain
    today's/yesterday's inventory, split a partial fill, or cap match quantity;
    those must be handled in the native position/matching state before a fill
    is emitted.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

PositionOffset = Literal["open", "close", "close_today", "close_yesterday"]


def effective_execution_offset(
    requested: PositionOffset, *, signal_trading_day: date,
    execution_trading_day: date,
) -> PositionOffset:
    """Resolve a deferred close against pre-resolved exchange trading days.

    The function deliberately has no settlement-price, DMTM, or margin input.
    A natural calendar date change alone does not age a position when the
    exchange still assigns both events to the same trading day. The caller
    resolves the exchange day from its existing event/calendar data once when
    the order is considered for execution, so this adds constant work per
    execution and no per-bar or background processing.
    """
    if requested not in {"open", "close", "close_today", "close_yesterday"}:
        raise ValueError(f"unknown position offset {requested!r}")

    if (isinstance(signal_trading_day, datetime) or isinstance(execution_trading_day, datetime)
            or not isinstance(signal_trading_day, date)
            or not isinstance(execution_trading_day, date)):
        raise TypeError("trading-day keys must be resolved date values")
    if execution_trading_day < signal_trading_day:
        raise ValueError("execution trading day cannot precede signal trading day")
    if requested == "close_today" and signal_trading_day != execution_trading_day:
        return "close_yesterday"
    return requested
