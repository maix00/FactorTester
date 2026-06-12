"""FeeModel 协议 — 费率核算。

对标 Zipline CommissionModel + backtrader Commission。
"""

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class FeeModel(Protocol):
    """费率模型协议。

    compute() 在每期的 FEE 事件中被调用。
    从 ctx 读取预计算的费率矩阵，结合当前交易量计算费用。
    """

    def compute(
        self,
        buy_qty: np.ndarray,           # (M, P) 买入量
        sell_qty: np.ndarray,          # (M, P) 卖出量
        contract_value: np.ndarray,    # (M, P) 合约价值
        ctx: "BacktestContext",         # noqa: F821
    ) -> np.ndarray:
        """计算费用矩阵。

        Args:
            buy_qty: (M, P) 每组的买入手数
            sell_qty: (M, P) 每组的卖出手数
            contract_value: (M, P) 每手合约价值
            ctx: 回测上下文（含预计算费率矩阵）

        Returns:
            (M, P) 每笔交易的费用
        """
        ...
