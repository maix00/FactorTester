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
from .volume_capacity import VolumeCapacityMode
from .margin import MarginModule
from .order_construct import OrderConstructModule
from .cash_rescale import LedgerCashConstraintModule
from .registry import (
    BacktestModuleRegistry,
    GroupTestModuleRegistry,
    LongShortModuleRegistry,
)

__all__ = [
    "ExecutableModule",
    "FeeModule",
    "SlippageModule",
    "VolumeCapacityMode",
    "MarginModule",
    "OrderConstructModule",
    "LedgerCashConstraintModule",
    "ModuleRegistry",
    "BacktestModuleRegistry",
    "GroupTestModuleRegistry",
    "LongShortModuleRegistry",
]
