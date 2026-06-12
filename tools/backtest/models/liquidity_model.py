"""LiquidityModel 协议 — 流动性约束。

对标 Zipline SlippageModel（成交量份额滑点）。
"""

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class LiquidityModel(Protocol):
    """流动性模型协议。

    cap() 在每期的 LIQUIDITY 事件中被调用。
    """

    def cap(
        self,
        desired_quantities: np.ndarray,  # (M, P) 目标持仓
        quantities: np.ndarray,          # (M, P) 当前持仓
        equity: np.ndarray,              # (M,) 当前净值
        ctx: "BacktestContext",           # noqa: F821
    ) -> np.ndarray:
        """流动性约束裁剪。

        Args:
            desired_quantities: (M, P) 目标持仓量
            quantities: (M, P) 当前持仓量
            equity: (M,) 每组当前净值
            ctx: 回测上下文（含预计算流动性参数）

        Returns:
            (M, P) 流动性裁剪后的目标持仓量
        """
        ...
