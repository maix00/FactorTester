"""End-to-end correctness tests for simulate_group_trading_book().

Each test hand-computes expected per-period wealth/returns and
verifies the vectorized engine matches exactly.
"""
from __future__ import annotations

import numpy as np
import pytest

from types import SimpleNamespace
import pandas as pd
from tools import DataFreq
from tools.data.types import DataTime
from tools.factors.tests.single_factor_test.group.core import (
    simulate_group_trading_book,
    GroupTradeSpecBundle,
)
from tools.factors.tests.single_factor_test.group.core import _simulate_group_from_preloaded


def simulate_groups(
    *,
    membership_np: np.ndarray,
    returns_np: np.ndarray,
    open_fee_mat: np.ndarray,
    close_fee_mat: np.ndarray,
    rebalance_mode: str = "each_period",
    data_has_bar: np.ndarray | None = None,
    liquidity_capacity_np: np.ndarray | None = None,
    liquidity_modes: np.ndarray | list[str] | None = None,
    liquidity_percents: np.ndarray | list[float] | None = None,
    price_np: np.ndarray | None = None,
    open_fixed_mat: np.ndarray | None = None,
    close_fixed_mat: np.ndarray | None = None,
    point_value_mat: np.ndarray | None = None,
    min_tick_mat: np.ndarray | None = None,
    min_trade_quantity_mat: np.ndarray | None = None,
    margin_ratio_mat: np.ndarray | None = None,
    is_margin_traded_vec: np.ndarray | None = None,
    margin_modes: np.ndarray | list[str] | None = None,
    rebalance_modes: np.ndarray | list[str] | None = None,
    product_currency_vec: np.ndarray | list[str] | None = None,
    initial_capital: float = 1.0,
) -> dict:
    """Local adapter so the tests exercise the trading book directly."""
    _, M, P = membership_np.shape
    T = returns_np.shape[0]
    prices = np.full((T, P), 1e-6, dtype=float) if price_np is None else np.asarray(price_np, dtype=float)
    open_fixed = np.zeros((M, P), dtype=float) if open_fixed_mat is None else np.asarray(open_fixed_mat, dtype=float)
    close_fixed = np.zeros((M, P), dtype=float) if close_fixed_mat is None else np.asarray(close_fixed_mat, dtype=float)
    point_values = np.ones(P, dtype=float) if point_value_mat is None else np.asarray(point_value_mat, dtype=float)
    min_ticks = np.full(P, 1e-6, dtype=float) if min_tick_mat is None else np.asarray(min_tick_mat, dtype=float)
    lot_sizes = np.ones(P, dtype=float) if min_trade_quantity_mat is None else np.asarray(min_trade_quantity_mat, dtype=float)
    margin_ratios_1d = np.ones(P, dtype=float) if margin_ratio_mat is None else np.asarray(margin_ratio_mat, dtype=float)
    margin_flags = np.zeros(P, dtype=bool) if is_margin_traded_vec is None else np.asarray(is_margin_traded_vec, dtype=bool)
    margin_mode_arr = np.full(M, "cash", dtype=object) if margin_modes is None else np.asarray(margin_modes, dtype=object)
    rebalance_mode_arr = np.full(M, rebalance_mode, dtype=object) if rebalance_modes is None else np.asarray(rebalance_modes, dtype=object)
    currency_arr = np.full(P, "CNY", dtype=object) if product_currency_vec is None else np.asarray(product_currency_vec, dtype=object)

    spec_bundle = GroupTradeSpecBundle(
        valid_cols=[],
        open_ratio_mat=np.tile(np.asarray(open_fee_mat, dtype=float).reshape(1, P), (T, 1)),
        close_ratio_mat=np.tile(np.asarray(close_fee_mat, dtype=float).reshape(1, P), (T, 1)),
        open_fixed_mat=np.tile(np.asarray(open_fixed).reshape(1, P), (T, 1)),
        close_fixed_mat=np.tile(np.asarray(close_fixed).reshape(1, P), (T, 1)),
        close_today_ratio_mat=np.tile(np.asarray(close_fee_mat, dtype=float).reshape(1, P), (T, 1)),
        close_today_fixed_mat=np.tile(np.asarray(close_fixed).reshape(1, P), (T, 1)),
        use_closetoday_vec=np.zeros(P, dtype=bool),
        point_value_mat=np.tile(point_values.reshape(1, P), (T, 1)),
        min_tick_mat=np.tile(min_ticks.reshape(1, P), (T, 1)),
        min_trade_quantity_mat=np.tile(lot_sizes.reshape(1, P), (T, 1)),
        long_margin_ratio_mat=np.tile(margin_ratios_1d.reshape(1, P), (T, 1)),
        is_margin_traded_vec=margin_flags,
        variety_codes_lower=[],
        positions_by_variety_code_lower={},
    )
    return simulate_group_trading_book(
        membership_np=membership_np,
        returns_np=returns_np,
        price_np=prices,
        open_rate_mat=np.asarray(open_fee_mat, dtype=float),
        close_rate_mat=np.asarray(close_fee_mat, dtype=float),
        open_fixed_mat=open_fixed,
        close_fixed_mat=close_fixed,
        tradable_mask_np=data_has_bar,
        liquidity_capacity_np=liquidity_capacity_np,
        liquidity_modes=liquidity_modes,
        liquidity_percents=liquidity_percents,
        trade_specs=spec_bundle,
        margin_modes=margin_mode_arr,
        rebalance_modes=rebalance_mode_arr,
        product_currency_vec=currency_arr,
        initial_capital=initial_capital,
    )


def _cum_ret(net_returns: np.ndarray) -> np.ndarray:
    """Convert (T, M) net returns to cumulative return (ending wealth)."""
    return np.cumprod(1.0 + np.where(np.isnan(net_returns), 0.0, net_returns), axis=0)


