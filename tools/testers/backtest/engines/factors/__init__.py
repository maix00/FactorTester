"""Factor actors used by the event-driven backtest runtime."""

from .selection import FactorMode, select_factor_mode

__all__ = ["FactorMode", "select_factor_mode"]
