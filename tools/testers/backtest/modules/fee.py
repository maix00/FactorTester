"""Transaction cost module — fee = |trade_value| * fee_rate."""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from tools.backtest_engines.event_driven.stages import PhaseContext, PhaseHandler
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
    output_fields: ClassVar[tuple[str, ...]] = ("fee_costs",)
    group_params: ClassVar[tuple[str, ...]] = ("fee_mode", "fee_rate", "fee_modifications")
    progress_phases: ClassVar[tuple[dict[str, Any], ...]] = (
        {"key": "framework_execution", "label": "事件回测工具"},
        {"key": "result_packaging", "label": "结果整理"},
    )
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

    # ── Setting definitions ─────────────────────────────────────

    setting_definitions: ClassVar[tuple[dict[str, Any], ...]] = (
        {
            "key": "fee_mode",
            "label": "费用规则",
            "tab": "cost",
            "control_template": "select",
            "default": "market",
            "scope_policy": "group_override",
            "options": (
                ("none", "无费用"),
                ("market", "市场历史费率"),
                ("custom", "自定义费率"),
            ),
            "chip_template": "费用: {value}",
        },
        {
            "key": "custom_fee_rate",
            "label": "自定义成交费率",
            "tab": "cost",
            "control_template": "number",
            "default": 0.0,
            "scope_policy": "group_override",
            "minimum": 0.0,
            "step": 0.000001,
            "chip_template": "费率: {value}",
            "visible_when": {"fee_mode": ("custom",)},
        },
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

    # ── Output collection ───────────────────────────────────────

    @classmethod
    def collect_outputs(
        cls,
        group_result: Any,
        owner: dict[str, Any],
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract fee_costs from GroupRunResult for frontend serialization.

        group_result.fee_costs_np has shape (T, M) — fee in minor units
        of base currency per timestamp per group.
        """
        group_index = int(owner.get("group_index", 0))
        fee_np = getattr(group_result, "fee_costs_np", None)
        if fee_np is not None:
            fee_np = np.asarray(fee_np, dtype=float)
            M = fee_np.shape[1] if fee_np.ndim >= 2 else 1
            if 0 <= group_index < M:
                col = fee_np[:, group_index]
                return {"fee_costs": [round(float(v), 8) for v in col]}
        return {"fee_costs": []}

    # ── _FactorGroupTestGroup params ────────────────────────────

    @classmethod
    def build_group_params(cls, group_settings: dict[str, Any], raw_group: dict[str, Any]) -> dict[str, Any]:
        """Extract fee-related params for _FactorGroupTestGroup."""
        return {
            "fee_mode": group_settings.get("fee_mode"),
            "fee_rate": group_settings.get("custom_fee_rate"),
            "fee_modifications": raw_group.get("feeModifications"),
        }