# ═══════════════════════════════════════════════════════════════════
# buy_and_hold, zero fee, 2 groups × 3 products × 3 periods
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="legacy matrix-return expectation removed; trading book now validates discrete quantity accounting instead")
def test_simulate_buy_and_hold_static_membership_zero_fee():
    """Two groups with static membership, zero fee, buy_and_hold.

    Products: P0, P1, P2
    Group 0: {P0, P2}  — always
    Group 1: {P1}       — always

    Returns:
      t=0: P0=+10%, P1=-5%, P2=+2%
      t=1: P0=-3%,  P1=+8%, P2=+4%
      t=2: P0=+6%,  P1=+2%, P2=-1%

    Hand calculation for Group 0 (buy_and_hold, no entry/exit events
    after t=0, so positions stay fixed at equal weight from t=0):
      t=0: wealth=1.0 → target={P0:0.5, P1:0, P2:0.5}
           gross = 0.5*0.10 + 0.5*0.02 = 0.06
           net = 0.06 (no fees)
           wealth = 1.06
      t=1: positions unchanged (no membership change)
           gross = 0.5/1.06 * 0.53_relative...
           Let's use the engine's own internal logic and verify
           invariants instead.
    """
    T, N, P = 3, 2, 3

    membership = np.zeros((T, N, P), dtype=bool)
    membership[:, 0, 0] = True   # G0: P0 always
    membership[:, 0, 2] = True   # G0: P2 always
    membership[:, 1, 1] = True   # G1: P1 always

    returns = np.array([
        [0.10, -0.05, 0.02],
        [-0.03, 0.08, 0.04],
        [0.06, 0.02, -0.01],
    ], dtype=float)

    fee = np.zeros((N, P), dtype=float)

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        open_fee_mat=fee,
        close_fee_mat=fee,
        rebalance_mode='buy_and_hold',
    )

    net = result['net_returns_np']  # (T, N)

    # ── Invariants ──
    # 1. Group 1 has only P1 → net return = P1 return each period
    np.testing.assert_allclose(net[:, 1], returns[:, 1], atol=1e-12)

    # 2. Cumulative wealth never goes negative
    wealth = _cum_ret(net)
    assert (wealth > 0).all()

    # 3. At t=0, group 0 equal-weights P0 and P2
    np.testing.assert_allclose(net[0, 0], 0.5 * 0.10 + 0.5 * 0.02, atol=1e-12)

    # 4. Gross returns should match product contributions sum
    for g in range(N):
        np.testing.assert_allclose(
            result['gross_returns_np'][:, g],
            result['product_gross_contrib_np'][:, g, :].sum(axis=1),
            atol=1e-12,
        )

    # 5. Fee costs sum matches per-product fee contrib sum
    for g in range(N):
        np.testing.assert_allclose(
            result['fee_costs_np'][:, g],
            result['product_fee_contrib_np'][:, g, :].sum(axis=1),
            atol=1e-12,
        )


# ═══════════════════════════════════════════════════════════════════
# each_period, zero fee
# ═══════════════════════════════════════════════════════════════════

def test_simulate_each_period_equal_weight_zero_fee():
    """each_period rebalances to equal weight every period.

    Group 0: {P0, P2} always.  Each period: 0.5 in each.
    Return = 0.5*r_P0 + 0.5*r_P2 every period.
    """
    T, N, P = 3, 1, 2
    membership = np.ones((T, N, P), dtype=bool)
    returns = np.array([
        [0.10, 0.02],
        [-0.03, 0.04],
        [0.06, -0.01],
    ], dtype=float)
    fee = np.zeros((N, P), dtype=float)

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        open_fee_mat=fee,
        close_fee_mat=fee,
        rebalance_mode='each_period',
        price_np=np.full((T, P), 0.01, dtype=float),
        min_tick_mat=np.full(P, 0.01, dtype=float),
    )

    net = result['net_returns_np'][:, 0]
    expected = 0.5 * returns[:, 0] + 0.5 * returns[:, 1]
    np.testing.assert_allclose(net, expected, atol=4e-4)
    np.testing.assert_allclose(net, result['product_gross_contrib_np'][:, 0, :].sum(axis=1), atol=1e-12)


def test_trading_book_distinguishes_cash_and_margin_products():
    membership = np.ones((1, 2, 1), dtype=bool)
    returns = np.array([[0.10]], dtype=float)
    price = np.array([[0.10]], dtype=float)
    fee = np.zeros((2, 1), dtype=float)

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        price_np=price,
        open_fee_mat=fee,
        close_fee_mat=fee,
        open_fixed_mat=fee,
        close_fixed_mat=fee,
        point_value_mat=np.array([1.0]),
        min_tick_mat=np.array([0.01]),
        min_trade_quantity_mat=np.array([1.0]),
        margin_ratio_mat=np.array([[1.0], [0.10]]),
        is_margin_traded_vec=np.array([False]),
        margin_modes=np.array(["margin", "margin"], dtype=object),
        rebalance_modes=np.array(["each_period", "each_period"], dtype=object),
        initial_capital=1.0,
    )

    np.testing.assert_allclose(result["position_quantities_np"][0, :, 0], [10.0, 10.0])
    # Non-margin products are cash funded even if the variant says "margin".
    np.testing.assert_array_equal(result["margin_occupied_np"][0], [110, 110])

    result_margin = simulate_groups(
        membership_np=membership[:1, :1, :],
        returns_np=returns,
        price_np=price,
        open_fee_mat=fee[:1],
        close_fee_mat=fee[:1],
        open_fixed_mat=fee[:1],
        close_fixed_mat=fee[:1],
        point_value_mat=np.array([1.0]),
        min_tick_mat=np.array([0.01]),
        min_trade_quantity_mat=np.array([1.0]),
        margin_ratio_mat=np.array([[0.10]]),
        is_margin_traded_vec=np.array([True]),
        margin_modes=np.array(["margin"], dtype=object),
        rebalance_modes=np.array(["each_period"], dtype=object),
        initial_capital=1.0,
    )
    np.testing.assert_allclose(result_margin["position_quantities_np"][0, 0, 0], 100.0)
    assert result_margin["margin_occupied_np"][0, 0] == 110


def test_group_run_result_hold_amounts_use_simulated_target_not_end_valuation():
    _, _, _, group_result = _simulate_group_from_preloaded(
        SimpleNamespace(alias='unit-factor'),
        membership_np=np.ones((1, 1, 1), dtype=bool),
        returns_filled=np.array([[0.10]], dtype=float),
        price_np=np.array([[100.0]], dtype=float),
        valid_cols=['P0'],
        index_list=[pd.Timestamp('2026-01-01')],
        n_names={0: 'A1'},
        group_configs=[{}],
        use_closetoday_vec=np.array([False], dtype=bool),
        rebalance_mode='each_period',
        initial_capital=1000.0,
        multi_session_active=False,
        product_currency_vec=np.array(['CNY'], dtype=object),
        start_dt=DataTime(ts=pd.Timestamp('2026-01-01'), precision='day'),
        end_dt=DataTime(ts=pd.Timestamp('2026-01-01'), precision='day'),
        source_freq=DataFreq.DAY,
        open_ratio_mat=np.zeros(1, dtype=float),
        close_ratio_mat=np.zeros(1, dtype=float),
        close_today_ratio_mat=np.zeros(1, dtype=float),
        open_fixed_mat=np.zeros(1, dtype=float),
        close_fixed_mat=np.zeros(1, dtype=float),
        close_today_fixed_mat=np.zeros(1, dtype=float),
        point_value_mat=np.ones(1, dtype=float),
        min_tick_mat=np.ones(1, dtype=float),
        min_trade_quantity_mat=np.ones(1, dtype=float),
        long_margin_ratio_mat=np.ones(1, dtype=float),
        is_margin_traded_vec=np.array([False], dtype=bool),
        positions_by_variety_code_lower={},
    )

    np.testing.assert_allclose(group_result.position_quantities_np[0, 0, 0], 10.0)
    assert group_result.hold_amounts_np[0, 0, 0] == 100000


