from __future__ import annotations

import numpy as np

from tools.factors.tests.single_factor_test.group.core import (
    build_multi_session_target_amounts,
    build_target_amounts,
)


def test_each_period_reweights_members_equally():
    targets = build_target_amounts(
        np.array([[True, True, False]]),
        np.array([[0.8, 0.2, 0.0]]),
        np.array([1.0]),
        "each_period",
    )
    np.testing.assert_allclose(targets, [[0.5, 0.5, 0.0]])


def test_buy_and_hold_preserves_stayers_and_recycles_released_capital():
    targets = build_target_amounts(
        np.array([[True, False, True]]),
        np.array([[0.7, 0.3, 0.0]]),
        np.array([1.0]),
        "buy_and_hold",
    )
    np.testing.assert_allclose(targets, [[0.7, 0.0, 0.3]])


def test_target_amounts_preserve_group_wealth():
    targets = build_target_amounts(
        np.array([[True, False, True], [False, True, True]]),
        np.array([[0.7, 0.3, 0.0], [0.0, 0.4, 0.6]]),
        np.array([1.0, 1.0]),
        "recycle",
    )
    np.testing.assert_allclose(targets.sum(axis=1), [1.0, 1.0])


def test_multi_session_targets_vectorize_preserved_and_recycled_holdings():
    targets = build_multi_session_target_amounts(
        np.array([[False, True, True, False], [True, False, False, True]]),
        np.array([[0.4, 0.6, 0.0, 0.0], [0.0, 0.5, 0.5, 0.0]]),
        np.array([1.0, 1.0]),
        np.array([False, True, True, True]),
        np.array([0.0, 0.1, 0.0, 0.0]),
    )

    np.testing.assert_allclose(targets[0], [0.4, 0.6, 0.0, 0.0])
    # 第二组：品1退出(回收0.5-0.5*0.1=0.45)，品2退出(回收0.5) → recycled=0.95 → 全给品3
    np.testing.assert_allclose(targets[1], [0.0, 0.0, 0.0, 0.95])


def test_multi_session_initial_period_funds_tradable_members():
    targets = build_multi_session_target_amounts(
        np.array([[True, False, True]]),
        np.zeros((1, 3)),
        np.array([1.0]),
        np.array([True, False, True]),
        np.zeros(3),
    )

    np.testing.assert_allclose(targets, [[0.5, 0.0, 0.5]])


def test_recycle_deducts_close_fee_from_released_capital():
    """卖出释放的资金应扣除平仓费率后再分配给新品种。"""
    # 品0保持，品1退出(prev=0.4)，品2新进
    targets = build_target_amounts(
        np.array([[True, False, True]]),
        np.array([[0.6, 0.4, 0.0]]),
        np.array([1.0]),
        "recycle",
        close_fee_vec=np.array([0.0, 0.02, 0.0]),  # 品1 卖出费 2%
    )
    # released = 0.4 - 0.4 * 0.02 = 0.392
    # targets = staying(0.6) + entering(0.392) = [0.6, 0.0, 0.392]
    np.testing.assert_allclose(targets, [[0.6, 0.0, 0.392]])


def test_buy_and_hold_deducts_close_fee_from_released():
    """buy_and_hold 模式下卖出释放资金也应扣手续费。"""
    targets = build_target_amounts(
        np.array([[True, False, True]]),
        np.array([[0.5, 0.5, 0.0]]),
        np.array([1.0]),
        "buy_and_hold",
        close_fee_vec=np.array([0.0, 0.03, 0.0]),
    )
    # released = 0.5 - 0.5 * 0.03 = 0.485
    np.testing.assert_allclose(targets, [[0.5, 0.0, 0.485]])
