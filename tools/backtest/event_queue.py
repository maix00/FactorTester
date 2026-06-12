"""事件优先队列 — 基于 heapq 的未来事件列表 (FEL)

DES 标准模式：next-event time progression。
引擎主循环不断从队列顶部 pop 下一个事件处理。
"""

import heapq

from tools.backtest.events import BacktestEvent


class EventQueue:
    """基于 heapq 的优先队列。

    事件按 BacktestEvent 的 order=True 字段排序：
    (timestamp, category, priority, seq)
    """

    def __init__(self) -> None:
        self._heap: list[BacktestEvent] = []

    def push(self, event: BacktestEvent) -> None:
        heapq.heappush(self._heap, event)

    def pop(self) -> BacktestEvent:
        if not self._heap:
            raise IndexError("pop from empty EventQueue")
        return heapq.heappop(self._heap)

    def peek(self) -> BacktestEvent | None:
        return self._heap[0] if self._heap else None

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)