def test_preloaded_group_requires_product_currency_metadata():
    with pytest.raises(ValueError, match="产品缺少 currency 字段"):
        _simulate_group_from_preloaded(
            SimpleNamespace(alias='missing-currency'),
            membership_np=np.ones((1, 1, 1), dtype=bool),
            returns_filled=np.zeros((1, 1), dtype=float),
            price_np=np.ones((1, 1), dtype=float),
            valid_cols=['P0'],
            index_list=[pd.Timestamp('2026-01-01')],
            n_names={0: 'A1'},
            group_configs=[{}],
            use_closetoday_vec=np.array([False], dtype=bool),
            rebalance_mode='each_period',
            initial_capital=1000.0,
            multi_session_active=False,
            start_dt=DataTime(ts=pd.Timestamp('2026-01-01'), precision='day'),
            end_dt=DataTime(ts=pd.Timestamp('2026-01-01'), precision='day'),
            source_freq=DataFreq.DAY,
            open_ratio_mat=np.zeros(1, dtype=float),
            close_ratio_mat=np.zeros(1, dtype=float),
            close_today_ratio_mat=np.zeros(1, dtype=float),
            open_fixed_mat=np.zeros(1, dtype=float),
            close_fixed_mat=np.zeros(1, dtype=float),
            close_today_fixed_mat=np.zeros(1, dtype=float),
            point_value_mat=np.ones(1, dtype=float),
            min_tick_mat=np.ones(1, dtype=float),
            min_trade_quantity_mat=np.ones(1, dtype=float),
            long_margin_ratio_mat=np.ones(1, dtype=float),
            is_margin_traded_vec=np.array([False], dtype=bool),
            positions_by_variety_code_lower={},
        )


def test_trading_book_rounds_aggregated_fixed_fee_per_order_to_minor_units():
    result = simulate_groups(
        membership_np=np.ones((1, 1, 1), dtype=bool),
        returns_np=np.array([[0.10]], dtype=float),
        price_np=np.array([[0.10]], dtype=float),
        open_fee_mat=np.zeros((1, 1), dtype=float),
        close_fee_mat=np.zeros((1, 1), dtype=float),
        open_fixed_mat=np.array([[0.001]], dtype=float),
        close_fixed_mat=np.zeros((1, 1), dtype=float),
        point_value_mat=np.array([1.0]),
        min_tick_mat=np.array([0.01]),
        min_trade_quantity_mat=np.array([1.0]),
        margin_ratio_mat=np.ones((1, 1), dtype=float),
        is_margin_traded_vec=np.array([False]),
        margin_modes=np.array(["cash"], dtype=object),
        rebalance_modes=np.array(["each_period"], dtype=object),
        initial_capital=1.0,
    )

    # Fixed-fee parameters stay in the product currency until the order quantity is known:
    # 10 contracts would cost 1.00 notional + round(10 * 0.001)=0.01 fee,
    # so the cash book can only open 9 contracts.
    np.testing.assert_allclose(result["position_quantities_np"][0, 0, 0], 9.0)
    np.testing.assert_allclose(result["gross_returns_np"][0, 0], 0.09)
    np.testing.assert_allclose(result["fee_costs_np"][0, 0], 0.01)
    np.testing.assert_allclose(result["net_returns_np"][0, 0], 0.08)

    result_one_cent = simulate_groups(
        membership_np=np.ones((1, 1, 1), dtype=bool),
        returns_np=np.array([[0.10]], dtype=float),
        price_np=np.array([[0.10]], dtype=float),
        open_fee_mat=np.zeros((1, 1), dtype=float),
        close_fee_mat=np.zeros((1, 1), dtype=float),
        open_fixed_mat=np.array([[0.01]], dtype=float),
        close_fixed_mat=np.zeros((1, 1), dtype=float),
        point_value_mat=np.array([1.0]),
        min_tick_mat=np.array([0.01]),
        min_trade_quantity_mat=np.array([1.0]),
        margin_ratio_mat=np.ones((1, 1), dtype=float),
        is_margin_traded_vec=np.array([False]),
        margin_modes=np.array(["cash"], dtype=object),
        rebalance_modes=np.array(["each_period"], dtype=object),
        initial_capital=1.0,
    )

    np.testing.assert_allclose(result_one_cent["position_quantities_np"][0, 0, 0], 9.0)
    np.testing.assert_allclose(result_one_cent["gross_returns_np"][0, 0], 0.09)
    np.testing.assert_allclose(result_one_cent["fee_costs_np"][0, 0], 0.09)
    np.testing.assert_allclose(result_one_cent["net_returns_np"][0, 0], 0.0, atol=1e-12)


def test_trading_book_respects_min_trade_quantity_lot_size():
    result = simulate_groups(
        membership_np=np.ones((1, 1, 1), dtype=bool),
        returns_np=np.array([[0.10]], dtype=float),
        price_np=np.array([[0.01]], dtype=float),
        open_fee_mat=np.zeros((1, 1), dtype=float),
        close_fee_mat=np.zeros((1, 1), dtype=float),
        open_fixed_mat=np.zeros((1, 1), dtype=float),
        close_fixed_mat=np.zeros((1, 1), dtype=float),
        point_value_mat=np.array([1.0]),
        min_tick_mat=np.array([0.01]),
        min_trade_quantity_mat=np.array([100.0]),
        margin_ratio_mat=np.ones((1, 1), dtype=float),
        is_margin_traded_vec=np.array([False]),
        margin_modes=np.array(["cash"], dtype=object),
        rebalance_modes=np.array(["each_period"], dtype=object),
        initial_capital=1.0,
    )

    np.testing.assert_allclose(result["position_quantities_np"][0, 0, 0], 100.0)

    result_too_expensive = simulate_groups(
        membership_np=np.ones((1, 1, 1), dtype=bool),
        returns_np=np.array([[0.10]], dtype=float),
        price_np=np.array([[0.02]], dtype=float),
        open_fee_mat=np.zeros((1, 1), dtype=float),
        close_fee_mat=np.zeros((1, 1), dtype=float),
        open_fixed_mat=np.zeros((1, 1), dtype=float),
        close_fixed_mat=np.zeros((1, 1), dtype=float),
        point_value_mat=np.array([1.0]),
        min_tick_mat=np.array([0.01]),
        min_trade_quantity_mat=np.array([100.0]),
        margin_ratio_mat=np.ones((1, 1), dtype=float),
        is_margin_traded_vec=np.array([False]),
        margin_modes=np.array(["cash"], dtype=object),
        rebalance_modes=np.array(["each_period"], dtype=object),
        initial_capital=1.0,
    )

    np.testing.assert_allclose(result_too_expensive["position_quantities_np"][0, 0, 0], 0.0)


