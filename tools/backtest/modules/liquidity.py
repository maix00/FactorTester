"""Liquidity module — caps deltas by volume participation rate."""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ..event_driven.stages import PhaseContext, PhaseHandler
from .base import ExecutableModule


class LiquidityModule(ExecutableModule):
    """Limits order deltas to a fraction of market volume.

    order_sizing — runs after lot_rounding, reads `deltas` and `volumes_row`,
                   writes capped `deltas`.
    """

    key: ClassVar[str] = "liquidity"
    label: ClassVar[str] = "流动性"
    order: ClassVar[int] = 150
    phases: ClassVar[tuple[PhaseHandler, ...]] = (
        PhaseHandler(
            "order_sizing", order=80,
            after=("order_sizing",),  # after lot rounding
            needs=("deltas", "volumes_row"),
            produces=("deltas",),
        ),
    )

    def on_order_sizing(self, ctx: PhaseContext) -> None:
        mode = str(self.setting("liquidity_mode", "infinite"))
        if mode == "infinite":
            return

        deltas = ctx.get("deltas")
        volumes = ctx.get("volumes_row")
        if deltas is None or volumes is None:
            return

        if mode != "volume_participation":
            raise ValueError(f"unsupported liquidity mode: {mode}")

        rate = float(self.setting("participation_rate", 0.0))
        if not 0 < rate <= 1:
            raise ValueError("participation_rate must be within (0, 1]")
        capacity = np.asarray(volumes, dtype=float) * rate
        ctx.set(
            "deltas",
            np.sign(np.asarray(deltas, dtype=float))
            * np.minimum(np.abs(np.asarray(deltas, dtype=float)), capacity),
        )
