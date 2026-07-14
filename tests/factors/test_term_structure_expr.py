from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.FactorExpr import CLOSE, ColumnRef, EvaluateContext, term_ratio, term_slope, term_spread
from tools.products.AdjustableTermStructure import (
    AdjustableProductMixin,
    TERM_CONTRACT_COL,
    TERM_CONTRACT_UID_COL,
    TERM_DAYS_TO_MATURITY_COL,
    TERM_PRODUCT_COL,
    TERM_RANK_COL,
    TERM_TRADING_DAY_COL,
)
from tools.testers.backtest.engines.factors.incremental import UnsupportedStreamingFactor


class _MemoryTermStore:
    def __init__(self, rows: pd.DataFrame) -> None:
        self._rows = rows.copy()

    def load(
        self,
        product: str | None = None,
        trading_day: Any | None = None,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        rows = self._rows
        if product is not None:
            rows = rows[rows[TERM_PRODUCT_COL] == product]
        if trading_day is not None:
            day = pd.Timestamp(trading_day).normalize()
            rows = rows[rows[TERM_TRADING_DAY_COL] == day]
        if columns is not None:
            rows = rows[columns]
        return rows.copy()


@dataclass(eq=False)
class _FakeTermProduct(AdjustableProductMixin):
    name: str
    _market_data: pd.DataFrame
    _store: _MemoryTermStore

    def get_some_data(self, freq: DataFreq, copy: bool = False) -> pd.DataFrame:
        return self._market_data.copy() if copy else self._market_data

    def get_term_structure_store(self, curve_variant: str = "listed_contracts") -> _MemoryTermStore:
        return self._store


def _raw_index(times: Iterable[str]) -> pd.MultiIndex:
    timestamps = pd.to_datetime(list(times))
    return pd.MultiIndex.from_arrays(
        [timestamps.normalize(), timestamps],
        names=["交易日", "数据源时间"],
    )


def _term_rows(
    product: str,
    curves: Iterable[tuple[str, list[float], list[int]]] | None = None,
) -> pd.DataFrame:
    curves = curves or [
        ("2024-01-02", [100.0, 95.0, 90.0], [10, 40, 70]),
        ("2024-01-03", [110.0, 100.0, 80.0], [9, 39, 69]),
    ]
    rows = []
    for day, prices, days_to_maturity in curves:
        for rank, (price, maturity_days) in enumerate(zip(prices, days_to_maturity, strict=True)):
            rows.append({
                TERM_PRODUCT_COL: product,
                TERM_TRADING_DAY_COL: pd.Timestamp(day),
                TERM_CONTRACT_UID_COL: f"{product}{rank}",
                TERM_CONTRACT_COL: f"{product}{rank}",
                TERM_DAYS_TO_MATURITY_COL: maturity_days,
                TERM_RANK_COL: rank,
                DataColumn.CLOSE.name: price,
            })
    return pd.DataFrame(rows)


def _fake_product(
    product: str = "TERM_FAKE",
    curves: Iterable[tuple[str, list[float], list[int]]] | None = None,
) -> _FakeTermProduct:
    index = _raw_index([
        "2024-01-02 09:00",
        "2024-01-02 10:00",
        "2024-01-03 09:00",
    ])
    market_data = pd.DataFrame({DataColumn.CLOSE.name: [1.0, 2.0, 3.0]}, index=index)
    return _FakeTermProduct(product, market_data, _MemoryTermStore(_term_rows(product, curves)))


def test_term_structure_ops_batch_evaluate_against_hand_calculated_curve_values() -> None:
    product = _fake_product()
    ctx = EvaluateContext(products=[product], freq=DataFreq.MIN1, cache={})

    spread = term_spread(0, 2, DataColumn.CLOSE).evaluate(ctx=ctx)
    ratio = term_ratio(0, 1, DataColumn.CLOSE).evaluate(ctx=ctx)
    slope = term_slope(3, DataColumn.CLOSE).evaluate(ctx=ctx)

    expected_index = product._market_data.index
    pd.testing.assert_frame_equal(
        spread,
        pd.DataFrame({product: [10.0, 10.0, 30.0]}, index=expected_index),
    )
    pd.testing.assert_frame_equal(
        ratio,
        pd.DataFrame({product: [100.0 / 95.0 - 1.0, 100.0 / 95.0 - 1.0, 0.1]}, index=expected_index),
    )
    expected_slopes = [
        np.polyfit([10.0, 40.0, 70.0], [100.0, 95.0, 90.0], 1)[0],
        np.polyfit([10.0, 40.0, 70.0], [100.0, 95.0, 90.0], 1)[0],
        np.polyfit([9.0, 39.0, 69.0], [110.0, 100.0, 80.0], 1)[0],
    ]
    pd.testing.assert_frame_equal(
        slope,
        pd.DataFrame({product: expected_slopes}, index=expected_index),
    )


@pytest.mark.parametrize(
    "column",
    [
        CLOSE,
        ColumnRef(DataColumn.CLOSE_ADJUSTED),
        DataColumn.CLOSE_ADJUSTED,
    ],
)
def test_term_structure_adjusted_price_columns_use_raw_curve_prices(column) -> None:
    product = _fake_product()
    ctx = EvaluateContext(products=[product], freq=DataFreq.MIN1, cache={})

    ratio = term_ratio(0, 1, column).evaluate(ctx=ctx)
    slope = term_slope(3, column).evaluate(ctx=ctx)

    expected_index = product._market_data.index
    pd.testing.assert_frame_equal(
        ratio,
        pd.DataFrame({product: [100.0 / 95.0 - 1.0, 100.0 / 95.0 - 1.0, 0.1]}, index=expected_index),
    )
    expected_slopes = [
        np.polyfit([10.0, 40.0, 70.0], [100.0, 95.0, 90.0], 1)[0],
        np.polyfit([10.0, 40.0, 70.0], [100.0, 95.0, 90.0], 1)[0],
        np.polyfit([9.0, 39.0, 69.0], [110.0, 100.0, 80.0], 1)[0],
    ]
    pd.testing.assert_frame_equal(
        slope,
        pd.DataFrame({product: expected_slopes}, index=expected_index),
    )


def test_term_structure_column_ref_describe_and_evaluate_minimal_path() -> None:
    product = _fake_product()
    ctx = EvaluateContext(products=[product], freq=DataFreq.MIN1, cache={})
    expr = term_ratio(0, 1, CLOSE)

    assert "TermRatio" in expr.to_latex()
    assert expr._get_alias() == "term_ratio_CA_0_1"
    result = expr.evaluate(ctx=ctx)

    pd.testing.assert_frame_equal(
        result,
        pd.DataFrame(
            {product: [100.0 / 95.0 - 1.0, 100.0 / 95.0 - 1.0, 0.1]},
            index=product._market_data.index,
        ),
    )


def test_term_structure_column_ref_output_feeds_cross_sectional_ops_with_multiindex() -> None:
    near_flat = _fake_product(
        "TERM_FLAT",
        curves=[
            ("2024-01-02", [100.0, 95.0, 90.0], [10, 40, 70]),
            ("2024-01-03", [110.0, 100.0, 80.0], [9, 39, 69]),
        ],
    )
    near_steep = _fake_product(
        "TERM_STEEP",
        curves=[
            ("2024-01-02", [120.0, 90.0, 70.0], [10, 40, 70]),
            ("2024-01-03", [130.0, 90.0, 65.0], [9, 39, 69]),
        ],
    )
    ctx = EvaluateContext(products=[near_flat, near_steep], freq=DataFreq.MIN1, cache={})

    zscore = term_ratio(0, 1, CLOSE).cs_zscore().evaluate(ctx=ctx)
    rank = term_ratio(0, 1, CLOSE).cs_rank().evaluate(ctx=ctx)

    expected_index = near_flat._market_data.index
    assert isinstance(zscore.index, pd.MultiIndex)
    assert zscore.index.names == expected_index.names
    assert rank.index.names == expected_index.names
    assert list(zscore.columns) == [near_flat, near_steep]
    pd.testing.assert_series_equal(rank[near_flat], pd.Series([0.0, 0.0, 0.0], index=expected_index, name=near_flat))
    pd.testing.assert_series_equal(rank[near_steep], pd.Series([0.5, 0.5, 0.5], index=expected_index, name=near_steep))
    assert zscore.notna().all().all()


def test_term_structure_ops_are_not_declared_live_incremental_until_streaming_curve_support_exists() -> None:
    expr = term_spread(0, 1, DataColumn.CLOSE)

    assert not expr.supports_incremental()
    with pytest.raises(UnsupportedStreamingFactor, match="TermStructureOp does not support incremental execution"):
        expr.compile_incremental(factor_alias="term_spread", products=(_fake_product(),))
