"""MarginModel 协议 — 保证金占用。

对标 Zipline Blotter 保证金逻辑。
"""

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class MarginModel(Protocol):
    """保证金模型协议。

    occupy() 在每期的 MARGIN 事件中被调用。
    """

    def occupy(
        self,
        position_notional: np.ndarray,  # (M, P) 持仓名义市值
        ctx: "BacktestContext",           # noqa: F821
    ) -> np.ndarray:
        """计算保证金占用。

        Args:
            position_notional: (M, P) 每组的每品种持仓名义市值
            ctx: 回测上下文（含预计算保证金率矩阵）

        Returns:
            (M,) 每组的总保证金占用
        """
        ...