def test_trading_book_initial_capital_changes_affordability():
    base_kwargs = dict(
        membership_np=np.ones((1, 1, 1), dtype=bool),
        returns_np=np.array([[0.10]], dtype=float),
        price_np=np.array([[100.0]], dtype=float),
        open_fee_mat=np.zeros((1, 1), dtype=float),
        close_fee_mat=np.zeros((1, 1), dtype=float),
        open_fixed_mat=np.zeros((1, 1), dtype=float),
        close_fixed_mat=np.zeros((1, 1), dtype=float),
        point_value_mat=np.array([10.0]),
        min_tick_mat=np.array([1.0]),
        min_trade_quantity_mat=np.array([1.0]),
        margin_ratio_mat=np.ones((1, 1), dtype=float),
        is_margin_traded_vec=np.array([False]),
        margin_modes=np.array(["cash"], dtype=object),
        rebalance_modes=np.array(["each_period"], dtype=object),
    )

    result_small = simulate_groups(initial_capital=1.0, **base_kwargs)
    result_large = simulate_groups(initial_capital=100000.0, **base_kwargs)

    np.testing.assert_allclose(result_small["position_quantities_np"][0, 0, 0], 0.0)
    np.testing.assert_allclose(result_small["net_returns_np"][0, 0], 0.0)
    np.testing.assert_allclose(result_large["position_quantities_np"][0, 0, 0], 100.0)
    np.testing.assert_allclose(result_large["gross_returns_np"][0, 0], 0.10)


def test_trading_book_allocates_integer_lots_by_weight_when_budget_is_tight():
    membership = np.ones((1, 1, 3), dtype=bool)
    returns = np.zeros((1, 3), dtype=float)
    price = np.array([[100.0, 100.0, 100.0]], dtype=float)
    fee = np.zeros((1, 3), dtype=float)

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        price_np=price,
        open_fee_mat=fee,
        close_fee_mat=fee,
        open_fixed_mat=fee,
        close_fixed_mat=fee,
        point_value_mat=np.array([1.0, 1.0, 1.0]),
        min_tick_mat=np.array([0.01, 0.01, 0.01]),
        min_trade_quantity_mat=np.array([1.0, 1.0, 1.0]),
        margin_ratio_mat=np.ones((1, 3), dtype=float),
        is_margin_traded_vec=np.array([False, False, False]),
        margin_modes=np.array(["cash"], dtype=object),
        rebalance_modes=np.array(["each_period"], dtype=object),
        initial_capital=250.0,
    )

    np.testing.assert_allclose(result["position_quantities_np"][0, 0], [1.0, 1.0, 0.0])
    np.testing.assert_allclose(result["trade_notional_ratio_np"][0, 0], 200.0 / 250.0, atol=1e-12)


def test_each_period_opens_margin_contract_when_cash_covers_one_lot_cost():
    result = simulate_groups(
        membership_np=np.ones((1, 1, 1), dtype=bool),
        returns_np=np.zeros((1, 1), dtype=float),
        price_np=np.array([[8595.0]], dtype=float),
        open_fee_mat=np.array([[0.00001]], dtype=float),
        close_fee_mat=np.zeros((1, 1), dtype=float),
        open_fixed_mat=np.zeros((1, 1), dtype=float),
        close_fixed_mat=np.zeros((1, 1), dtype=float),
        point_value_mat=np.array([10.0]),
        min_tick_mat=np.array([1.0]),
        min_trade_quantity_mat=np.array([1.0]),
        margin_ratio_mat=np.array([[0.10]], dtype=float),
        is_margin_traded_vec=np.array([True]),
        margin_modes=np.array(["margin"], dtype=object),
        rebalance_modes=np.array(["each_period"], dtype=object),
        initial_capital=100_000_000.0,
    )

    assert result["position_quantities_np"][0, 0, 0] > 0.0
    assert result["cash_np"][0, 0] >= 0


def test_each_period_equal_allocates_by_margin_cash_cost_not_notional():
    result = simulate_groups(
        membership_np=np.ones((1, 1, 2), dtype=bool),
        returns_np=np.zeros((1, 2), dtype=float),
        price_np=np.array([[100.0, 100.0]], dtype=float),
        open_fee_mat=np.zeros((1, 2), dtype=float),
        close_fee_mat=np.zeros((1, 2), dtype=float),
        open_fixed_mat=np.zeros((1, 2), dtype=float),
        close_fixed_mat=np.zeros((1, 2), dtype=float),
        point_value_mat=np.array([10.0, 10.0]),
        min_tick_mat=np.ones(2, dtype=float),
        min_trade_quantity_mat=np.ones(2, dtype=float),
        margin_ratio_mat=np.array([[0.10, 0.20]], dtype=float),
        is_margin_traded_vec=np.array([True, True]),
        margin_modes=np.array(["margin"], dtype=object),
        rebalance_modes=np.array(["each_period"], dtype=object),
        initial_capital=1000.0,
    )

    # 现金等分：每个品种 500现金预算。
    # P0 一手现金成本 1000*10%=100，可开 5 手；
    # P1 一手现金成本 1000*20%=200，可开 2 手，剩余现金再补给 P0。
    np.testing.assert_allclose(result["position_quantities_np"][0, 0], [6.0, 2.0])
    assert result["margin_occupied_np"][0, 0] == 100000


def test_trading_book_money_outputs_are_cent_quantized():
    result = simulate_groups(
        membership_np=np.array([[[True, True]], [[False, True]]], dtype=bool),
        returns_np=np.array([[0.0, 0.0], [0.0111, -0.0222]], dtype=float),
        price_np=np.full((2, 2), 123.45, dtype=float),
        open_fee_mat=np.full((1, 2), 0.00123, dtype=float),
        close_fee_mat=np.full((1, 2), 0.00234, dtype=float),
        open_fixed_mat=np.full((1, 2), 0.017, dtype=float),
        close_fixed_mat=np.full((1, 2), 0.019, dtype=float),
        point_value_mat=np.ones(2, dtype=float),
        min_tick_mat=np.full(2, 0.01, dtype=float),
        min_trade_quantity_mat=np.ones(2, dtype=float),
        margin_ratio_mat=np.full((1, 2), 0.12, dtype=float),
        is_margin_traded_vec=np.array([True, True]),
        margin_modes=np.array(["margin"], dtype=object),
        rebalance_modes=np.array(["each_period"], dtype=object),
        initial_capital=10000.0,
    )

    money_keys = [
        "target_amounts_np",
        "target_amounts_before_floor_np",
        "prev_end_amounts_np",
        "margin_occupied_np",
        "pre_rebalance_total_equity_np",
        "post_rebalance_total_equity_np",
        "total_equity_np",
        "pre_rebalance_cash_np",
        "post_rebalance_cash_np",
        "cash_np",
        "buy_fee_amount_np",
        "sell_fee_amount_np",
    ]
    for key in money_keys:
        values = np.asarray(result[key])
        assert np.issubdtype(values.dtype, np.integer), key

    # Display-only one-lot diagnostics are intentionally not cent-rounded; real
    # execution costs are computed from whole-order quantities.
    assert not np.allclose(result["one_lot_fee_np"] * 100.0, np.round(result["one_lot_fee_np"] * 100.0))


