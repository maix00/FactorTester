from __future__ import annotations

import pandas as pd

from tools.data.providers.DataProviderProductTS import DataProviderProductTS


def test_path_has_rows_rejects_empty_parquet(tmp_path):
    path = tmp_path / "empty.parquet"
    pd.DataFrame().to_parquet(path)

    assert DataProviderProductTS._path_has_rows(str(path)) is False


def test_path_has_rows_accepts_non_empty_parquet(tmp_path):
    path = tmp_path / "prices.parquet"
    pd.DataFrame({"close": [1.0]}).to_parquet(path)

    assert DataProviderProductTS._path_has_rows(str(path)) is True
