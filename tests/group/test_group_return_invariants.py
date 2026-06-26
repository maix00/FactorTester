from __future__ import annotations

import numpy as np

from tools.factors.tester_calc.single_factor_test.group.core import (
    compute_group_gross_returns,
    compute_group_net_returns,
    compute_sell_fee,
    compute_buy_costs,
)


def test_net_return_matches_gross_and_fee_formula():
    """net = gross - sell_fee_ratio - buy_fee_ratio."""
    gross = np.array([0.10, -0.05])
    sell_fee_ratio = np.array([0.01, 0.02])
    buy_fee_ratio = np.array([0.005, 0.0])

    net = compute_group_net_returns(
        gross, sell_fee_ratio, buy_fee_ratio,
        np.ones_like(gross), np.ones((2, 2)),
    )

    np.testing.assert_allclose(net, [0.085, -0.07])


def test_product_gross_contributions_sum_to_group_gross_return():
    target_amounts = np.array([[0.25, 0.75]])
    wealth_before_trade = np.array([1.0])
    product_returns = np.array([0.20, -0.10])

    product_contrib, gross = compute_group_gross_returns(
        target_amounts,
        wealth_before_trade,
        product_returns,
    )

    np.testing.assert_allclose(product_contrib, [[0.05, -0.075]])
    np.testing.assert_allclose(gross, [-0.025])


def test_cumulative_returns_are_period_return_compounds():
    period_returns = np.array([[0.10], [-0.05], [0.02]])

    cumulative = np.cumprod(1.0 + period_returns, axis=0)

    np.testing.assert_allclose(cumulative[:, 0], [1.10, 1.045, 1.0659])


def test_buy_and_hold_staying_positions_pay_no_fee():
    """buy&hold 持仓不变时买卖费用均为 0。"""
    buy, buy_fee, tnr = compute_buy_costs(
        target_amounts=np.array([[0.7, 0.3]]),
        prev_end_amounts=np.array([[0.7, 0.3]]),
        open_fee_vec=np.array([0.001, 0.002]),
        wealth_before_trade=np.array([1.0]),
    )
    np.testing.assert_allclose(buy, [[0.0, 0.0]])
    np.testing.assert_allclose(buy_fee, [0.0])
    np.testing.assert_allclose(tnr, [0.0])

    # sell_fee 只对 exiting 收费，staying 的不收费
    prev = np.array([[0.7, 0.3]])
    target = np.array([[0.7, 0.3]])
    _, sell_fee = compute_sell_fee(
        prev_end_amounts=prev,
        target_amounts=target,
        close_fee_vec=np.array([0.003, 0.004]),
    )
    np.testing.assert_allclose(sell_fee, [0.0])  # 没有 exiting 部分


def test_sell_and_buy_fees_use_per_product_rates():
    """卖出用平昨/平今费率，买入用开仓费率，各品种独立。"""
    # 卖出 P0，买入 P1 — prev=[1,0] → target=[0,1]，exiting=1.0
    prev = np.array([[1.0, 0.0]])
    target = np.array([[0.0, 1.0]])
    _, sell_fee = compute_sell_fee(
        prev_end_amounts=prev,
        target_amounts=target,
        close_fee_vec=np.array([0.003, 0.004]),
    )
    np.testing.assert_allclose(sell_fee, [0.003])  # exiting 1.0 * 0.003

    buy, buy_fee, tnr = compute_buy_costs(
        target_amounts=target,
        prev_end_amounts=prev,
        open_fee_vec=np.array([0.001, 0.002]),
        wealth_before_trade=np.array([1.0]),
    )
    np.testing.assert_allclose(buy, [[0.0, 1.0]])
    np.testing.assert_allclose(buy_fee, [0.002])
    np.testing.assert_allclose(tnr, [2.0])  # (1.0 sell + 1.0 buy) / 1.0


def test_sell_fee_can_use_user_selected_close_today_rates():
    """用平今费率覆盖平昨费率计算卖出费用。"""
    _, sell_fee = compute_sell_fee(
        prev_end_amounts=np.array([[1.0, 0.0]]),
        target_amounts=np.array([[0.0, 0.0]]),
        close_fee_vec=np.array([0.003, 0.004]),
        close_today_fee_vec=np.array([0.007, 0.008]),
    )
    # 卖出 P0: 1.0 * 0.007 = 0.007（平今，不是 0.003）
    np.testing.assert_allclose(sell_fee, [0.007])
