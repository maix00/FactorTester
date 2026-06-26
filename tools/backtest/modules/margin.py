"""Margin module — caps target weights by available collateral."""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from ..event_driven.stages import PhaseContext, PhaseHandler
from .base import ExecutableModule


class MarginModule(ExecutableModule):
    """Scales target weights if required margin exceeds available collateral.

    risk — reads `target_weights` and `margin_ratios`, writes scaled `target_weights`.
    """

    key: ClassVar[str] = "margin"
    label: ClassVar[str] = "保证金"
    order: ClassVar[int] = 130
    phases: ClassVar[tuple[PhaseHandler, ...]] = (
        PhaseHandler(
            "risk", order=90,
            needs=("target_weights", "margin_ratios"),
            produces=("target_weights",),
        ),
    )

    def on_risk(self, ctx: PhaseContext) -> None:
        mode = str(self.setting("margin_mode", "none"))
        if mode == "none":
            return

        target = ctx.get("target_weights")
        long_margin_ratios = ctx.get("margin_ratios")
        if target is None or long_margin_ratios is None:
            return

        long_ratio = float(self.setting("margin_long", 0.0))
        short_ratio = float(self.setting("margin_short", 0.0))
        t = np.asarray(target, dtype=float)
        required = np.where(
            t >= 0,
            t * long_ratio * np.asarray(long_margin_ratios, dtype=float),
            np.abs(t) * short_ratio * np.asarray(long_margin_ratios, dtype=float),
        )
        total_req = float(np.sum(required))

        if total_req > 1.0 + 1e-12:
            ctx.set("target_weights", t / total_req)
