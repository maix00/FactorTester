"""Margin module — caps target weights by available collateral."""

from __future__ import annotations

from typing import Any, ClassVar

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
    output_fields: ClassVar[tuple[str, ...]] = ()
    group_params: ClassVar[tuple[str, ...]] = ("margin_mode",)
    progress_phases: ClassVar[tuple[dict[str, Any], ...]] = (
        {"key": "framework_execution", "label": "事件回测工具"},
    )
    phases: ClassVar[tuple[PhaseHandler, ...]] = (
        PhaseHandler(
            "risk", order=90,
            needs=("target_weights", "margin_ratios"),
            produces=("target_weights",),
        ),
    )

    # ── Setting definitions ─────────────────────────────────────

    setting_definitions: ClassVar[tuple[dict[str, Any], ...]] = (
        {
            "key": "margin_mode",
            "label": "保证金约束",
            "tab": "margin",
            "control_template": "select",
            "default": "market",
            "scope_policy": "group_override",
            "options": (
                ("none", "关闭"),
                ("market", "市场保证金规则"),
            ),
            "chip_template": "保证金: {value}",
        },
        {
            "key": "collateral_fraction",
            "label": "最大保证金占权益",
            "tab": "margin",
            "control_template": "number",
            "default": 1.0,
            "scope_policy": "group_override",
            "minimum": 0.01,
            "maximum": 1.0,
            "step": 0.01,
            "chip_template": "保证金上限: {value}",
            "visible_when": {"margin_mode": ("market",)},
        },
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

    # ── _FactorGroupTestGroup params ────────────────────────────

    @classmethod
    def build_group_params(cls, group_settings: dict[str, Any], raw_group: dict[str, Any]) -> dict[str, Any]:
        """Extract margin-related params for _FactorGroupTestGroup."""
        return {
            "margin_mode": group_settings.get("margin_mode"),
        }
