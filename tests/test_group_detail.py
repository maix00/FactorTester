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

    def test_builds_daily_and_period_robustness(self):
        index = list(pd.to_datetime([
            "2026-01-01 09:00",
            "2026-01-01 09:05",
            "2026-01-02 09:00",
            "2026-01-03 09:00",
        ]))
        detail = build_group_detail(
            0,
            {0: {}},
            np.array([[0.10], [0.10], [-0.05], [-0.05]]),
            index,
        )
        daily = detail["daily_analysis"]
        robust = detail["period_robustness"]

        self.assertEqual(daily["top_days"][0]["date"], "2026-01-01")
        self.assertLess(daily["return_without_top1_day"], 0)
        self.assertLess(robust["without_top5pct"]["remaining_return"], 0.2)
        self.assertTrue(detail["robustness_summary"]["is_fragile"])

    def test_builds_product_gross_contribution_from_cached_matrix(self):
        products = [
            SimpleNamespace(name="CF.CZC", desc="一号棉花"),
            SimpleNamespace(name="CY.CZC", desc="棉纱"),
        ]
        detail = build_group_detail(
            0,
            {0: {}},
            np.array([[0.01], [0.02]]),
            list(pd.date_range("2026-01-01", periods=2, freq="D")),
            product_gross_contrib_np=np.array([[[0.03, -0.02]], [[0.02, 0.00]]]),
            valid_cols=products,
        )
        analysis = detail["product_analysis"]

        self.assertEqual(analysis["top_products"][0]["product"]["name"], "CF.CZC")
        self.assertAlmostEqual(analysis["top_products"][0]["gross_contribution"], 0.05)
        self.assertTrue(analysis["is_concentrated"])


if __name__ == "__main__":
    unittest.main()
