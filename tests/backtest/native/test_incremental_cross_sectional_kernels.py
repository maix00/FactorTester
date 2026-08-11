from __future__ import annotations

import numpy as np
import pandas as pd

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import ColumnRef, EvaluateContext
from tools.products.categories.Category import Category
from tools.testers.backtest.engines.factors.cross_sectional_kernels import (
    ordinal_rank,
    rank_percent,
    zscore,
)


def test_rank_percent_matches_pandas_ties_missing_and_infinity() -> None:
    values = np.array([np.inf, 2.0, 2.0, np.nan, -np.inf, 1.0])
    expected = (pd.Series(values).rank(pct=True) - 0.5).to_numpy()

    np.testing.assert_allclose(rank_percent(values), expected, equal_nan=True)


def test_masked_rank_percent_matches_pandas_boolean_mask() -> None:
    values = np.array([3.0, 1.0, 1.0, np.nan, 2.0])
    mask = np.array([True, False, True, np.nan, True])
    expected = (
        pd.Series(values)
        .where(pd.Series(mask).fillna(False).astype(bool))
        .rank(pct=True)
        .sub(0.5)
        .to_numpy()
    )

    eligible = ~np.isnan(mask) & mask.astype(bool)
    np.testing.assert_allclose(rank_percent(values, eligible), expected, equal_nan=True)


def test_ordinal_rank_matches_pandas_sorted_index_first_rank() -> None:
    keys = np.array(["z", "a", "m", "b", "q"])
    values = np.array([2.0, 2.0, 1.0, np.nan, 2.0])
    mask = np.array([True, True, True, True, False])
    order = np.argsort(keys, kind="mergesort")
    series = pd.Series(values, index=keys)
    eligible = series.where(pd.Series(mask, index=keys).fillna(False).astype(bool))

    for ascending in (True, False):
        expected = (
            eligible.sort_index()
            .rank(method="first", ascending=ascending, na_option="keep")
            .reindex(keys)
            .to_numpy()
        )
        actual = ordinal_rank(values, mask, order, ascending=ascending)
        np.testing.assert_allclose(actual, expected, equal_nan=True)


def test_zscore_matches_pandas_sample_standard_deviation() -> None:
    values = np.array([1.0, 4.0, np.nan, 8.0, 11.0])
    series = pd.Series(values)
    expected = ((series - series.mean()) / series.std()).to_numpy()

    np.testing.assert_allclose(zscore(values), expected, equal_nan=True)


def test_incremental_group_transforms_match_batch_values() -> None:
    products = ("P1", "P2", "P3", "P4")
    index = pd.date_range("2024-01-01 09:00", periods=3, freq="min")
    rows = pd.DataFrame(
        {
            (product, DataColumn.CLOSE.name): values
            for product, values in {
                "P1": [1.0, 4.0, 7.0],
                "P2": [3.0, 2.0, 8.0],
                "P3": [10.0, 9.0, 5.0],
                "P4": [12.0, 6.0, 6.0],
            }.items()
        },
        index=index,
    )
    rows[[(product, DataColumn.OPEN.name) for product in products]] = 1.0
    rows.loc[index[1], ("P2", DataColumn.OPEN.name)] = 0.0
    rows.columns = pd.MultiIndex.from_tuples(rows.columns)
    category = Category.from_members(
        alias="IncrementalGroupKernel",
        type=str,
        labels={"first": ["P1", "P2"], "second": ["P3", "P4"]},
    )
    close = ColumnRef(DataColumn.CLOSE)
    mask = ColumnRef(DataColumn.OPEN) > 0.0
    preloaded = {
        (product, DataFreq.MIN1.name): rows[product]
        for product in products
    }
    for method in ("cs_group_rank", "cs_group_zscore", "cs_group_demean"):
        expression = getattr(close, method)(category, mask=mask)
        batch = expression.evaluate(
            ctx=EvaluateContext(
                products=products,
                freq=DataFreq.MIN1,
                cache={},
                preloaded=preloaded,
            )
        )
        executor = expression.compile_incremental(
            factor_alias=f"group_{method}",
            products=products,
            source_freq=DataFreq.MIN1,
        )
        live_rows = []
        for timestamp, row in rows.iterrows():
            executor.on_bar(
                timestamp,
                {
                    product: {
                        DataColumn.CLOSE.name: row[(product, DataColumn.CLOSE.name)],
                        DataColumn.OPEN.name: row[(product, DataColumn.OPEN.name)],
                    }
                    for product in products
                },
            )
            live_rows.append(pd.Series(executor.on_signal(timestamp), name=timestamp))
        live = pd.DataFrame(live_rows, index=index)[list(products)]
        pd.testing.assert_frame_equal(live, batch.loc[:, list(products)])