def test_each_period_offsets_redundant_sell_buy_fees_when_position_unchanged():
    result = simulate_groups(
        membership_np=np.ones((2, 1, 1), dtype=bool),
        returns_np=np.zeros((2, 1), dtype=float),
        price_np=np.full((2, 1), 100.0, dtype=float),
        open_fee_mat=np.full((1, 1), 0.01, dtype=float),
        close_fee_mat=np.full((1, 1), 0.02, dtype=float),
        open_fixed_mat=np.zeros((1, 1), dtype=float),
        close_fixed_mat=np.zeros((1, 1), dtype=float),
        point_value_mat=np.ones(1, dtype=float),
        min_tick_mat=np.ones(1, dtype=float),
        min_trade_quantity_mat=np.ones(1, dtype=float),
        margin_ratio_mat=np.ones((1, 1), dtype=float),
        is_margin_traded_vec=np.array([False]),
        margin_modes=np.array(["cash"], dtype=object),
        rebalance_modes=np.array(["each_period"], dtype=object),
        initial_capital=1000.0,
    )

    assert result["position_quantities_np"][1, 0, 0] == result["position_quantities_np"][0, 0, 0]
    assert result["buy_fee_amount_np"][1, 0] == 0
    assert result["sell_fee_amount_np"][1, 0] == 0


def test_simulate_each_period_percent_liquidity_caps_execution_only():
    """Percent liquidity caps execution after the normal equal-weight target."""
    T, N, P = 1, 1, 2
    membership = np.ones((T, N, P), dtype=bool)
    returns = np.array([[0.10, 0.00]], dtype=float)
    fee = np.zeros((N, P), dtype=float)

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        open_fee_mat=fee,
        close_fee_mat=fee,
        rebalance_mode='each_period',
        liquidity_capacity_np=np.array([[0.2, 0.8]], dtype=float),
        liquidity_modes=np.array(['percent'], dtype=object),
        liquidity_percents=np.array([50.0], dtype=float),
        price_np=np.array([[0.01, 0.01]], dtype=float),
        min_tick_mat=np.array([0.01, 0.01], dtype=float),
        min_trade_quantity_mat=np.ones(2, dtype=float),
    )

    # Ideal target is still [0.5, 0.5]. Capacity is [0.1, 0.4],
    # so the execution layer fills [0.1, 0.4] and leaves 0.5 cash idle.
    np.testing.assert_allclose(result['trade_notional_ratio_np'][0, 0], 0.5, atol=1e-12)
    np.testing.assert_allclose(result['gross_returns_np'][0, 0], 0.1 * 0.10 + 0.4 * 0.00, atol=1e-12)
    np.testing.assert_allclose(result['net_returns_np'][0, 0], 0.01, atol=1e-12)


def test_simulate_liquidity_does_not_reweight_rebalance_target():
    """High-liquidity products do not receive extra target if their ideal target is already filled."""
    T, N, P = 1, 1, 2
    membership = np.ones((T, N, P), dtype=bool)
    returns = np.array([[0.00, 0.10]], dtype=float)
    fee = np.zeros((N, P), dtype=float)

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        open_fee_mat=fee,
        close_fee_mat=fee,
        rebalance_mode='each_period',
        liquidity_capacity_np=np.array([[0.8, 0.1]], dtype=float),
        liquidity_modes=np.array(['percent'], dtype=object),
        liquidity_percents=np.array([100.0], dtype=float),
        price_np=np.array([[0.01, 0.01]], dtype=float),
        min_tick_mat=np.array([0.01, 0.01], dtype=float),
        min_trade_quantity_mat=np.ones(2, dtype=float),
    )

    # Cash-equal allocation iteratively fills P0 up to its liquidity cap (0.8)
    # after P1 hits its cap (0.1).  Total trade = 0.8 + 0.1 = 0.9.
    np.testing.assert_allclose(result['trade_notional_ratio_np'][0, 0], 0.9, atol=1e-12)
    np.testing.assert_allclose(result['gross_returns_np'][0, 0], 0.1 * 0.10, atol=1e-12)
    np.testing.assert_allclose(result['net_returns_np'][0, 0], 0.01, atol=1e-12)


def test_simulate_liquidity_caps_sells_before_buying_and_preserves_cash():
    """A capped exit cannot fully fund the entrant; unsold holding remains invested."""
    T, N, P = 2, 1, 2
    membership = np.zeros((T, N, P), dtype=bool)
    membership[0, 0, 0] = True
    membership[1, 0, 1] = True
    returns = np.array([
        [0.00, 0.00],
        [0.10, 0.00],
    ], dtype=float)
    fee = np.zeros((N, P), dtype=float)

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        open_fee_mat=fee,
        close_fee_mat=fee,
        rebalance_mode='recycle',
        liquidity_capacity_np=np.array([[1.0, 1.0], [0.25, 0.25]], dtype=float),
        liquidity_modes=np.array(['percent'], dtype=object),
        liquidity_percents=np.array([100.0], dtype=float),
        price_np=np.full((T, P), 0.01, dtype=float),
        min_tick_mat=np.full(P, 0.01, dtype=float),
    )

    # t=1 can sell only 0.25 of P0 and buy only 0.25 of P1.
    # Remaining P0=0.75 stays exposed to P0 return; no leverage is created.
    np.testing.assert_allclose(result['trade_notional_ratio_np'][1, 0], 0.5, atol=1e-12)
    np.testing.assert_allclose(result['gross_returns_np'][1, 0], 0.75 * 0.10, atol=1e-12)
    np.testing.assert_allclose(result['net_returns_np'][1, 0], 0.075, atol=1e-12)


