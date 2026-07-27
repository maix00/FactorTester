"""Public strategy callbacks adapted into the native intent pipeline."""

from .dispatch import (
    _call_bar,
    _call_market_feed,
    _call_order_event,
    _call_order_status_event,
    _call_position_event,
    _call_start,
    _call_stop,
)
from .flows import StrategyRuntime
from .intent import _apply_signal_intent
from .commands import apply_strategy_command

__all__ = [
    "StrategyRuntime",
    "_apply_signal_intent",
    "apply_strategy_command",
    "_call_bar",
    "_call_market_feed",
    "_call_order_event",
    "_call_order_status_event",
    "_call_position_event",
    "_call_start",
    "_call_stop",
]
