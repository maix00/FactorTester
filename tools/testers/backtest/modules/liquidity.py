"""Liquidity module — caps deltas by volume participation rate."""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from tools.testers.backtest.engines.event_driven.stages import PhaseContext, PhaseHandler
from .base import ExecutableModule


class LiquidityModule(ExecutableModule):
    """Limits order deltas to a fraction of market volume.

    order_sizing — runs after lot_rounding, reads `deltas` and `volumes_row`,
                   writes capped `deltas`.
    """

    key: ClassVar[str] = "liquidity"
    label: ClassVar[str] = "流动性"
    order: ClassVar[int] = 150
    output_fields: ClassVar[tuple[str, ...]] = ()
    group_params: ClassVar[tuple[str, ...]] = ("liquidity_mode", "liquidity_percent")
    progress_phases: ClassVar[tuple[dict[str, Any], ...]] = (
        {"key": "liquidity", "label": "流动性容量"},
    )
    phases: ClassVar[tuple[PhaseHandler, ...]] = (
        PhaseHandler(
            "order_sizing", order=80,
            after=("order_sizing",),  # after lot rounding
            needs=("deltas", "volumes_row"),
            produces=("deltas",),
        ),
    )

    # ── Setting definitions ─────────────────────────────────────

    setting_definitions: ClassVar[tuple[dict[str, Any], ...]] = (
        {
            "key": "liquidity_mode",
            "label": "流动性规则",
            "tab": "liquidity",
            "control_template": "select",
            "default": "infinite",
            "scope_policy": "group_override",
            "options": (
                ("infinite", "无限流动性"),
                ("volume_participation", "成交量参与率"),
            ),
            "chip_template": "流动性: {value}",
        },
        {
            "key": "participation_rate",
            "label": "成交量参与率",
            "tab": "liquidity",
            "control_template": "number",
            "default": 0.1,
            "scope_policy": "group_override",
            "minimum": 0.0,
            "maximum": 1.0,
            "step": 0.01,
            "chip_template": "参与率: {value}",
            "visible_when": {"liquidity_mode": ("volume_participation",)},
        },
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

    # ── _FactorGroupTestGroup params ────────────────────────────

    @classmethod
    def build_group_params(cls, group_settings: dict[str, Any], raw_group: dict[str, Any]) -> dict[str, Any]:
        """Extract liquidity-related params for _FactorGroupTestGroup."""
        mode = group_settings.get("liquidity_mode")
        percent = (
            float(group_settings.get("participation_rate") or 0) * 100
            if mode == "volume_participation"
            else None
        )
        return {
            "liquidity_mode": mode,
            "liquidity_percent": percent,
        }
