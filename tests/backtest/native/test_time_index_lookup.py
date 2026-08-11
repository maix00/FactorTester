from __future__ import annotations

import pandas as pd

from tools.testers.backtest.modules.time_index_lookup import TableRowLocator


def test_table_row_locator_value_at_matches_row_without_materializing_row():
    index = pd.date_range("2024-01-01", periods=3, freq="min")
    table = pd.DataFrame({"P1": [10.0, 11.0, 12.0]}, index=index)
    locator = TableRowLocator.for_table(table)

    assert locator.value_at(table, index[1], "P1", asof=False) == 11.0
    assert locator.row_at(table, index[1], asof=False)["P1"] == 11.0


def test_table_row_locator_value_at_keeps_asof_semantics():
    index = pd.date_range("2024-01-01", periods=3, freq="min")
    table = pd.DataFrame({"P1": [10.0, 11.0, 12.0]}, index=index)
    locator = TableRowLocator.for_table(table)

    assert locator.value_at(
        table, index[1] + pd.Timedelta(seconds=30), "P1", asof=True,
    ) == 11.0


def test_table_row_locator_row_values_at_matches_series_values_and_asof():
    index = pd.date_range("2024-01-01", periods=3, freq="min")
    table = pd.DataFrame({"P1": [10.0, 11.0, 12.0], "P2": [2.0, 3.0, 4.0]}, index=index)
    locator = TableRowLocator.for_table(table)

    exact = locator.row_values_at(table, index[1], asof=False)
    asof = locator.row_values_at(
        table, index[1] + pd.Timedelta(seconds=30), asof=True,
    )

    assert exact.tolist() == [11.0, 3.0]
    assert asof.tolist() == exact.tolist()
