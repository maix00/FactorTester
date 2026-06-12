"""EventDrivenEngine 测试 — precompute + init_events + run 主循环"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tools.backtest.clock import SimulationClock
from tools.backtest.context import BacktestContext
from tools.backtest.engine import EventDrivenEngine
from tools.backtest.events import BacktestEvent, EventCategory
from tools.backtest.state import WorldState


# ============================================================
# EventDrivenEngine.precompute 测试
# ============================================================

def test_precompute_basic():
    """基本 precompute: T×M×P 矩阵"""
    T, M, P = 5, 3, 4
    returns = np.random.randn(T, P)
    membership = np.random.randint(0, 2, (T, M, P)).astype(float)
    price = np.random.rand(T, P) * 100

    engine = EventDrivenEngine()
    ctx = engine.precompute(
        returns_mat=returns,
        membership_mat=membership,
        price_mat=price,
    )

    assert ctx.T == T
    assert ctx.M == M
    assert ctx.P == P
    assert ctx.returns_mat.shape == (T, P)
    assert ctx.membership_mat.shape == (T, M, P)
    assert ctx.price_mat.shape == (T, P)


def test_precompute_default_matrices():
    """未提供的矩阵使用默认零值"""
    engine = EventDrivenEngine()
    ctx = engine.precompute(
        returns_mat=np.random.randn(5, 4),
        membership_mat=np.random.randint(0, 2, (5, 2, 4)).astype(float),
        price_mat=np.random.rand(5, 4) * 100,
    )
    # 默认值不应影响 T/P
    assert ctx.fee_rate_mat.shape == (5, 4)
    assert np.allclose(ctx.fee_rate_mat, 0)
    assert ctx.margin_ratio_mat.shape == (5, 4)
    assert np.allclose(ctx.margin_ratio_mat, 0)
    assert ctx.tradable_mask_mat.shape == (5, 4)
    assert np.all(ctx.tradable_mask_mat)  # 默认全部可交易


def test_precompute_2d_membership_reshaped():
    """2D membership → 自动 reshape 为 (T, 1, P)"""
    T, P = 5, 4
    returns = np.random.randn(T, P)
    membership_2d = np.random.randint(0, 2, (T, P)).astype(float)

    engine = EventDrivenEngine()
    ctx = engine.precompute(
        returns_mat=returns,
        membership_mat=membership_2d,
        price_mat=np.random.rand(T, P) * 100,
    )
    assert ctx.M == 1
    assert ctx.membership_mat.shape == (T, 1, P)


def test_precompute_config_passthrough():
    """config dict 透传到 ctx"""
    engine = EventDrivenEngine()
    ctx = engine.precompute(
        returns_mat=np.random.randn(5, 4),
        membership_mat=np.random.randint(0, 2, (5, 2, 4)).astype(float),
        price_mat=np.random.rand(5, 4) * 100,
        config={"initial_capital": 500_000, "mode": "each_period"},
    )
    assert ctx.config["initial_capital"] == 500_000
    assert ctx.config["mode"] == "each_period"


def test_precompute_factor_values():
    """factor_values 透传"""
    engine = EventDrivenEngine()
    factors = {"mom": np.random.randn(5, 4), "rsi": np.random.rand(5, 4)}
    ctx = engine.precompute(
        returns_mat=np.random.randn(5, 4),
        membership_mat=np.random.randint(0, 2, (5, 2, 4)).astype(float),
        price_mat=np.random.rand(5, 4) * 100,
        factor_values=factors,
    )
    assert "mom" in ctx.factor_values
    assert "rsi" in ctx.factor_values
    assert ctx.factor_values["mom"].shape == (5, 4)


# ============================================================
# EventDrivenEngine.init_events 测试
# ============================================================

def test_init_events_count():
    """init_events 创建正确数量的事件"""
    engine = EventDrivenEngine()
    ctx = engine.precompute(
        returns_mat=np.random.randn(5, 4),
        membership_mat=np.random.randint(0, 2, (5, 2, 4)).astype(float),
        price_mat=np.random.rand(5, 4) * 100,
    )
    timestamps = [
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
    ]
    engine.init_events(ctx, timestamps)
    # 10 类事件 × 3 个时间点 = 30
    assert len(engine.queue) == 30


def test_init_events_ordering():
    """init_events 事件按 (timestamp, category) 正确排序"""
    engine = EventDrivenEngine()
    ctx = engine.precompute(
        returns_mat=np.random.randn(5, 4),
        membership_mat=np.random.randint(0, 2, (5, 2, 4)).astype(float),
        price_mat=np.random.rand(5, 4) * 100,
    )
    timestamps = [
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-02"),
    ]
    engine.init_events(ctx, timestamps)

    # 第一个事件：最早时间 + 最小 category
    e1 = engine.queue.pop()
    assert e1.timestamp == timestamps[0]
    assert e1.category == EventCategory.MARKET_DATA

    # 第二个事件：同时间 + 第二小 category
    e2 = engine.queue.pop()
    assert e2.timestamp == timestamps[0]
    assert e2.category == EventCategory.FACTOR


# ============================================================
# EventDrivenEngine.run + dispatch 测试
# ============================================================

def test_run_empty_queue():
    """空队列 run 立即返回"""
    engine = EventDrivenEngine()
    ctx = engine.precompute(
        returns_mat=np.random.randn(5, 4),
        membership_mat=np.random.randint(0, 2, (5, 2, 4)).astype(float),
        price_mat=np.random.rand(5, 4) * 100,
    )
    state = WorldState()
    state.init(M=2, P=4)
    # 不 init_events — 空队列
    result = engine.run(ctx, state)
    assert result is state  # 返回同一个 state


def test_run_with_handlers():
    """注册 handler 后 run 正确调用各 handler"""
    T, M, P = 3, 2, 3
    returns = np.random.randn(T, P)
    membership = np.random.randint(0, 2, (T, M, P)).astype(float)
    price = np.random.rand(T, P) * 100

    engine = EventDrivenEngine()
    ctx = engine.precompute(
        returns_mat=returns,
        membership_mat=membership,
        price_mat=price,
    )

    # 注册 handler 收集被调用的事件
    called_categories: list[EventCategory] = []
    called_t_idx: list[int] = []

    def handler(event: BacktestEvent, state: WorldState, ctx: BacktestContext):
        called_categories.append(event.category)
        called_t_idx.append(event.payload["t_idx"])

    # 为所有类别注册同一个 handler
    for cat in EventCategory:
        engine.register_dispatcher(cat, handler)

    timestamps = [
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
    ]
    engine.init_events(ctx, timestamps)

    state = WorldState()
    state.init(M=M, P=P)

    engine.run(ctx, state)

    # 30 个事件 (3 期 × 10 类)
    assert len(called_categories) == 30
    # 验证 category 顺序：每期 MARKED_DATA 最先
    for t in range(3):
        base = t * 10
        assert called_categories[base] == EventCategory.MARKET_DATA
        assert called_categories[base + 9] == EventCategory.REPORT


def test_run_dispatch_stop():
    """ctx.stop=True 时提前退出"""
    T, M, P = 3, 2, 2
    returns = np.random.randn(T, P)
    membership = np.random.randint(0, 2, (T, M, P)).astype(float)

    engine = EventDrivenEngine()
    ctx = engine.precompute(
        returns_mat=returns,
        membership_mat=membership,
        price_mat=np.random.rand(T, P) * 100,
    )

    call_count = 0

    def stopping_handler(event, state, ctx):
        nonlocal call_count
        call_count += 1
        if call_count >= 5:
            ctx.stop = True

    engine.register_dispatcher(EventCategory.MARKET_DATA, stopping_handler)

    timestamps = [
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
    ]
    engine.init_events(ctx, timestamps)

    state = WorldState()
    state.init(M=M, P=P)
    engine.run(ctx, state)

    # 在第 5 个 MARKET_DATA 后停止（不是所有事件都处理完）
    assert call_count <= 10  # 最多处理到第10个 MARKET_DATA


def test_clock_advances_during_run():
    """run 过程中时钟随事件推进"""
    T, P = 2, 2
    returns = np.random.randn(T, P)
    membership = np.random.randint(0, 2, (T, 1, P)).astype(float)

    engine = EventDrivenEngine()
    ctx = engine.precompute(
        returns_mat=returns,
        membership_mat=membership,
        price_mat=np.random.rand(T, P) * 100,
    )

    recorded_timestamps: list[pd.Timestamp] = []

    def handler(event, state, ctx):
        recorded_timestamps.append(event.timestamp)

    engine.register_dispatcher(EventCategory.MARKET_DATA, handler)

    timestamps = [
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-03"),
    ]
    engine.init_events(ctx, timestamps)

    state = WorldState()
    state.init(M=1, P=P)
    engine.run(ctx, state)

    # 验证时钟推进到了最后时刻
    assert engine.clock.current == timestamps[-1]


# ============================================================
# 冒烟测试：3期×2品种×2组
# ============================================================

def test_smoke_3t_2p_2m():
    """3 期 × 2 品种 × 2 组冒烟测试"""
    T, M, P = 3, 2, 2

    # 构造简单数据
    returns = np.array([
        [0.01, -0.005],
        [0.02, 0.015],
        [-0.01, 0.01],
    ])
    price = np.ones((T, P)) * 100.0
    membership = np.ones((T, M, P))  # 全部属于全部组
    fee_rate = np.ones((T, P)) * 0.0005

    engine = EventDrivenEngine()
    ctx = engine.precompute(
        returns_mat=returns,
        membership_mat=membership,
        price_mat=price,
        fee_rate_mat=fee_rate,
    )

    # 简易 handler：模拟完整生命周期
    processed_events: list[tuple[pd.Timestamp, EventCategory]] = []

    def log_handler(event: BacktestEvent, state: WorldState, ctx: BacktestContext):
        processed_events.append((event.timestamp, event.category))

    for cat in EventCategory:
        engine.register_dispatcher(cat, log_handler)

    timestamps = [
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
    ]
    engine.init_events(ctx, timestamps)

    state = WorldState()
    state.init(M=M, P=P)

    engine.run(ctx, state)

    # 30 个事件
    assert len(processed_events) == 30
    # 验证每个时间点有 10 个事件
    t1_events = [e for e in processed_events if e[0] == timestamps[0]]
    assert len(t1_events) == 10
