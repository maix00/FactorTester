"""Slippage module — fill_price = base_price * (1 ± slippage_bps)."""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from tools.testers.backtest.engines.native.stages import PhaseContext, PhaseHandler
from .base import ExecutableModule


class SlippageModule(ExecutableModule):
    """Adjusts execution prices by a configurable slippage model.

    order_execution — reads `deltas` and `valuation_values`, writes `fill_prices`.
    """

    key: ClassVar[str] = "slippage"
    label: ClassVar[str] = "滑点"
    order: ClassVar[int] = 110
    output_fields: ClassVar[tuple[str, ...]] = ()
    progress_phases: ClassVar[tuple[dict[str, Any], ...]] = (
        {"key": "framework_execution", "label": "事件回测工具"},
    )
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

    # ── Setting definitions ─────────────────────────────────────

    setting_definitions: ClassVar[tuple[dict[str, Any], ...]] = (
        {
            "key": "slippage_mode",
            "label": "滑点模型",
            "tab": "cost",
            "control_template": "select",
            "default": "none",
            "scope_policy": "group_override",
            "options": (
                ("none", "零滑点"),
                ("fixed_bps", "固定基点"),
            ),
            "chip_template": "滑点: {value}",
        },
        {
            "key": "slippage_bps",
            "label": "固定滑点（基点）",
            "tab": "cost",
            "control_template": "number",
            "default": 0.0,
            "scope_policy": "group_override",
            "minimum": 0.0,
            "step": 0.1,
            "chip_template": "滑点bp: {value}",
            "visible_when": {"slippage_mode": ("fixed_bps",)},
        },
    )
