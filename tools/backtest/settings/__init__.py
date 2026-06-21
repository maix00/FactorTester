"""Backend-owned backtest setting schemas and resolution."""

from .applications import backtest_setting_registry
from .contracts import SettingScope
from .resolver import resolve_strategy_settings

__all__ = [
    "SettingScope",
    "backtest_setting_registry",
    "resolve_strategy_settings",
]
