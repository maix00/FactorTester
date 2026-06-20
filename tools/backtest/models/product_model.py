"""ProductModel 协议 — 品种元数据（合约乘数、min_tick、lot_size）。
"""

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class ProductModel(Protocol):
    """品种模型协议。

    提供 min_tick 规整和 lot_size 取整。
    """

    def price_round(
        self,
        prices: np.ndarray,          # (P,) 或 (M, P)
        ctx: "BacktestContext",       # noqa: F821
    ) -> np.ndarray:
        """min_tick 规整。

        Args:
            prices: 原始价格
            ctx: 回测上下文（含 min_ticks）

        Returns:
            规整后的价格
        """
        ...

    def quantity_round(
        self,
        quantities: np.ndarray,      # (M, P) 或 (P,)
        ctx: "BacktestContext",       # noqa: F821
    ) -> np.ndarray:
        """lot_size 取整。

        Args:
            quantities: 原始手数
            ctx: 回测上下文（含 lot_sizes）

        Returns:
            取整后的手数（向下取整到 lot_size 的整数倍）
        """
        ...
