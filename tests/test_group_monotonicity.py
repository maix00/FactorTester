import unittest

import numpy as np

from tools.factors.tests.single_factor_test.group.monotonicity import build_group_ranking_detail


class TestGroupRankingDetail(unittest.TestCase):
    def test_builds_ranking_summary_from_group_returns(self):
        detail = build_group_ranking_detail(np.array([
            [0.03, 0.02, 0.01],
            [0.04, 0.01, -0.01],
            [0.01, 0.02, 0.03],
        ]))

        self.assertEqual(detail["period_count"], 3)
        self.assertEqual(detail["comparable_period_count"], 3)
        self.assertAlmostEqual(detail["monotonic_period_ratio"], 1.0)
        self.assertAlmostEqual(detail["descending_period_ratio"], 2 / 3)
        self.assertAlmostEqual(detail["top_bottom"]["mean_spread"], 1 / 60)
        self.assertAlmostEqual(detail["top_bottom"]["positive_ratio"], 2 / 3)

    def test_ignores_incomplete_rows_for_comparable_metrics(self):
        detail = build_group_ranking_detail(np.array([
            [0.03, 0.02, np.nan],
            [0.02, 0.01, 0.00],
        ]))

        self.assertEqual(detail["period_count"], 2)
        self.assertEqual(detail["comparable_period_count"], 1)
        self.assertAlmostEqual(detail["mean_non_empty_group_count"], 2.5)
        self.assertAlmostEqual(detail["full_group_period_ratio"], 0.5)
        self.assertAlmostEqual(detail["top_bottom"]["mean_spread"], 0.02)


if __name__ == "__main__":
    unittest.main()
