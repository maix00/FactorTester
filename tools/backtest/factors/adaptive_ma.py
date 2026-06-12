"""自适应均线 (Adaptive Moving Average) — EventDrivenFactor 示例。

AMA(t) = AMA(t-1) + sc * (price(t) - AMA(t-1))

其中 sc = (ER * (fast_sc - slow_sc) + slow_sc)²
ER = |price(t) - price(t-N)| / sum(|price(i) - price(i-1)| for i in t-N+1..t)

这是一个真正的路径依赖因子：每期结果依赖于上期自身的值。
无法用 FactorExpr 声明式表达（递归关系和跨期状态）。
"""

import numpy as np
import pandas as pd

from tools.backtest.events import EventCategory


class AdaptiveMA:
    """自适应均线 (Kaufman's Adaptive Moving Average) — 演示用。

    对应 EventDrivenFactor 协议。
    """

    def __init__(self, n: int = 10, fast_sc: float = 2.0, slow_sc: float = 30.0):
        self.n = n
        self.fast_sc = 2.0 / (fast_sc + 1)
        self.slow_sc = 2.0 / (slow_sc + 1)
        self._ama: np.ndarray | None = None
        self._price_history: list[np.ndarray] = []
        self._t: int = 0

    @staticmethod
    def event_category() -> EventCategory:
        return EventCategory.FACTOR

    def on_bar(
        self,
        timestamp: pd.Timestamp,
        prices: np.ndarray,
        ctx: "BacktestContext",  # noqa: F821
    ) -> np.ndarray:
        """逐期计算 AMA。"""
        self._price_history.append(prices.copy())
        if len(self._price_history) > self.n + 1:
            self._price_history.pop(0)

        P = len(prices)
        if self._ama is None:
            self._ama = prices.copy()
            self._t = 1
            return self._ama

        if self._t < self.n:
            # 不足 N 期，用简单平均
            price_array = np.array(self._price_history)
            self._ama = np.nanmean(price_array, axis=0)
            self._ama = np.nan_to_num(self._ama, nan=prices)
            self._t += 1
            return self._ama

        # 计算效率比率 ER
        price_array = np.array(self._price_history)  # (N+1, P)
        direction = np.abs(price_array[-1] - price_array[0])
        volatility = np.nansum(np.abs(np.diff(price_array, axis=0)), axis=0)
        er = np.divide(direction, volatility, out=np.zeros(P), where=volatility > 0)

        # 平滑常数
        sc = (er * (self.fast_sc - self.slow_sc) + self.slow_sc) ** 2

        # AMA 递推
        self._ama = self._ama + sc * (prices - self._ama)
        self._t += 1
        return self._ama

    def reset(self) -> None:
        self._ama = None
        self._price_history.clear()
        self._t = 0