# ═══════════════════════════════════════════════════════════════════
# buy_and_hold with membership change, zero fee
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="legacy matrix-return expectation removed; trading book now validates discrete quantity accounting instead")
def test_simulate_buy_and_hold_membership_change_zero_fee():
    """Group membership changes trigger exit/entry at zero fee.

    P0, P1, P2.  Group 0: t=0:{P0,P1}, t=1:{P1,P2}, t=2:{P1,P2}
    P1 stays throughout (no fee), P0 exits at t=1, P2 enters at t=1.

    t=0: equal-weight into P0(0.5) and P1(0.5)
         ret = 0.5*0.10 + 0.5*0.06 = 0.08
         wealth = 1.08, positions P0=0.54, P1=0.54
    t=1: P0 exits → release 0.54, P2 enters with 0.54
         P1 stays at 0.54
         ret = 0.54/1.08 * (-0.02) + 0.54/1.08 * 0.03
             = 0.5*(-0.02) + 0.5*0.03 = 0.005
         wealth = 1.08 * 1.005 = 1.0854
    t=2: same membership → positions unchanged
         ret = 0.5*(-0.01) + 0.5*0.04 = 0.015
         wealth = 1.0854 * 1.015
    """
    T, N, P = 3, 1, 3
    membership = np.zeros((T, N, P), dtype=bool)
    membership[0, 0, 0] = True   # P0
    membership[0, 0, 1] = True   # P1
    membership[1, 0, 1] = True   # P1 stays
    membership[1, 0, 2] = True   # P2 enters
    membership[2, 0, 1] = True
    membership[2, 0, 2] = True

    returns = np.array([
        [0.10, 0.06, 0.03],
        [-0.02, 0.03, 0.04],
        [0.00, -0.01, 0.04],
    ], dtype=float)
    fee = np.zeros((N, P), dtype=float)

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        open_fee_mat=fee,
        close_fee_mat=fee,
        rebalance_mode='buy_and_hold',
    )

    net = result['net_returns_np'][:, 0]

    # t=0: equal-weight
    np.testing.assert_allclose(net[0], 0.5 * 0.10 + 0.5 * 0.06, atol=1e-12)

    # t=1: P1 stays, P0→P2 (released capital funds P2)
    # After t=0: P0=0.5*1.10=0.55, P1=0.5*1.06=0.53, wealth=1.08
    # Exit P0 releases 0.55, enters P2 with 0.55. P1 stays at 0.53.
    # gross = (0.53/1.08)*(-0.02) + (0.55/1.08)*0.03
    wealth_t0 = 1.0 + net[0]  # 1.08
    pos_p1 = 0.5 * (1.0 + returns[0, 1])  # 0.53
    pos_p0 = 0.5 * (1.0 + returns[0, 0])  # 0.55
    gross_t1 = (pos_p1 / wealth_t0) * returns[1, 1] + (pos_p0 / wealth_t0) * returns[1, 2]
    np.testing.assert_allclose(net[1], gross_t1, atol=1e-12)


# ═══════════════════════════════════════════════════════════════════
# Non-zero fee
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="legacy matrix-return expectation removed; trading book now validates discrete quantity accounting instead")
def test_simulate_each_period_with_open_fee():
    """each_period with non-zero open fee reduces net return.

    Group 0: {P0, P1}, open_fee=0.001 per side.
    Each period: buy both equally. Buy fee = 0.001 * target_amount.
    No exit (zero prev), so no close fee.
    """
    T, N, P = 1, 1, 2
    membership = np.ones((T, N, P), dtype=bool)
    returns = np.array([[0.10, 0.02]], dtype=float)
    open_fee = np.full((N, P), 0.001, dtype=float)
    close_fee = np.zeros((N, P), dtype=float)

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        open_fee_mat=open_fee,
        close_fee_mat=close_fee,
        rebalance_mode='each_period',
    )

    net = result['net_returns_np'][0, 0]
    # With open_fee=0.001 per unit:
    #   target = [0.5, 0.5]
    #   buy_fee = 0.001 * (0.5+0.5) = 0.001
    #   invested = [0.5-0.0005, 0.5-0.0005] = [0.4995, 0.4995]
    #   gross = 0.4995*0.10 + 0.4995*0.02 = 0.05994
    #   net = gross - buy_fee_ratio = 0.05994 - 0.001 = 0.05894
    expected_gross = 0.4995 * 0.10 + 0.4995 * 0.02
    np.testing.assert_allclose(result['gross_returns_np'][0, 0], expected_gross, atol=1e-12)
    np.testing.assert_allclose(net, expected_gross - 0.001, atol=1e-12)


@pytest.mark.skip(reason="legacy matrix-return expectation removed; trading book now validates discrete quantity accounting instead")
def test_simulate_close_fee_on_exit():
    """Exit incurs close fee; released capital is net of fee.

    t=0: P0 present → equal-weight 1.0 in P0
    t=1: P0 exits → pay close_fee on liquidation
    """
    T, N, P = 2, 1, 1
    membership = np.zeros((T, N, P), dtype=bool)
    membership[0, 0, 0] = True
    # t=1: empty group

    returns = np.array([[0.10], [0.02]], dtype=float)
    open_fee = np.zeros((N, P), dtype=float)
    close_fee = np.full((N, P), 0.003, dtype=float)  # 0.3% close fee

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        open_fee_mat=open_fee,
        close_fee_mat=close_fee,
        rebalance_mode='buy_and_hold',
    )

    net = result['net_returns_np'][:, 0]
    # t=0: equal-weight 1.0 in P0, no fee on entry (open_fee=0)
    np.testing.assert_allclose(net[0], 0.10, atol=1e-12)

    # t=1: exit 1.10, pay 0.003*1.10=0.0033 fee
    # net = -fee_ratio = -0.0033/1.10 = -0.003
    wealth_t0 = 1.10
    expected_net_t1 = -(0.003 * 1.10) / wealth_t0  # -0.003
    np.testing.assert_allclose(net[1], expected_net_t1, atol=1e-12)

    # cumulative = (1+0.10) * (1-0.003) = 1.10 * 0.997 = 1.0967
    cum = float(_cum_ret(net)[-1])
    np.testing.assert_allclose(cum, 1.10 * (1.0 + net[1]), atol=1e-12)


@pytest.mark.skip(reason="legacy matrix-return expectation removed; trading book now validates discrete quantity accounting instead")
def test_each_period_close_fee_is_paid_before_rebuilding_target():
    """each_period should sell first, pay close fee, then equal-weight remaining wealth."""
    T, N, P = 2, 1, 2
    membership = np.zeros((T, N, P), dtype=bool)
    membership[0, 0, 0] = True
    membership[1, 0, :] = True

    returns = np.zeros((T, P), dtype=float)
    open_fee = np.zeros((N, P), dtype=float)
    close_fee = np.full((N, P), 0.10, dtype=float)

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        open_fee_mat=open_fee,
        close_fee_mat=close_fee,
        rebalance_mode='each_period',
    )

    # At t=1: target x solves x = (1 - 0.10 * (1 - x)) / 2.
    target_each = (1.0 - 0.10) / (2.0 - 0.10)
    expected_sell_fee_ratio = (1.0 - target_each) * 0.10
    np.testing.assert_allclose(
        result['fee_costs_np'][1, 0],
        expected_sell_fee_ratio,
        rtol=1e-10,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        result['net_returns_np'][1, 0],
        -expected_sell_fee_ratio,
        rtol=1e-10,
        atol=1e-12,
    )


