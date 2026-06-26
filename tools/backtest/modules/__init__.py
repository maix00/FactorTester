"""Executable backtest setting modules.

Each module: one file, one class, no mutual imports.
The runner discovers modules from the ModuleRegistry and dispatches purely
by phase — it never imports a module by its concrete class name.

Module discovery chain:
  ModuleRegistry                  — base: collects ExecutableModules
    BacktestModuleRegistry        — adds ApplicationSettings manifest
      GroupTestModuleRegistry     — group strategy parsing
      LongShortModuleRegistry     — long-short strategy parsing
"""

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
    ModuleRegistry,
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
