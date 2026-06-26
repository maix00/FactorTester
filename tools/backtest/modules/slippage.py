"""Slippage module — fill_price = base_price * (1 ± slippage_bps)."""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ..event_driven.stages import PhaseContext, PhaseHandler
from .base import ExecutableModule


class SlippageModule(ExecutableModule):
    """Adjusts execution prices by a configurable slippage model.

    order_execution — reads `deltas` and `valuation_values`, writes `fill_prices`.
    """

    key: ClassVar[str] = "slippage"
    label: ClassVar[str] = "滑点"
    order: ClassVar[int] = 110
    phases: ClassVar[tuple[PhaseHandler, ...]] = (
        PhaseHandler(
            "order_execution", order=80,
            needs=("deltas", "valuation_values"),
            produces=("fill_prices",),
        ),
    )

    def on_order_execution(self, ctx: PhaseContext) -> None:
        deltas = ctx.get("deltas")
        base_prices = ctx.get("valuation_values")
        if deltas is None or base_prices is None:
            return

        mode = str(self.setting("slippage_mode", "none"))
        if mode == "none":
            fill_prices = np.asarray(base_prices, dtype=float).copy()
        elif mode == "fixed_bps":
            bps = float(self.setting("slippage_bps", 0.0))
            fill_prices = np.asarray(base_prices, dtype=float) * (
                1.0 + np.sign(np.asarray(deltas, dtype=float)) * bps / 10_000.0
            )
        else:
            raise ValueError(f"unsupported slippage mode: {mode}")

        ctx.set("fill_prices", fill_prices)