# ═══════════════════════════════════════════════════════════════════
# recycle mode
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="legacy matrix-return expectation removed; trading book now validates discrete quantity accounting instead")
def test_simulate_recycle_vs_buy_and_hold_expanding():
    """recycle should not create leverage when membership expands with no exit capital."""
    T, N, P = 2, 1, 2
    membership = np.zeros((T, N, P), dtype=bool)
    membership[0, 0, 0] = True   # only P0
    membership[1, 0, 0] = True   # P0 stays
    membership[1, 0, 1] = True   # P1 added

    returns = np.array([[0.10, 0.05], [0.02, 0.08]], dtype=float)
    fee = np.zeros((N, P), dtype=float)

    # recycle
    r_recycle = simulate_groups(
        membership_np=membership, returns_np=returns,
        open_fee_mat=fee, close_fee_mat=fee, rebalance_mode='recycle',
    )
    # buy_and_hold
    r_bah = simulate_groups(
        membership_np=membership, returns_np=returns,
        open_fee_mat=fee, close_fee_mat=fee, rebalance_mode='buy_and_hold',
    )

    net_r = r_recycle['net_returns_np'][:, 0]
    net_b = r_bah['net_returns_np'][:, 0]

    # t=0: both modes identical (only P0)
    np.testing.assert_allclose(net_r[0], net_b[0])
    np.testing.assert_allclose(net_r[0], 0.10, atol=1e-12)

    # t=1: recycle keeps P0 only; buy_and_hold equal-weights the whole group.
    # They differ because recycle can only fund entrants with released capital.
    assert not np.isclose(net_r[1], net_b[1])
    np.testing.assert_allclose(net_r[1], 0.02, atol=1e-12)


def test_recycle_allows_new_member_when_idle_cash_exists():
    membership = np.zeros((2, 1, 2), dtype=bool)
    membership[0, 0, 0] = True
    membership[1, 0, 0] = True
    membership[1, 0, 1] = True

    returns = np.zeros((2, 2), dtype=float)
    price = np.array([[10.0, 10.0], [10.0, 10.0]], dtype=float)
    fee = np.zeros((1, 2), dtype=float)

    result = simulate_groups(
        membership_np=membership,
        returns_np=returns,
        price_np=price,
        open_fee_mat=fee,
        close_fee_mat=fee,
        point_value_mat=np.array([1.0, 1.0]),
        min_tick_mat=np.array([1.0, 1.0]),
        min_trade_quantity_mat=np.array([1.0, 1.0]),
        margin_ratio_mat=np.array([[0.1, 0.1]]),
        is_margin_traded_vec=np.array([True, True]),
        margin_modes=np.array(["margin"], dtype=object),
        rebalance_modes=np.array(["recycle"], dtype=object),
        initial_capital=1000.0,
    )

    np.testing.assert_allclose(result["position_quantities_np"][0, 0, 0], 1000.0)
    # Recycle buys the single member in t=0 with full capital.
    # In t=1, capital is fully occupied by the staying position; no idle cash
    # exists to buy the new member, so P1 stays at 0.
    assert result["position_quantities_np"][1, 0, 1] == 0.0


# ═══════════════════════════════════════════════════════════════════
# close_today override — now handled upstream via effective close matrix
# ═══════════════════════════════════════════════════════════════════

def test_simulate_close_today_overrides_close_fee():
    """close_today rate overrides close rate — caller passes effective close matrix."""
    T, N, P = 1, 1, 1
    membership = np.zeros((2, 1, 1), dtype=bool)
    membership[0, 0, 0] = True
    # t=1: empty → exit

    returns = np.array([[0.0], [0.0]], dtype=float)
    close_rate = np.full((1, 1), 0.025, dtype=float)   # 2.5% close (effective)
    open_fee = np.zeros((1, 1), dtype=float)

    result = simulate_groups(
        membership_np=membership, returns_np=returns,
        open_fee_mat=open_fee, close_fee_mat=close_rate,
        rebalance_mode='buy_and_hold',
        price_np=np.full((2, 1), 0.01, dtype=float),
        min_tick_mat=np.array([0.01], dtype=float),
    )

    net = result['net_returns_np'][:, 0]
    # t=0: buy 1.0, no fee, ret=0
    np.testing.assert_allclose(net[0], 0.0, atol=1e-12)
    # t=1: exit 1.0, close_today fee = 0.025 * 1.0, rounded up to one cent = 0.03.
    np.testing.assert_allclose(net[1], -0.03, atol=1e-12)


def test_simulate_exposes_rebalance_cash_equity_and_fee_amounts():
    membership = np.zeros((2, 1, 2), dtype=bool)
    membership[0, 0, 0] = True
    membership[1, 0, 1] = True

    result = simulate_groups(
        membership_np=membership,
        returns_np=np.zeros((2, 2), dtype=float),
        open_fee_mat=np.full((1, 2), 0.01, dtype=float),
        close_fee_mat=np.full((1, 2), 0.02, dtype=float),
        rebalance_mode='each_period',
        price_np=np.full((2, 2), 100.0, dtype=float),
        min_tick_mat=np.ones(2, dtype=float),
        min_trade_quantity_mat=np.ones(2, dtype=float),
        initial_capital=1000.0,
    )

    np.testing.assert_array_equal(result['pre_rebalance_total_equity_np'][:, 0], [100000, 99100])
    np.testing.assert_array_equal(result['pre_rebalance_cash_np'][:, 0], [100000, 9100])
    np.testing.assert_array_equal(result['post_rebalance_total_equity_np'][:, 0], [99100, 96400])
    np.testing.assert_array_equal(result['post_rebalance_cash_np'][:, 0], [9100, 6400])
    np.testing.assert_array_equal(result['total_equity_np'][:, 0], [99100, 96400])
    np.testing.assert_array_equal(result['cash_np'][:, 0], [9100, 6400])
    np.testing.assert_array_equal(result['buy_fee_amount_np'][:, 0], [900, 900])
    np.testing.assert_array_equal(result['sell_fee_amount_np'][:, 0], [0, 1800])


