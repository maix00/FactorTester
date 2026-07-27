"""Public strategy callbacks adapted into the native intent pipeline."""

from .dispatch import (
    _call_bar,
    _call_market_data,
    _call_order_event,
    _call_start,
    _call_stop,
)
from .flows import StrategyHookModule
from .intent import _apply_signal_intent

__all__ = [
    "StrategyHookModule",
    "_apply_signal_intent",
    "_call_bar",
    "_call_market_data",
    "_call_order_event",
    "_call_start",
    "_call_stop",
]
