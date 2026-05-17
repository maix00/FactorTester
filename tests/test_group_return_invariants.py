from __future__ import annotations

import numpy as np

from tools.factors.tests.single_factor_test.group.core import (
    compute_group_gross_returns,
    compute_group_net_returns,
)


def test_net_return_matches_gross_and_fee_formula():
    gross = np.array([0.10, -0.05])
    fee_ratio = np.array([0.01, 0.02])

    net = compute_group_net_returns(gross, fee_ratio)

    np.testing.assert_allclose(net, [0.089, -0.069])


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