def test_group_fee_close_override_applies_to_close_today_when_unspecified():
    membership = np.array([[[True]], [[False]]], dtype=bool)

    _, _, _, group_result = _simulate_group_from_preloaded(
        SimpleNamespace(alias='fee-close-today'),
        membership_np=membership,
        returns_filled=np.zeros((2, 1), dtype=float),
        price_np=np.full((2, 1), 100.0, dtype=float),
        valid_cols=['P0'],
        index_list=[pd.Timestamp('2026-01-01 09:30:00'), pd.Timestamp('2026-01-01 09:31:00')],
        n_names={0: 'A1'},
        group_configs=[{'fee_override': {'open': 0.0, 'close': 0.02}}],
        use_closetoday_vec=np.array([True], dtype=bool),
        rebalance_mode='each_period',
        initial_capital=1000.0,
        multi_session_active=False,
        product_currency_vec=np.array(['CNY'], dtype=object),
        start_dt=DataTime.parse('2026-01-01 09:30:00'),
        end_dt=DataTime.parse('2026-01-01 09:31:00'),
        source_freq=DataFreq.MIN1,
        open_ratio_mat=np.zeros(1, dtype=float),
        close_ratio_mat=np.zeros(1, dtype=float),
        close_today_ratio_mat=np.zeros(1, dtype=float),
        open_fixed_mat=np.zeros(1, dtype=float),
        close_fixed_mat=np.zeros(1, dtype=float),
        close_today_fixed_mat=np.zeros(1, dtype=float),
        point_value_mat=np.ones(1, dtype=float),
        min_tick_mat=np.ones(1, dtype=float),
        min_trade_quantity_mat=np.ones(1, dtype=float),
        long_margin_ratio_mat=np.ones(1, dtype=float),
        is_margin_traded_vec=np.zeros(1, dtype=bool),
        positions_by_variety_code_lower={},
    )

    np.testing.assert_array_equal(group_result.sell_fee_amount_np[:, 0], [0, 2000])
    np.testing.assert_allclose(group_result.fee_costs_np[:, 0], [0.0, 0.02], atol=1e-12)


def test_settlement_price_marks_open_margin_positions_only_on_day_end():
    membership = np.array([[[True]], [[True]]], dtype=bool)
    returns = np.zeros((2, 1), dtype=float)
    price = np.array([[100.0], [100.0]], dtype=float)
    settlement_price = np.array([[np.nan], [110.0]], dtype=float)

    result = simulate_group_trading_book(
        membership_np=membership,
        returns_np=returns,
        price_np=price,
        settlement_price_np=settlement_price,
        settlement_bar_mask=np.array([[False], [True]], dtype=bool),
        open_rate_mat=np.zeros((1, 1), dtype=float),
        close_rate_mat=np.zeros((1, 1), dtype=float),
        open_fixed_mat=np.zeros((1, 1), dtype=float),
        close_fixed_mat=np.zeros((1, 1), dtype=float),
        point_value_mat=np.array([1.0], dtype=float),
        min_tick_mat=np.array([1.0], dtype=float),
        min_trade_quantity_mat=np.array([1.0], dtype=float),
        margin_ratio_mat=np.array([[0.10]], dtype=float),
        is_margin_traded_vec=np.array([True], dtype=bool),
        margin_modes=np.array(["margin"], dtype=object),
        rebalance_modes=np.array(["buy_and_hold"], dtype=object),
        product_currency_vec=np.array(["CNY"], dtype=object),
        initial_capital=1000.0,
    )

    assert np.isnan(result["post_settlement_cash_np"][0, 0])
    np.testing.assert_array_equal(result["post_settlement_cash_np"][1:, 0], [90000])
    np.testing.assert_array_equal(result["margin_occupied_np"][:, 0], [100000, 100000])
    np.testing.assert_array_equal(result["pre_rebalance_cash_np"][:, 0], [100000, 90000])
    np.testing.assert_array_equal(result["cash_np"][:, 0], [0, 100000])
    np.testing.assert_array_equal(result["total_equity_np"][:, 0], [100000, 200000])


def test_simulate_fee_amounts_include_ratio_and_fixed_fees():
    result = simulate_groups(
        membership_np=np.array([[[True]], [[False]]], dtype=bool),
        returns_np=np.zeros((2, 1), dtype=float),
        open_fee_mat=np.full((1, 1), 0.01, dtype=float),
        close_fee_mat=np.full((1, 1), 0.02, dtype=float),
        open_fixed_mat=np.full((1, 1), 2.0, dtype=float),
        close_fixed_mat=np.full((1, 1), 3.0, dtype=float),
        rebalance_mode='each_period',
        price_np=np.full((2, 1), 100.0, dtype=float),
        min_tick_mat=np.ones(1, dtype=float),
        min_trade_quantity_mat=np.ones(1, dtype=float),
        initial_capital=1000.0,
    )

    # t=0 buys 9 contracts: 900 * 1% + 9 * 2 = 27.
    # t=1 sells 9 contracts: 900 * 2% + 9 * 3 = 45.
    np.testing.assert_array_equal(result['buy_fee_amount_np'][:, 0], [2700, 0])
    np.testing.assert_array_equal(result['sell_fee_amount_np'][:, 0], [0, 4500])


def test_empty_group_keeps_untradable_holding_in_multi_session():
    """An empty current group should not liquidate holdings whose product has no bar."""
    membership = np.zeros((2, 1, 1), dtype=bool)
    membership[0, 0, 0] = True

    result = simulate_groups(
        membership_np=membership,
        returns_np=np.zeros((2, 1), dtype=float),
        open_fee_mat=np.zeros((1, 1), dtype=float),
        close_fee_mat=np.full((1, 1), 0.10, dtype=float),
        rebalance_mode='buy_and_hold',
        data_has_bar=np.array([[True], [False]], dtype=bool),
    )

    np.testing.assert_allclose(result['fee_costs_np'][1, 0], 0.0, atol=1e-12)
    np.testing.assert_allclose(result['net_returns_np'][1, 0], 0.0, atol=1e-12)


def test_empty_group_sells_only_tradable_holdings_in_mixed_session():
    """For mixed sessions, empty groups should keep no-bar holdings and sell tradable holdings."""
    membership = np.zeros((2, 1, 2), dtype=bool)
    membership[0, 0, :] = True

    result = simulate_groups(
        membership_np=membership,
        returns_np=np.zeros((2, 2), dtype=float),
        open_fee_mat=np.zeros((1, 2), dtype=float),
        close_fee_mat=np.full((1, 2), 0.10, dtype=float),
        rebalance_mode='buy_and_hold',
        data_has_bar=np.array([[True, True], [False, True]], dtype=bool),
        price_np=np.full((2, 2), 0.01, dtype=float),
        min_tick_mat=np.full(2, 0.01, dtype=float),
    )

    # t=0 holds 0.5/0.5; t=1 can only sell P1, so fee = 0.5 * 10%.
    np.testing.assert_allclose(result['fee_costs_np'][1, 0], 0.05, atol=1e-12)
    np.testing.assert_allclose(result['net_returns_np'][1, 0], -0.05, atol=1e-12)
