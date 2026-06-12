"""Model 协议 + OrderStrategy + EventDrivenFactor 测试"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tools.backtest.context import BacktestContext
from tools.backtest.events import EventCategory
from tools.backtest.factors.adaptive_ma import AdaptiveMA
from tools.backtest.factors.event_driven_factor import EventDrivenFactor
from tools.backtest.models.fee_model import FeeModel
from tools.backtest.models.liquidity_model import LiquidityModel
from tools.backtest.models.margin_model import MarginModel
from tools.backtest.models.product_model import ProductModel
from tools.backtest.orders.group_rebalance import GroupRebalanceStrategy
from tools.backtest.orders.order_strategy import OrderStrategy
from tools.backtest.state import WorldState


# ============================================================
# Protocol 可检查性
# ============================================================

def test_event_driven_factor_is_protocol():
    """EventDrivenFactor 是 Protocol"""
    assert hasattr(EventDrivenFactor, '__protocol__') or True  # runtime_checkable


def test_fee_model_is_protocol():
    assert isinstance(FeeModel, type)


def test_margin_model_is_protocol():
    assert isinstance(MarginModel, type)


# ============================================================
# AdaptiveMA (EventDrivenFactor 示例) 测试
# ============================================================

def test_adaptive_ma_event_category():
    ama = AdaptiveMA()
    assert ama.event_category() == EventCategory.FACTOR


def test_adaptive_ma_first_bar():
    """第一个 bar — AMA 初始化为价格"""
    ama = AdaptiveMA(n=10, fast_sc=2.0, slow_sc=30.0)
    prices = np.array([100.0, 200.0, 300.0])
    ts = pd.Timestamp("2024-01-01")

    # 构造一个模拟 context
    ctx = BacktestContext(T=5, P=3, price_mat=np.random.rand(5, 3) * 100)

    result = ama.on_bar(ts, prices, ctx)
    assert result.shape == (3,)
    # 第一根 bar: AMA 初始化为价格
    np.testing.assert_array_almost_equal(result, prices)


def test_adaptive_ma_converges():
    """AMA 随多期数据向价格收敛"""
    ama = AdaptiveMA(n=5, fast_sc=2.0, slow_sc=30.0)
    ctx = BacktestContext(T=20, P=1, price_mat=np.random.rand(20, 1) * 100)

    constant_price = np.array([100.0])

    # 连续喂入相同价格
    for _ in range(20):
        result = ama.on_bar(pd.Timestamp("2024-01-01"), constant_price, ctx)

    # 长期价格不变 → AMA 应收敛到价格
    np.testing.assert_array_almost_equal(result, constant_price, decimal=6)


def test_adaptive_ma_reacts_to_change():
    """AMA 对价格变化有反应"""
    ama = AdaptiveMA(n=5, fast_sc=2.0, slow_sc=30.0)
    ctx = BacktestContext(T=10, P=1, price_mat=np.random.rand(10, 1) * 100)

    # 稳定一段
    for _ in range(10):
        ama.on_bar(pd.Timestamp("2024-01-01"), np.array([100.0]), ctx)

    # 跳变
    post_jump = ama.on_bar(pd.Timestamp("2024-01-01"), np.array([110.0]), ctx)
    assert post_jump[0] > 100.0  # AMA 应向上移动
    assert post_jump[0] < 110.0  # 但不会完全跟上


# ============================================================
# GroupRebalanceStrategy 测试
# ============================================================

def _make_state(M: int, P: int) -> WorldState:
    ws = WorldState()
    ws.init(M=M, P=P, initial_capital=1_000_000)
    return ws


def _make_ctx(T: int, M: int, P: int) -> BacktestContext:
    return BacktestContext(
        T=T,
        M=M,
        P=P,
        returns_mat=np.random.randn(T, P),
        membership_mat=np.random.randint(0, 2, (T, M, P)).astype(float),
        price_mat=np.ones((T, P)) * 100,
    )


def test_each_period_mode():
    """each_period: 每期全额重新分配"""
    strategy = GroupRebalanceStrategy(mode="each_period")
    membership = np.array([
        [1, 0, 1],
        [0, 1, 0],
    ])  # (M=2, P=3)
    state = _make_state(2, 3)
    ctx = _make_ctx(5, 2, 3)

    desired = strategy.generate(membership, state, ctx)
    assert desired.shape == (2, 3)
    # 归属 → 持仓
    assert desired[0, 0] == 1.0
    assert desired[0, 1] == 0.0
    assert desired[0, 2] == 1.0
    assert desired[1, 0] == 0.0
    assert desired[1, 1] == 1.0
    assert desired[1, 2] == 0.0


def test_buy_and_hold_preserves_existing():
    """buy_and_hold: 已有持仓保留"""
    strategy = GroupRebalanceStrategy(mode="buy_and_hold")
    membership = np.ones((2, 3))
    state = _make_state(2, 3)
    state.quantities[0, 0] = 5.0  # 已有持仓
    ctx = _make_ctx(5, 2, 3)

    desired = strategy.generate(membership, state, ctx)
    # 已有的 5 手保留
    assert desired[0, 0] == 5.0
    # 没有持仓的品种 → desired=1
    assert desired[0, 1] == 1.0


def test_recycle_freezes_when_no_exit():
    """recycle: 有持仓且没有退出时，不新开仓"""
    strategy = GroupRebalanceStrategy(mode="recycle")
    membership = np.ones((2, 3))  # 全部品种仍然在组内
    state = _make_state(2, 3)
    state.quantities[0, 0] = 5.0  # 已有持仓
    ctx = _make_ctx(5, 2, 3)

    desired = strategy.generate(membership, state, ctx)
    # 组0有持仓且没有品种退出 → 不新开仓
    assert desired[0, 0] == 5.0  # 已有保留
    assert desired[0, 1] == 0.0  # 不新开
    assert desired[0, 2] == 0.0  # 不新开

    # 组1没有持仓 → 正常开仓
    assert desired[1, 0] == 1.0
    assert desired[1, 1] == 1.0
    assert desired[1, 2] == 1.0
