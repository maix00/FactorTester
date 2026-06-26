"""Transaction cost module — fee = |trade_value| * fee_rate."""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ..event_driven.stages import PhaseContext, PhaseHandler
from .base import ExecutableModule


class FeeModule(ExecutableModule):
    """Applies transaction cost in two phases:

    target_generation    — emits `fee_rate` into context
    order_fill_accounting — applies fee to trade values, signals
                            `needs_rescale` if cash is insufficient
    """

    key: ClassVar[str] = "transaction_cost"
    label: ClassVar[str] = "交易费用"
    order: ClassVar[int] = 100
    phases: ClassVar[tuple[PhaseHandler, ...]] = (
        PhaseHandler(
            "target_generation", order=90,
            produces=("fee_rate",),
        ),
        PhaseHandler(
            "order_fill_accounting", order=90,
            needs=("deltas", "fill_prices", "cash"),
            produces=("deltas", "fill_prices", "cash"),
            records=("commission",),
        ),
    )

    def on_target_generation(self, ctx: PhaseContext) -> None:
        fee_rate = float(self.setting("fee_rate", 0.0))
        ctx.set("fee_rate", fee_rate)

    def on_order_fill_accounting(self, ctx: PhaseContext) -> None:
        deltas = ctx.get("deltas")
        fill_prices = ctx.get("fill_prices")
        cash = float(ctx.get("cash", 0.0))
        if deltas is None or fill_prices is None:
            return

        fee_rate = float(ctx.get("fee_rate", 0.0))
        trade_values = np.abs(deltas) * fill_prices
        sells = deltas < -1e-12
        buys = deltas > 1e-12
        available = float(cash + np.sum(trade_values[sells] * (1.0 - fee_rate)))
        buy_cost = float(np.sum(trade_values[buys] * (1.0 + fee_rate)))

        if buy_cost > max(available, 0.0) + 1e-9:
            ctx.signal("needs_rescale", {"available": available, "buy_cost": buy_cost})

        commission = float(np.sum(trade_values * fee_rate))
        next_cash = float(cash - np.sum(deltas * fill_prices + trade_values * fee_rate))
        ctx.set("cash", next_cash)
        ctx.set("commission", commission)
