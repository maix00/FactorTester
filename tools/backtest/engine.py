"""EventDrivenEngine — 事件驱动回测引擎主循环。

混合架构：
1. precompute(ctx): 向量化预计算（调用现有 FactorExpr.evaluate + 构建矩阵）
2. init_events(): 初始化事件队列（每期 push 10 类事件）
3. run(): 主循环 — while queue: dispatch(queue.pop())
"""

import itertools

import numpy as np
import pandas as pd

from tools.backtest.clock import SimulationClock
from tools.backtest.context import BacktestContext
from tools.backtest.event_queue import EventQueue
from tools.backtest.events import BacktestEvent, EventCategory
from tools.backtest.state import WorldState


class EventDrivenEngine:
    """事件驱动回测引擎。

    Usage:
        engine = EventDrivenEngine()
        ctx = engine.precompute(/* ... */)      # 向量化层
        final_state = engine.run(ctx)           # 事件驱动层
    """

    def __init__(self) -> None:
        self.queue = EventQueue()
        self.clock = SimulationClock()
        self._seq_counter = itertools.count()

        # 事件处理函数注册表: {EventCategory: callable}
        self._dispatchers: dict[EventCategory, list] = {}

    def register_dispatcher(self, category: EventCategory, handler) -> None:
        """注册事件处理函数。

        同一 category 可以有多个 handler，按注册顺序调用。
        """
        self._dispatchers.setdefault(category, []).append(handler)

    def precompute(
        self,
        returns_mat: np.ndarray,
        membership_mat: np.ndarray,
        price_mat: np.ndarray,
        fee_rate_mat: np.ndarray | None = None,
        margin_ratio_mat: np.ndarray | None = None,
        tradable_mask_mat: np.ndarray | None = None,
        point_values: np.ndarray | None = None,
        min_ticks: np.ndarray | None = None,
        lot_sizes: np.ndarray | None = None,
        factor_values: dict | None = None,
        config: dict | None = None,
    ) -> BacktestContext:
        """向量化预计算阶段。

        将现有 FactorExpr.evaluate() 的输出转为预计算矩阵，
        存入 BacktestContext 供事件驱动层只读访问。
        """
        T, P = returns_mat.shape
        M = membership_mat.shape[1] if membership_mat.ndim == 3 else 1

        ctx = BacktestContext(
            returns_mat=returns_mat,
            membership_mat=(
                membership_mat.reshape(T, M, P)
                if membership_mat.ndim == 2
                else membership_mat
            ),
            factor_values=factor_values or {},
            fee_rate_mat=(
                fee_rate_mat
                if fee_rate_mat is not None
                else np.zeros((T, P))
            ),
            margin_ratio_mat=(
                margin_ratio_mat
                if margin_ratio_mat is not None
                else np.zeros((T, P))
            ),
            price_mat=price_mat,
            tradable_mask_mat=(
                tradable_mask_mat
                if tradable_mask_mat is not None
                else np.ones((T, P), dtype=bool)
            ),
            point_values=(
                point_values
                if point_values is not None
                else np.ones(P)
            ),
            min_ticks=(
                min_ticks
                if min_ticks is not None
                else np.zeros(P)
            ),
            lot_sizes=(
                lot_sizes
                if lot_sizes is not None
                else np.ones(P)
            ),
            T=T,
            M=M,
            P=P,
            config=config or {},
        )
        return ctx

    def init_events(self, ctx: BacktestContext, timestamps: list[pd.Timestamp]) -> None:
        """初始化事件队列。

        为每个时间点 push 全部 10 类事件。
        """
        self.queue = EventQueue()
        self._seq_counter = itertools.count()

        for t_idx, ts in enumerate(timestamps):
            for cat in EventCategory:
                self.queue.push(BacktestEvent(
                    timestamp=ts,
                    category=cat,
                    priority=0,
                    seq=next(self._seq_counter),
                    payload={"t_idx": t_idx},
                ))

    def run(self, ctx: BacktestContext, state: WorldState) -> WorldState:
        """主循环 — 事件驱动 DES。

        while queue:
            event = queue.pop()
            clock.advance_to(event.timestamp)
            dispatch(event, state, ctx)
        """
        while self.queue:
            event = self.queue.pop()
            self.clock.advance_to(event.timestamp)
            self._dispatch(event, state, ctx)
            if ctx.stop:
                break

        return state

    def _dispatch(
        self,
        event: BacktestEvent,
        state: WorldState,
        ctx: BacktestContext,
    ) -> None:
        """按 EventCategory 分发事件。

        子类或用户可通过 register_dispatcher() 注册 handler。
        无 handler 的类别静默跳过。
        """
        handlers = self._dispatchers.get(event.category, [])
        for handler in handlers:
            handler(event, state, ctx)
