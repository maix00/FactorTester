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


if __name__ == "__main__":
    unittest.main()
