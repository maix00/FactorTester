from __future__ import annotations

import numpy as np
import pandas as pd

from tools.factors.tests.single_factor_test.group.core import _expand_trade_products
from tools.products.Futures import Futures


def test_expand_trade_products_maps_main_future_by_roller_ranges():
    future = Futures("IF.CFE", _local_only=True)
    future.roller_info = pd.DataFrame(
        [
            {
                "PRODUCT": "IF.CFE",
                "CONTRACT_UID": "CFE|F|IF|2406",
                "CONTRACT": "IF2406.CFE",
                "STARTDATE": pd.Timestamp("2024-06-01"),
                "ENDDATE": pd.Timestamp("2024-06-14"),
            },
            {
                "PRODUCT": "IF.CFE",
                "CONTRACT_UID": "CFE|F|IF|2407",
                "CONTRACT": "IF2407.CFE",
                "STARTDATE": pd.Timestamp("2024-06-15"),
                "ENDDATE": pd.Timestamp("2024-06-28"),
            },
        ]
    )
    future._ensure_roller_info = lambda: None  # type: ignore[method-assign]

    signal_index = [
        pd.Timestamp("2024-06-14 09:31:00+08:00"),
        pd.Timestamp("2024-06-17 09:31:00+08:00"),
    ]
    membership = np.ones((2, 1, 1), dtype=bool)

    trade_products, expanded = _expand_trade_products([future], signal_index, membership)

    assert [p.name for p in trade_products] == ["CFE|F|IF|2406", "CFE|F|IF|2407"]
    assert expanded.shape == (2, 1, 2)
    assert expanded[0, 0, 0]
    assert not expanded[0, 0, 1]
    assert not expanded[1, 0, 0]
    assert expanded[1, 0, 1]
