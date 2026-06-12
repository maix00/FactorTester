"""OrderStrategy 协议 — 订单执行策略。

每个 Bar 根据 membership + 当前 WorldState 生成 trade intents（买卖量）。
"""

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class OrderStrategy(Protocol):
    """订单执行策略协议。

    在每期的 ORDER 事件中被调用。
    输入：membership、当前状态、上下文
    输出：desired_quantities (M, P)
    """

    def generate(
        self,
        membership: np.ndarray,      # (M, P) 当期分组归属
        state: "WorldState",          # noqa: F821
        ctx: "BacktestContext",       # noqa: F821
    ) -> np.ndarray:
        """生成目标持仓量矩阵。

        Returns:
            (M, P) desired_quantities — 正数=买入，负数=卖出（相对于当前持仓）
        """
        ...
