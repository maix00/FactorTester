from __future__ import annotations

import numpy as np

from tools.factors.tests.single_factor_test.group.core import build_target_amounts


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
