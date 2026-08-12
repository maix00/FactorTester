from __future__ import annotations

import pandas as pd
import pyarrow.parquet as parquet

from sources.LocalCNFutures.parquet_layout import (
    MINUTE_ROW_GROUP_SIZE,
    write_minute_parquet,
)


def test_minute_parquet_writer_creates_prunable_row_groups(tmp_path):
    rows = MINUTE_ROW_GROUP_SIZE * 2 + 1
    expected = pd.DataFrame(
        {
            "trade_time": pd.date_range("2024-01-02 09:01", periods=rows, freq="1min"),
            "close_price": range(rows),
        }
    )
    path = tmp_path / "minute.parquet"

    write_minute_parquet(expected, path)

    metadata = parquet.ParquetFile(path).metadata
    assert metadata.num_row_groups == 3
    assert all(
        metadata.row_group(index).num_rows <= MINUTE_ROW_GROUP_SIZE
        for index in range(metadata.num_row_groups)
    )
    pd.testing.assert_frame_equal(pd.read_parquet(path), expected)
    assert not (tmp_path / ".minute.parquet.tmp").exists()
