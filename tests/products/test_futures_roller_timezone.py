from __future__ import annotations

import pandas as pd

from tools.products.Futures import Futures


def test_get_contract_row_from_trading_day_accepts_tz_aware_intraday_timestamp():
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

    row = future.get_contract_row_from_trading_day(pd.Timestamp("2024-06-15 09:31:00+08:00"))

    assert row is not None
    assert str(row["CONTRACT_UID"]) == "CFE|F|IF|2407"


def test_get_contract_row_from_trading_day_uses_day_boundary_not_intraday_time():
    future = Futures("IF.CFE", _local_only=True)
    future.roller_info = pd.DataFrame(
        [
            {
                "PRODUCT": "IF.CFE",
                "CONTRACT_UID": "CFE|F|IF|2406",
                "CONTRACT": "IF2406.CFE",
                "STARTDATE": pd.Timestamp("2024-06-01"),
                "ENDDATE": pd.Timestamp("2024-06-14"),
            }
        ]
    )
    future._ensure_roller_info = lambda: None  # type: ignore[method-assign]

    row = future.get_contract_row_from_trading_day("2024-06-14 14:59:00")

    assert row is not None
    assert str(row["CONTRACT_UID"]) == "CFE|F|IF|2406"
