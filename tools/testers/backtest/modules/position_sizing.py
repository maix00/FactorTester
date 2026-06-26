"""Position sizing module — rounds target weights to lot sizes, produces deltas."""

from __future__ import annotations

from typing import ClassVar

import numpy as np

from tools.testers.backtest.engines.event_driven.stages import PhaseContext, PhaseHandler
from .base import ExecutableModule


class PositionSizingModule(ExecutableModule):
    """Converts target weights into position deltas respecting lot sizes.

    order_sizing — reads `target_weights`, `valuation_values`, `cash`, `positions`;
                   writes `deltas` and `deltas_before`.
    """

    key: ClassVar[str] = "order_sizing"
    label: ClassVar[str] = "开单"
    order: ClassVar[int] = 140
    output_fields: ClassVar[tuple[str, ...]] = ()
    progress_phases: ClassVar[tuple[dict[str, Any], ...]] = (
        {"key": "framework_execution", "label": "事件回测工具"},
    )
    phases: ClassVar[tuple[PhaseHandler, ...]] = (
        PhaseHandler(
            "order_sizing", order=50,
            needs=("target_weights", "valuation_values", "cash", "positions"),
            produces=("deltas", "deltas_before"),
        ),
    )

    def on_order_sizing(self, ctx: PhaseContext) -> None:
        target = ctx.get("target_weights")
        prices = ctx.get("valuation_values")
        cash = ctx.get("cash")
        positions = ctx.get("positions")
        if target is None or prices is None or cash is None or positions is None:
            return

        lot_size = int(self.setting("lot_size", 1))
        round_mode = str(self.setting("round_mode", "round"))
        equal_lots = bool(self.setting("equal_lots", False))

        t = np.asarray(target, dtype=float)
        p = np.asarray(prices, dtype=float)
        c = float(cash)
        pos = np.asarray(positions, dtype=float)

        equity = float(c + np.sum(pos * p))
        desired = t * equity / np.where(p > 0, p, 1.0)
        deltas_before = desired - pos
        deltas = _round_to_lots(deltas_before, lot_size, round_mode, equal_lots)

        ctx.set("deltas_before", deltas_before)
        ctx.set("deltas", deltas)


def _round_to_lots(
    deltas: np.ndarray,
    lot_size: int,
    mode: str,
    equal_lots: bool,
) -> np.ndarray:
    """Round position deltas to lot granularity."""
    if mode == "none" or lot_size <= 1:
        return deltas.copy()

    result = np.asarray(deltas, dtype=float)
    if not equal_lots:
        result = np.trunc(result / lot_size) * lot_size
        return result

    if mode == "round":
        result = np.round(result / lot_size) * lot_size
    elif mode == "floor":
        result = np.floor(result / lot_size) * lot_size
    elif mode == "ceil":
        result = np.ceil(result / lot_size) * lot_size
    else:
        raise ValueError(f"unsupported round mode: {mode}")
    return result
