"""BacktestContext, WorldState, SimulationClock 测试"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tools.backtest.clock import SimulationClock
from tools.backtest.context import BacktestContext
from tools.backtest.state import WorldState


# ============================================================
# BacktestContext 测试
# ============================================================

def test_backtest_context_default_init():
    """默认初始化 BacktestContext"""
    ctx = BacktestContext()
    assert ctx.T == 0
    assert ctx.M == 0
    assert ctx.P == 0
    assert ctx.returns_mat.shape == (0,)
    assert isinstance(ctx.config, dict)
    assert isinstance(ctx.errors, list)
    assert not ctx.stop


def test_backtest_context_with_matrices():
    """使用预计算矩阵初始化 BacktestContext"""
    returns = np.random.randn(10, 5)
    membership = np.random.randint(0, 2, (10, 3, 5)).astype(float)
    price = np.random.rand(10, 5) * 100

    ctx = BacktestContext(
        returns_mat=returns,
        membership_mat=membership,
        price_mat=price,
        T=10,
        M=3,
        P=5,
    )
    assert ctx.T == 10
    assert ctx.M == 3
    assert ctx.P == 5
    assert ctx.returns_mat.shape == (10, 5)
    assert ctx.membership_mat.shape == (10, 3, 5)
    assert ctx.price_mat.shape == (10, 5)


def test_backtest_context_optional_fields():
    """可选字段默认值"""
    ctx = BacktestContext(T=5, P=3)
    assert ctx.margin_ratio_mat.shape == (0,)
    assert ctx.tradable_mask_mat.shape == (0,)
    assert isinstance(ctx.factor_values, dict)
    assert ctx.factor_values == {}


def test_backtest_context_stop_flag():
    """stop 标志控制引擎停止"""
    ctx = BacktestContext()
    assert not ctx.stop
    ctx.stop = True
    assert ctx.stop


# ============================================================
# WorldState 测试
# ============================================================

def test_world_state_init():
    """初始化 WorldState"""
    ws = WorldState()
    ws.init(M=3, P=5, initial_capital=1_000_000)
    assert ws.initial_capital == 1_000_000
    assert ws.equity.shape == (3,)
    assert np.allclose(ws.equity, 1_000_000)
    assert ws.quantities.shape == (3, 5)
    assert np.all(ws.quantities == 0)
    assert ws.cash.shape == (3,)
    assert np.allclose(ws.cash, 1_000_000)


def test_world_state_default_capital():
    """使用默认初始资金"""
    ws = WorldState()
    ws.init(M=2, P=3)
    assert ws.initial_capital == 100_000_000.0
    assert np.allclose(ws.equity, 100_000_000.0)


def test_world_state_snapshot():
    """snapshot 保存当前状态到历史记录"""
    ws = WorldState()
    ws.init(M=2, P=3, initial_capital=1_000_000)
    ws.snapshot()
    assert len(ws.equity_history) == 1
    assert np.allclose(ws.equity_history[0], 1_000_000)
    assert len(ws.quantities_history) == 1


def test_world_state_snapshot_copies():
    """snapshot 是拷贝，修改 state 不影响历史"""
    ws = WorldState()
    ws.init(M=2, P=3, initial_capital=1_000_000)
    ws.snapshot()
    ws.equity[0] = 500_000  # 修改当前状态
    assert np.allclose(ws.equity_history[0][0], 1_000_000)  # 历史不变


def test_world_state_multiple_snapshots():
    """多次 snapshot"""
    ws = WorldState()
    ws.init(M=1, P=2, initial_capital=1_000_000)
    ws.snapshot()
    ws.equity[0] = 1_100_000
    ws.quantities[0, 0] = 10
    ws.snapshot()
    assert len(ws.equity_history) == 2
    assert np.allclose(ws.equity_history[0], 1_000_000)
    assert np.allclose(ws.equity_history[1], 1_100_000)


# ============================================================
# SimulationClock 测试
# ============================================================

def test_simulation_clock_initial():
    """初始状态 current 为 None"""
    clock = SimulationClock()
    assert clock.current is None


def test_simulation_clock_advance():
    """推进时钟"""
    clock = SimulationClock()
    ts = pd.Timestamp("2024-01-15 14:30:00")
    clock.advance_to(ts)
    assert clock.current == ts


def test_simulation_clock_advance_multiple():
    """多次推进"""
    clock = SimulationClock()
    t1 = pd.Timestamp("2024-01-01")
    t2 = pd.Timestamp("2024-01-02")
    t3 = pd.Timestamp("2024-01-03")
    clock.advance_to(t1)
    assert clock.current == t1
    clock.advance_to(t2)
    assert clock.current == t2
    clock.advance_to(t3)
    assert clock.current == t3
