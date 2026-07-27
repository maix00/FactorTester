"""Field references owned by the strategy-hook adapter."""

from typing import Any

from tools.testers.backtest.engines.native.fields import FieldRef


emitted_signal: FieldRef[Any] = FieldRef("hook_emitted_signal")
