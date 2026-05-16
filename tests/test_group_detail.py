import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from tools.factors.tests.single_factor_test.group.detail import build_group_detail


class TestGroupDetail(unittest.TestCase):
    def test_products_include_display_desc(self):
        product = SimpleNamespace(name="IF.CFE", desc="沪深300指数期货")
        detail = build_group_detail(
            0,
            {0: {pd.Timestamp("2026-01-01"): [product]}},
            np.array([[0.01]]),
            [pd.Timestamp("2026-01-01")],
        )

        self.assertEqual(detail["entry_frequency"][0]["product"], {
            "name": "IF.CFE",
            "desc": "沪深300指数期货",
        })
        self.assertEqual(detail["top_periods"][0]["products"][0], {
            "name": "IF.CFE",
            "desc": "沪深300指数期货",
        })
        self.assertEqual(detail["return_series"][0]["return"], 0.01)
        self.assertAlmostEqual(detail["return_series"][0]["cumulative_return"], 1.01)

    def test_detects_profit_concentration_in_positive_runs(self):
        returns = np.array([[0.10], [0.10], [-0.05], [-0.05], [-0.05]])
        index = list(pd.date_range("2026-01-01", periods=5, freq="D"))
        detail = build_group_detail(0, {0: {}}, returns, index)
        analysis = detail["positive_run_analysis"]

        self.assertEqual(analysis["run_count"], 1)
        self.assertAlmostEqual(analysis["top1_positive_contribution_ratio"], 1.0)
        self.assertLess(analysis["return_without_top1_run"], 0)
        self.assertTrue(analysis["is_concentrated"])

    def test_builds_intraday_contribution_summary(self):
        index = [
            pd.Timestamp("2026-01-01 09:00"),
            pd.Timestamp("2026-01-02 09:00"),
            pd.Timestamp("2026-01-01 14:55"),
            pd.Timestamp("2026-01-01 22:55"),
        ]
        detail = build_group_detail(
            0,
            {0: {}},
            np.array([[0.01], [0.02], [-0.01], [0.03]]),
            index,
        )
        analysis = detail["intraday_analysis"]

        self.assertEqual(analysis["top_times"][0]["sum"], 0.03)
        self.assertEqual({row["time"] for row in analysis["top_times"][:2]}, {"09:00", "22:55"})


if __name__ == "__main__":
    unittest.main()
