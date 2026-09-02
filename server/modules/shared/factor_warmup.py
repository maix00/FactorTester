"""Resolve the factor warm-up policy without changing the formal run window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from tools.testers.backtest.modules.run_window import (
    auto_warmup_window,
    parse_warmup_window,
)


@dataclass(frozen=True, slots=True)
class FactorWarmupPolicy:
    mode: str
    window: pd.Timedelta

    @property
    def enabled(self) -> bool:
        return self.window > pd.Timedelta(0)

    def evaluation_window(self) -> pd.Timedelta | None:
        return self.window if self.enabled else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "window": str(self.window) if self.enabled else None,
            "leading_nan_allowed": not self.enabled,
        }


def resolve_factor_warmup_policy(
    settings: Mapping[str, Any] | None,
    factor: Any,
    *,
    default_mode: str = "none",
) -> FactorWarmupPolicy:
    values = settings or {}
    mode = str(values.get("warmup_mode") or default_mode).strip().lower()
    if mode == "none":
        return FactorWarmupPolicy(mode="none", window=pd.Timedelta(0))
    if mode == "fixed":
        return FactorWarmupPolicy(
            mode="fixed",
            window=parse_warmup_window(values.get("warmup_window")),
        )
    if mode == "auto":
        return FactorWarmupPolicy(
            mode="auto",
            window=auto_warmup_window(factor) or pd.Timedelta(0),
        )
    raise ValueError(f"未知因子预热模式: {mode}")


__all__ = ["FactorWarmupPolicy", "resolve_factor_warmup_policy"]
