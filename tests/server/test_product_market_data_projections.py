from __future__ import annotations

import pandas as pd

from server.modules.shared.price_data_helpers import open_interest_column
from server.services.product_market_data.products import _price_rows
from tools.data.types import DataFreq


def test_open_interest_column_accepts_canonical_and_provider_aliases() -> None:
    assert open_interest_column(["OPEN", "OPEN_INTEREST", "CLOSE"]) == "OPEN_INTEREST"
    assert open_interest_column(["open_price", "open_interest", "close_price"]) == "open_interest"
    assert open_interest_column(["open", "OI", "close"]) == "OI"
    assert open_interest_column(["open", "hold", "close"]) == "hold"
    assert open_interest_column(["open", "close"]) is None


def test_product_price_rows_keeps_open_interest_from_provider_alias() -> None:
    frame = pd.DataFrame(
        {
            "OPEN": [10.0, 11.0],
            "HIGH": [12.0, 13.0],
            "LOW": [9.0, 10.0],
            "CLOSE": [11.0, 12.0],
            "VOLUME": [100, 120],
            "OI": [80, 90],
        },
        index=pd.date_range("2025-01-02", periods=2, freq="D"),
    )

    rows, has_open_interest = _price_rows(
        object(), frame, adjusted=False, frequency=DataFreq.DAY1,
    )

    assert has_open_interest is True
    assert [row["open_interest"] for row in rows] == [80.0, 90.0]
