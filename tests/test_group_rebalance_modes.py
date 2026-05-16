import unittest

import numpy as np

from tools.factors.tests.single_factor_test.group.core import build_target_amounts


class TestGroupRebalanceModes(unittest.TestCase):
    def test_each_period_reweights_current_members_equally(self):
        targets = build_target_amounts(
            np.array([[True, True, False]]),
            np.array([[0.8, 0.2, 0.0]]),
            np.array([1.0]),
            "each_period",
        )
        np.testing.assert_allclose(targets, [[0.5, 0.5, 0.0]])

    def test_buy_and_hold_preserves_staying_positions_when_membership_unchanged(self):
        targets = build_target_amounts(
            np.array([[True, True, False]]),
            np.array([[0.8, 0.2, 0.0]]),
            np.array([1.0]),
            "buy_and_hold",
        )
        np.testing.assert_allclose(targets, [[0.8, 0.2, 0.0]])

    def test_buy_and_hold_uses_released_capital_for_new_member(self):
        targets = build_target_amounts(
            np.array([[True, False, True]]),
            np.array([[0.7, 0.3, 0.0]]),
            np.array([1.0]),
            "buy_and_hold",
        )
        np.testing.assert_allclose(targets, [[0.7, 0.0, 0.3]])

    def test_recycle_preserves_staying_positions_and_uses_released_capital(self):
        targets = build_target_amounts(
            np.array([[True, False, True]]),
            np.array([[0.7, 0.3, 0.0]]),
            np.array([1.0]),
            "recycle",
        )
        np.testing.assert_allclose(targets, [[0.7, 0.0, 0.3]])

    def test_modes_are_vectorized_across_groups(self):
        targets = build_target_amounts(
            np.array([
                [True, True, False],
                [False, True, True],
            ]),
            np.array([
                [0.8, 0.2, 0.0],
                [0.0, 0.4, 0.6],
            ]),
            np.array([1.0, 1.0]),
            "buy_and_hold",
        )
        np.testing.assert_allclose(targets, [
            [0.8, 0.2, 0.0],
            [0.0, 0.4, 0.6],
        ])


if __name__ == "__main__":
    unittest.main()
