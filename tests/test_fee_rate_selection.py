"""Ensure 平今/平昨 fee rate selection flows correctly through group test pipeline.

Tests cover:
  - compute_sell_fee fallback when close_today_fee_vec is None
  - compute_sell_fee when close_today_fee_vec is given (平今 override)
  - simulate_derived_group with different fee rates
  - 空组清仓 uses close_fee_vec (not always close_today)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tools.factors.tests.single_factor_test.group.core import (
    compute_sell_fee,
    compute_buy_costs,
    compute_group_gross_returns,
    compute_group_net_returns,
    simulate_derived_group,
    build_target_amounts,
)
from tools.factors.tests.single_factor_test.group.result import GroupRunResult


# ── helpers ────────────────────────────────────────────────────────────

def _make_group_result(
    membership_np: np.ndarray,
    period_returns_np: np.ndarray,
    open_fee_vec: np.ndarray | None = None,
    close_fee_vec: np.ndarray | None = None,
    close_today_fee_vec: np.ndarray | None = None,
    close_yesterday_fee_vec: np.ndarray | None = None,
) -> GroupRunResult:
    """Build a minimal GroupRunResult for simulate_derived_group."""
    T = membership_np.shape[0]
    P = period_returns_np.shape[1]
    return GroupRunResult(
        fee_costs_np=np.zeros((T, 1)),
        trade_notional_ratio_np=np.zeros((T, 1)),
        gross_returns_np=np.zeros((T, 1)),
        product_gross_contrib_np=np.zeros((T, 1, P)),
        product_fee_contrib_np=np.zeros((T, 1, P)),
        returns_np=period_returns_np,
        period_returns_np=period_returns_np,
        membership_np=membership_np,
        products_by_group={0: {}},
        valid_cols=[f"P{i}" for i in range(P)],
        open_fee_vec=open_fee_vec if open_fee_vec is not None else np.zeros(P),
        close_fee_vec=close_fee_vec if close_fee_vec is not None else np.zeros(P),
        close_today_fee_vec=close_today_fee_vec if close_today_fee_vec is not None else np.zeros(P),            close_yesterday_fee_vec=close_yesterday_fee_vec if close_yesterday_fee_vec is not None else close_fee_vec if close_fee_vec is not None else np.zeros(P),        index_list=[],
        multi_session_active=False,
        rebalance_mode="buy_and_hold",
        report_df=pd.DataFrame(),
    )


# ── compute_sell_fee: close_today_fee_vec fallback ──────────────────

def test_compute_sell_fee_falls_back_to_close_fee_when_today_is_none():
    """When close_today_fee_vec is None, use close_fee_vec (平昨)."""
    _, sell_fee = compute_sell_fee(
        prev_end_amounts=np.array([[1.0, 0.0]]),
        target_amounts=np.array([[0.0, 0.0]]),
        close_fee_vec=np.array([0.01, 0.02]),  # 平昨
        close_today_fee_vec=None,
    )
    # 卖出 P0: 1.0 * 0.01 = 0.01
    np.testing.assert_allclose(sell_fee, [0.01])


def test_compute_sell_fee_uses_close_today_when_provided():
    """When close_today_fee_vec is provided, it overrides close_fee_vec."""
    _, sell_fee = compute_sell_fee(
        prev_end_amounts=np.array([[1.0, 0.0]]),
        target_amounts=np.array([[0.0, 0.0]]),
        close_fee_vec=np.array([0.01, 0.02]),  # 平昨（应被覆盖）
        close_today_fee_vec=np.array([0.05, 0.06]),  # 平今
    )
    # 卖出 P0: 1.0 * 0.05 = 0.05 (NOT 0.01)
    np.testing.assert_allclose(sell_fee, [0.05])


def test_sell_fee_close_today_differs_from_close_yields_different_fees():
    """When 平今 != 平昨, sell_fee must differ."""
    args_common = dict(
        prev_end_amounts=np.array([[1.0, 0.0, 0.0]]),
        target_amounts=np.array([[0.0, 0.0, 0.0]]),
        close_fee_vec=np.array([0.003, 0.004, 0.0]),
    )
    _, sell_yesterday = compute_sell_fee(close_today_fee_vec=None, **args_common)
    _, sell_today = compute_sell_fee(
        close_today_fee_vec=np.array([0.007, 0.008, 0.0]), **args_common,
    )
    assert abs(float(sell_yesterday[0]) - float(sell_today[0])) > 1e-12, (
        f"平昨={sell_yesterday[0]} 应不同于 平今={sell_today[0]}"
    )


# ── compute_buy_costs ────────────────────────────────────────────────

def test_compute_buy_costs_charges_only_on_new_buys():
    """Buy fee only applies to bought portion, not staying holdings."""
    buy, buy_fee, _ = compute_buy_costs(
        target_amounts=np.array([[0.5, 0.5]]),
        prev_end_amounts=np.array([[0.4, 0.0]]),
        open_fee_vec=np.array([0.01, 0.01]),
        wealth_before_trade=np.array([1.0]),
    )
    # buy: P0=0.1 (0.5-0.4), P1=0.5 (0.5-0.0)
    np.testing.assert_allclose(buy, [[0.1, 0.5]])
    # buy_fee: 0.1*0.01 + 0.5*0.01 = 0.006
    np.testing.assert_allclose(buy_fee, [0.006])


# ── 两步 fee 模型完整性 ──────────────────────────────────────────────

def test_two_step_fee_model_sell_then_target_then_buy():
    """sell→available→target→buy→invested 完整流程验证。

    wealth=1.0, prev=[0.4, 0.4, 0.0], mask=[T,T,F]→[F,T,T]
    品0退出(0.4*close=0.004), 品1留存(0.4), 品2新进
    available = 1.0 - 0.004 = 0.996
    target: staying=0.4 + entering*recycled/1 = 0.4 + 0.396/1 = [0, 0.4, 0.396]
    buy = [0, 0, 0.396], buy_fee = 0.396*0.01 = 0.00396
    invested = [0, 0.4, 0.39204]
    """
    target = build_target_amounts(
        curr_mask_all=np.array([[False, True, True]]),
        prev_end_amounts=np.array([[0.4, 0.4, 0.0]]),
        wealth_before_trade=np.array([1.0]),
        rebalance_mode="buy_and_hold",
        close_fee_vec=np.array([0.01, 0.0, 0.0]),
    )
    # 留存品1，退出回收 0.4*0.99=0.396 全给品2
    np.testing.assert_allclose(target, [[0.0, 0.4, 0.396]])

    _, sell_fee = compute_sell_fee(
        np.array([[0.4, 0.4, 0.0]]), target,
        np.array([0.01, 0.0, 0.0]),
    )
    np.testing.assert_allclose(sell_fee, [0.004])  # 只对 exiting 0.4 收费

    buy, buy_fee, _ = compute_buy_costs(
        target, np.array([[0.4, 0.4, 0.0]]),
        open_fee_vec=np.array([0.01, 0.01, 0.01]),
        wealth_before_trade=np.array([1.0]),
    )
    np.testing.assert_allclose(buy, [[0.0, 0.0, 0.396]])
    np.testing.assert_allclose(buy_fee, [0.00396])

    # gross = invested * ret / wb = [0, 0.4, 0.39204] * [0.02, 0.02, 0.02] / 1
    buy_open_fees = buy * np.array([0.01, 0.01, 0.01])
    _, gross = compute_group_gross_returns(
        target, np.array([1.0]), np.array([0.02, 0.02, 0.02]),
        buy_open_fees=buy_open_fees,
    )
    expected_gross = 0.4 * 0.02 + 0.39204 * 0.02  # 0.008 + 0.0078408 = 0.0158408
    np.testing.assert_allclose(gross, [expected_gross])

    # net = gross - sell_fee_ratio - buy_fee_ratio
    # = 0.0158408 - 0.004 - 0.00396 = 0.0078808
    net = compute_group_net_returns(
        gross, np.array([0.004]), np.array([0.00396]),
        np.array([1.0]), target,
    )
    np.testing.assert_allclose(net, [0.0078808])


# ── simulate_derived_group: fee rate flows correctly ───────────────────

def test_derived_group_net_return_lower_with_higher_fee():
    """精选组：费率越高，净收益越低（平今不应高于平昨）。"""
    T = 3
    P = 2
    # 始终满仓 2 品种
    membership = np.ones((T, 1, P), dtype=bool)
    rets = np.full((T, P), 0.02, dtype=float)  # 每期 2% 收益

    # 低费率（平昨）
    sim_low = _make_derived_sim(
        membership, rets,
        open_fv=np.array([0.0005, 0.0005]),
        close_fv=np.array([0.0005, 0.0005]),
        close_today_fv=np.array([0.0005, 0.0005]),
        selected_idx=[0, 1], use_closetoday=False,
    )
    # 高费率（平今）
    sim_high = _make_derived_sim(
        membership, rets,
        open_fv=np.array([0.005, 0.005]),
        close_fv=np.array([0.005, 0.005]),
        close_today_fv=np.array([0.005, 0.005]),
        selected_idx=[0, 1], use_closetoday=False,
    )

    # 最终累计净收益：低费率 > 高费率
    assert sim_low['cumulative'][-1] > sim_high['cumulative'][-1], (
        f"低费率累计={sim_low['cumulative'][-1]:.6f} 应 > 高费率累计={sim_high['cumulative'][-1]:.6f}"
    )


def test_derived_group_empty_group_clearing_uses_close_fee():
    """精选组清仓时用 close_fee_vec，费率选对则清仓费用不同。"""
    T = 2
    P = 1
    # 第一期满仓，第二期清仓（mask=False）
    membership = np.array([[[True]], [[False]]], dtype=bool)
    rets = np.array([[0.0], [0.0]], dtype=float)

    # 低清仓费率
    sim_low = _make_derived_sim(
        membership, rets,
        open_fv=np.array([0.0]),
        close_fv=np.array([0.001]),
        close_today_fv=np.array([0.001]),
        selected_idx=[0], use_closetoday=False,
    )
    # 高清仓费率
    sim_high = _make_derived_sim(
        membership, rets,
        open_fv=np.array([0.0]),
        close_fv=np.array([0.010]),
        close_today_fv=np.array([0.010]),
        selected_idx=[0], use_closetoday=False,
    )

    # 清仓后累计 net: 低费率 > 高费率 (扣费少)
    assert sim_low['cumulative'][-1] > sim_high['cumulative'][-1], (
        f"低清仓费率累计={sim_low['cumulative'][-1]:.6f} > 高清仓费率累计={sim_high['cumulative'][-1]:.6f}"
    )


# ── simulate_derived_group: fee_costs 序列正确性 ───────────────────────

def test_derived_group_fee_costs_reflects_close_fee():
    """精选组 fee_costs 序列应反映 close_fee_vec。"""
    T = 2
    P = 2
    membership = np.ones((T, 1, P), dtype=bool)
    rets = np.zeros((T, P), dtype=float)

    sim = _make_derived_sim(
        membership, rets,
        open_fv=np.array([0.0, 0.0]),
        close_fv=np.array([0.005, 0.005]),
        close_today_fv=np.array([0.005, 0.005]),
        selected_idx=[0, 1], use_closetoday=False,
    )

    # 第一期从空仓建仓，有买入（无卖出），fee 应为 0
    assert sim['fee_costs'][0] == 0.0

    # 第二期仓位不变（buy&hold），fee 也应为 0
    assert sim['fee_costs'][1] == 0.0


# ── helpers for fee sensitivity ────────────────────────────────────────

def _make_result(membership, rets, close_fee_vec, open_fee_vec,
                  close_today_fee_vec=None):
    gr = _make_group_result(
        membership_np=membership,
        period_returns_np=rets,
        close_fee_vec=close_fee_vec,
        open_fee_vec=open_fee_vec,
        close_today_fee_vec=close_today_fee_vec,
    )
    return gr, open_fee_vec, close_fee_vec, close_today_fee_vec


def _make_derived_sim(membership, rets, open_fv, close_fv, close_today_fv,
                      selected_idx, use_closetoday, group_index=0):
    """Helper: build GroupRunResult + call simulate_derived_group with fee vectors."""
    gr = _make_group_result(
        membership_np=membership,
        period_returns_np=rets,
        open_fee_vec=open_fv if open_fv is not None else np.zeros(rets.shape[1]),
        close_fee_vec=close_fv if close_fv is not None else np.zeros(rets.shape[1]),
        close_today_fee_vec=close_today_fv if close_today_fv is not None else close_fv,
    )
    return simulate_derived_group(
        group_index=group_index,
        selected_idx=selected_idx,
        group_result=gr,
        open_fee_vec=open_fv if open_fv is not None else np.zeros(rets.shape[1]),
        close_fee_vec=close_fv if close_fv is not None else np.zeros(rets.shape[1]),
        close_today_fee_vec=close_today_fv,
        use_closetoday=use_closetoday,
    )


# ── net-return formula invariant ───────────────────────────────────────

def test_net_return_with_fee_never_exceeds_gross():
    """净收益不应超过总收益（sell_fee + buy_fee 非负）。"""
    gross = np.array([0.10, 0.0, -0.05])
    sell_fee_ratio = np.array([0.01, 0.03, 0.0])
    buy_fee_ratio = np.array([0.005, 0.0, 0.0])

    net = compute_group_net_returns(
        gross, sell_fee_ratio, buy_fee_ratio,
        np.ones_like(gross), np.ones((3, 2)),
    )

    assert (net <= gross + 1e-12).all(), f"net={net} 应 ≤ gross={gross}"


# ── 精选组平今 < 平昨 回归测试 ──────────────────────────────────────

def test_derived_group_close_today_lower_than_close_yesterday():
    """精选组：平今费率更高时，累计净收益必须 < 平昨费率。

    覆盖 _build_derived_group_payload 中的 use_closetoday 分支：
    当 use_closetoday=True 时，应使用 close_today_fee_vec（平今），
    从而精选组的累计净收益低于平昨。
    """
    T = 5
    P = 3
    # 品种进出组：模拟调仓触发交易费用
    membership = np.array([
        [[True, True, True]],    # t=0: 建仓 3 品种
        [[True, True, True]],    # t=1: 持有（无调仓）
        [[True, True, False]],   # t=2: P2 退出 → 卖出 P2，买入 P0/P1
        [[True, False, True]],   # t=3: P1 退出，P2 重新进入 → 调仓
        [[True, True, True]],    # t=4: P1 重新进入 → 调仓
    ], dtype=bool)
    rets = np.full((T, P), 0.01, dtype=float)  # 每期 1% 正收益

    open_fv = np.array([0.0001, 0.0001, 0.0001], dtype=float)   # 开仓费率相同
    close_yesterday = np.array([0.0001, 0.0003, 0.0002], dtype=float)  # 平昨
    close_today = np.array([0.0020, 0.0060, 0.0040], dtype=float)      # 平今（高 20 倍）

    # 平昨：use_closetoday=False，用 close_fee_vec（平昨）
    cum_yesterday = _make_derived_sim(
        membership, rets,
        open_fv=open_fv, close_fv=close_yesterday, close_today_fv=close_today,
        selected_idx=[0, 1, 2], use_closetoday=False,
    )['cumulative'][-1]

    # 平今：use_closetoday=True，用 close_today_fee_vec（平今）
    cum_today = _make_derived_sim(
        membership, rets,
        open_fv=open_fv, close_fv=close_yesterday, close_today_fv=close_today,
        selected_idx=[0, 1, 2], use_closetoday=True,
    )['cumulative'][-1]

    assert cum_yesterday > cum_today, (
        f"平昨累计={cum_yesterday:.8f} 应 > 平今累计={cum_today:.8f}，"
        f"差值={cum_yesterday - cum_today:.10f}"
    )


def test_derived_group_close_today_same_as_yesterday_when_rates_equal():
    """当平今=平昨时，use_closetoday True/False 结果应一致。"""
    T = 3
    P = 2
    membership = np.array([
        [[True, True]],
        [[True, False]],  # 调仓触发费用
        [[False, True]],  # 调仓触发费用
    ], dtype=bool)
    rets = np.full((T, P), 0.015, dtype=float)
    open_fv = np.array([0.0002, 0.0002], dtype=float)
    same_close = np.array([0.0005, 0.0005], dtype=float)  # 平今=平昨

    # 平昨
    cum_yesterday = _make_derived_sim(
        membership, rets,
        open_fv=open_fv, close_fv=same_close, close_today_fv=same_close,
        selected_idx=[0, 1], use_closetoday=False,
    )['cumulative'][-1]

    # 平今
    cum_today = _make_derived_sim(
        membership, rets,
        open_fv=open_fv, close_fv=same_close, close_today_fv=same_close,
        selected_idx=[0, 1], use_closetoday=True,
    )['cumulative'][-1]

    assert abs(cum_yesterday - cum_today) < 1e-12, (
        f"平今=平昨时 use_closetoday 不应改变结果，yesterday={cum_yesterday}, today={cum_today}"
    )


def test_simulate_derived_group_close_today_affects_only_close_fee():
    """use_closetoday 只影响卖出费用，持仓不变时净收益不受影响。"""
    T = 2
    P = 2
    # 品种切换：第0期全在，第1期换成另一组 → 触发卖出
    membership = np.ones((T, 1, P), dtype=bool)
    membership[1, 0, 0] = False  # 品0在第1期退出（触发卖出）
    rets = np.array([[0.05, 0.05], [0.05, 0.05]], dtype=float)

    open_fv = np.array([0.001, 0.001], dtype=float)
    close_fv = np.array([0.001, 0.001], dtype=float)     # 平昨
    close_today_fv = np.array([0.010, 0.010], dtype=float)  # 平今（更高）

    # 平昨
    sim_yesterday = _make_derived_sim(
        membership, rets,
        open_fv=open_fv, close_fv=close_fv, close_today_fv=close_today_fv,
        selected_idx=[0, 1], use_closetoday=False,
    )
    # 平今
    sim_today = _make_derived_sim(
        membership, rets,
        open_fv=open_fv, close_fv=close_fv, close_today_fv=close_today_fv,
        selected_idx=[0, 1], use_closetoday=True,
    )

    net_yesterday = sim_yesterday['cumulative'][-1]
    net_today = sim_today['cumulative'][-1]

    # 平今费率更高，净收益更低
    assert net_yesterday > net_today, (
        f"平今费率更高时净收益应更低: yesterday={net_yesterday:.8f}, today={net_today:.8f}"
    )
