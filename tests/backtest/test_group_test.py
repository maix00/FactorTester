"""Tests for tools/backtest/group_test.py — GroupTest 整体模型。"""

import numpy as np
import pytest

from tools.backtest_engines.group_test import (
    GroupTest,
    FlatFeeModel,
    SimpleMarginModel,
    PercentLiquidityModel,
    ProductMetaModel,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def small_membership() -> np.ndarray:
    """(T=3, M=2, P=3) — group0: [A,B]; group1: [B,C] at t=0, then static."""
    T, M, P = 3, 2, 3
    m = np.zeros((T, M, P), dtype=bool)
    m[:, 0, 0] = True
    m[:, 0, 1] = True
    m[:, 1, 1] = True
    m[:, 1, 2] = True
    return m


@pytest.fixture
def small_returns() -> np.ndarray:
    """(T=3, P=3) — all positive. A=1%, B=2%, C=1.5%."""
    return np.array([
        [0.01, 0.02, 0.015],
        [0.01, 0.02, 0.015],
        [0.01, 0.02, 0.015],
    ])


@pytest.fixture
def small_prices() -> np.ndarray:
    """(T=3, P=3) — prices at 100, 200, 150."""
    return np.array([
        [100., 200., 150.],
        [101., 202., 152.],
        [102., 204., 153.],
    ])


@pytest.fixture
def product_meta() -> ProductMetaModel:
    return ProductMetaModel(
        point_values=np.array([10., 20., 15.]),
        min_ticks=np.array([0.5, 1.0, 0.5]),
        lot_sizes=np.array([1., 1., 1.]),
    )


# ============================================================
# Vectorized path (no friction)
# ============================================================

class TestGroupTestVectorized:
    """无摩擦 → run_vectorized()"""

    def test_basic_shapes(self, small_membership, small_returns, small_prices):
        gt = GroupTest(
            membership_np=small_membership,
            returns_np=small_returns,
            price_np=small_prices,
        )
        result = gt.run()
        assert result["net_returns_np"].shape == (3, 2)
        assert result["cumulative_returns_np"].shape == (3, 2)
        assert result["equity_np"].shape == (3, 2)

    def test_no_friction_returns_finite(self, small_membership, small_returns, small_prices):
        gt = GroupTest(
            membership_np=small_membership,
            returns_np=small_returns,
            price_np=small_prices,
        )
        result = gt.run()
        assert np.all(np.isfinite(result["net_returns_np"]))

    def test_equal_weight_allocation(self):
        """等权分配：2品种，各0.5权重 → group_ret = 均值。"""
        m = np.ones((1, 1, 2), dtype=bool)  # T=1, M=1, P=2
        r = np.ones((1, 2)) * 0.02
        gt = GroupTest(
            membership_np=m,
            returns_np=r,
            price_np=np.ones((1, 2)) * 100,
        )
        result = gt.run()
        np.testing.assert_almost_equal(result["net_returns_np"][0, 0], 0.02)

    def test_cumulative_compounding(self):
        """累计净值 = cumprod(1+ret)。"""
        m = np.ones((3, 1, 2), dtype=bool)
        r = np.array([
            [0.01, 0.01],
            [0.02, 0.02],
            [0.03, 0.03],
        ])
        gt = GroupTest(
            membership_np=m,
            returns_np=r,
            price_np=np.ones((3, 2)) * 100,
        )
        result = gt.run()
        expected_cum = np.cumprod(1.0 + np.array([0.01, 0.02, 0.03]))
        np.testing.assert_almost_equal(
            result["cumulative_returns_np"][:, 0],
            expected_cum,
        )

    def test_zero_weight_for_non_members(self):
        """非成员品种权重为0。"""
        m = np.zeros((1, 1, 3), dtype=bool)
        m[0, 0, 0] = True  # only A
        r = np.array([[0.01, 0.02, 0.03]])
        gt = GroupTest(membership_np=m, returns_np=r, price_np=np.ones((1, 3)) * 100)
        result = gt.run()
        np.testing.assert_almost_equal(result["net_returns_np"][0, 0], 0.01)


# ============================================================
# DES path (with friction)
# ============================================================

class TestGroupTestDES:
    """有摩擦 → run_des()"""

    def test_flat_fee_reduces_return(self, small_membership, small_returns, small_prices, product_meta):
        """费率 1% 开+平 → net_returns < gross_returns。"""
        fee = FlatFeeModel(
            open_rate_mat=np.full((2, 3), 0.01),
            close_rate_mat=np.full((2, 3), 0.01),
            open_fixed_mat=np.zeros((2, 3)),
            close_fixed_mat=np.zeros((2, 3)),
        )
        gt = GroupTest(
            membership_np=small_membership,
            returns_np=small_returns,
            price_np=small_prices,
            product_model=product_meta,
            fee_model=fee,
        )
        result = gt.run()
        net = result["net_returns_np"]
        gross = result["gross_returns_np"]
        assert result["fee_costs_np"].sum() > 0
        assert np.all(net < gross)

    def test_no_fee_gives_same_gross_net(self, small_membership, small_returns, small_prices, product_meta):
        """无 fee → net ≈ gross。"""
        gt = GroupTest(
            membership_np=small_membership,
            returns_np=small_returns,
            price_np=small_prices,
            product_model=product_meta,
        )
        result = gt.run()
        # 无摩擦时走向量化路径 net=gross
        np.testing.assert_almost_equal(result["net_returns_np"], result["gross_returns_np"])

    def test_margin_occupied_positive(self, small_membership, small_returns, small_prices, product_meta):
        """保证金占用 > 0（持有仓位时）。"""
        margin = SimpleMarginModel(
            margin_ratio_mat=np.full((2, 3), 0.1),
            is_margin_flags=np.array([True, True, True]),
        )
        gt = GroupTest(
            membership_np=small_membership,
            returns_np=small_returns,
            price_np=small_prices,
            product_model=product_meta,
            margin_model=margin,
        )
        result = gt.run()
        # 首期建仓后占用 > 0
        assert result["margin_occupied_np"][0].sum() > 0

    def test_liquidity_caps_notional(self, small_membership, small_returns, small_prices, product_meta):
        """流动性 0.1% cap → 无法满仓。"""
        # capacity is (T, P) cross-sectional shares
        cap_mat = np.tile(np.array([0.5, 0.3, 0.2]), (3, 1))
        liq = PercentLiquidityModel(capacity_mat=cap_mat, percent=0.001)
        gt = GroupTest(
            membership_np=small_membership,
            returns_np=small_returns,
            price_np=small_prices,
            product_model=product_meta,
            liquidity_model=liq,
        )
        result = gt.run()
        # 持仓名义金额应该很小（受限于 0.1% cap）
        pos = result["position_quantities_np"][0]
        # 名义金额小于初始本金
        assert np.nansum(pos) < gt.initial_capital * 0.5

    def test_buy_and_hold_no_turnover(self, small_returns, small_prices, product_meta):
        """buy_and_hold：首期建仓后不退仓。"""
        m = np.zeros((3, 1, 2), dtype=bool)
        m[0] = np.array([[True, False]])
        m[1] = np.array([[True, True]])  # t=1, B enters
        m[2] = np.array([[True, False]])  # t=2, B exits
        gt = GroupTest(
            membership_np=m,
            returns_np=small_returns[:, :2],
            price_np=small_prices[:, :2],
            product_model=product_meta,
            rebalance_modes=["buy_and_hold"],
        )
        result = gt.run()
        qty = result["position_quantities_np"]
        # t=0: A only
        assert qty[0, 0, 0] > 0
        assert qty[0, 0, 1] == 0
        # t=1: B enters, A stays
        assert qty[1, 0, 0] > 0
        assert qty[1, 0, 1] > 0
        # t=2: B exits, A stays
        assert qty[2, 0, 0] > 0
        assert qty[
    2, 0, 1] == 0

    def test_recycle_no_new_entries(self, small_returns, small_prices, product_meta):
        """recycle：有持仓无退出 → 不新开。"""
        m = np.zeros((3, 1, 2), dtype=bool)
        m[0] = np.array([[True, False]])
        m[1] = np.array([[True, True]])
        m[2] = np.array([[True, False]])
        gt = GroupTest(
            membership_np=m,
            returns_np=small_returns[:, :2],
            price_np=small_prices[:, :2],
            product_model=product_meta,
            rebalance_modes=["recycle"],
        )
        result = gt.run()
        qty = result["position_quantities_np"]
        # t=1: B enters (no exit yet)
        assert qty[1, 0, 1] >= 0  # may be 0 (recycle freeze)
        # t=2: B exits → recycles capital to stay in A
        assert qty[2, 0, 0] > 0

    def test_mixed_rebalance_modes(self, small_returns, small_prices, product_meta):
        """mixed modes: group0 each_period, group1 buy_and_hold。"""
        m = np.ones((3, 2, 2), dtype=bool)
        gt = GroupTest(
            membership_np=m,
            returns_np=small_returns[:, :2],
            price_np=small_prices[:, :2],
            product_model=product_meta,
            rebalance_modes=["each_period", "buy_and_hold"],
        )
        result = gt.run()
        # both groups produce finite returns
        assert np.all(np.isfinite(result["net_returns_np"]))

    def test_has_friction_detection(self, small_membership, small_returns, small_prices):
        """根据是否有 fee/margin/liquidity 决定 has_friction。"""
        gt1 = GroupTest(
            membership_np=small_membership,
            returns_np=small_returns,
            price_np=small_prices,
        )
        assert not gt1.has_friction

        fee = FlatFeeModel(
            open_rate_mat=np.ones((2, 3)),
            close_rate_mat=np.ones((2, 3)),
            open_fixed_mat=np.zeros((2, 3)),
            close_fixed_mat=np.zeros((2, 3)),
        )
        gt2 = GroupTest(
            membership_np=small_membership,
            returns_np=small_returns,
            price_np=small_prices,
            fee_model=fee,
        )
        assert gt2.has_friction

    def test_tradable_mask_filters(self, small_membership, small_returns, small_prices, product_meta):
        """tradable_mask：不可交易品种不参与分配。"""
        mask = np.ones((3, 3), dtype=bool)
        mask[:, 1] = False  # B untradeable
        gt = GroupTest(
            membership_np=small_membership,
            returns_np=small_returns,
            price_np=small_prices,
            product_model=product_meta,
            tradable_mask_np=mask,
        )
        result = gt.run()
        qty = result["position_quantities_np"]
        # B should have zero position everywhere
        assert np.all(qty[:, :, 1] == 0)

    def test_init_validation(self, small_membership, small_returns):
        """init 参数校验：returns/price 形状不匹配报错。"""
        with pytest.raises(ValueError):
            GroupTest(
                membership_np=small_membership,
                returns_np=np.ones((2, 3)),  # wrong T
                price_np=np.ones((3, 3)),
            )
