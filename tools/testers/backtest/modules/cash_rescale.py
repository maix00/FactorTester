"""Cash rescale module — scales buy deltas when cash is insufficient."""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from tools.testers.backtest.engines.native.stages import PhaseContext, PhaseHandler
from .base import ExecutableModule


class CashRescaleModule(ExecutableModule):
    """Responds to `needs_rescale` signal by scaling buy deltas.

    order_fill_accounting — after fee module, checks `needs_rescale` signal
                            and scales buy deltas proportionally down.
    """

    key: ClassVar[str] = "cash_rescale"
    label: ClassVar[str] = "现金调整"
    order: ClassVar[int] = 160
    output_fields: ClassVar[tuple[str, ...]] = ()
    progress_phases: ClassVar[tuple[dict[str, Any], ...]] = (
        {"key": "framework_execution", "label": "事件回测工具"},
    )
    phases: ClassVar[tuple[PhaseHandler, ...]] = (
        PhaseHandler(
            "order_fill_accounting", order=100,
            after=("transaction_cost",),
            needs=("deltas", "fill_prices"),
            produces=("deltas",),
        ),
    )

    def on_order_fill_accounting(self, ctx: PhaseContext) -> None:
        if not ctx.has_signal("needs_rescale"):
            return

        deltas = ctx.get("deltas")
        prices = ctx.get("fill_prices")
        if deltas is None or prices is None:
            return

        payload = ctx.consume_signal("needs_rescale")
        available = float(payload.get("available", 0.0))
        buy_cost = float(payload.get("buy_cost", 0.0))
        if buy_cost <= 0 or available <= 0:
            return

        scale = float(max(0.0, available) / buy_cost)
        d = np.asarray(deltas, dtype=float)
        d[d > 1e-12] *= scale
        ctx.set("deltas", d)
