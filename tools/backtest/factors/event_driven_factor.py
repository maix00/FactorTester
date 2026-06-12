"""EventDrivenFactor 协议 — 路径依赖因子的 evaluate 通道。

与 FactorExpr 的区别：
- FactorExpr: 每期结果 = f(当期数据 + 固定窗口历史数据)，无跨期状态，可向量化
- EventDrivenFactor: 每期结果 = f(当期数据 + 上一期自身状态)，有路径依赖，必须逐期推进

示例：
- 自适应均线 AMA: ama(t) = ama(t-1) + sc * (price(t) - ama(t-1))
- 趋势状态机: 切换 trend/range/breakout 状态
- 组合感知因子: 需要知道当前持仓做加权
"""

from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from tools.backtest.events import EventCategory


@runtime_checkable
class EventDrivenFactor(Protocol):
    """事件驱动因子 — 需要维护跨期状态。

    每个 Bar 由引擎调用 on_bar()，因子可读写 self 内部状态。
    """

    @staticmethod
    def event_category() -> EventCategory:
        """返回 EventCategory.FACTOR。

        所有事件驱动因子共享同一类别，按 registration priority 排序。
        """
        ...

    def on_bar(
        self,
        timestamp: pd.Timestamp,
        prices: np.ndarray,       # (P,) 当期价格
        ctx: "BacktestContext",    # noqa: F821
    ) -> np.ndarray:
        """逐期 evaluate。

        Args:
            timestamp: 当前 Bar 时间戳
            prices: (P,) 当期价格数组
            ctx: 回测上下文（预计算矩阵 + 状态）

        Returns:
            (P,) 当期因子值
        """
        ...

    def reset(self) -> None:
        """重置内部状态（跨批次复用前调用）。"""
        ...
