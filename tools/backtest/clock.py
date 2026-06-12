"""仿真时钟 — 时间推进和交易日历。

DES 模式：next-event time progression。
引擎不按固定步长推进，而是读取事件队列顶部的时间戳。
"""

import pandas as pd


class SimulationClock:
    """仿真时钟。

    DES 中时钟不需要主动 tick()，只需知道当前处理到哪个时刻。
    由引擎在 dispatch 时从事件中读取 timestamp 并更新。
    """

    def __init__(self) -> None:
        self._current: pd.Timestamp | None = None

    @property
    def current(self) -> pd.Timestamp | None:
        return self._current

    def advance_to(self, timestamp: pd.Timestamp) -> None:
        """推进到指定时刻。"""
        self._current = timestamp
