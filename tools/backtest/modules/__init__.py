"""Executable backtest setting modules.

Each module: one file, one class, no mutual imports.
The runner discovers modules from the ModuleRegistry and dispatches purely
by phase — it never imports a module by its concrete class name.

Module discovery chain:
  tools.data.modules.ModuleRegistry   ← domain-neutral base (no backtest deps)
    BacktestModuleRegistry            ← adds ApplicationSettings manifest
      GroupTestModuleRegistry         ← group strategy parsing
      LongShortModuleRegistry         ← long-short strategy parsing
"""

from tools.data.modules.registry import ModuleRegistry

from .base import ExecutableModule
from .fee import FeeModule
from .slippage import SlippageModule
from .liquidity import LiquidityModule
from .margin import MarginModule
from .position_sizing import PositionSizingModule
from .cash_rescale import CashRescaleModule
from .registry import (
    BacktestModuleRegistry,
    GroupTestModuleRegistry,
    LongShortModuleRegistry,
)

__all__ = [
    "ExecutableModule",
    "FeeModule",
    "SlippageModule",
    "LiquidityModule",
    "MarginModule",
    "PositionSizingModule",
    "CashRescaleModule",
    "ModuleRegistry",
    "BacktestModuleRegistry",
    "GroupTestModuleRegistry",
    "LongShortModuleRegistry",
]
