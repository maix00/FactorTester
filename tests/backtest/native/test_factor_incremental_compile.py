from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataColumn
from tools.data.types import DataFreq
from tools.factors.expr import (
    CLOSE,
    ColumnRef,
    ConstExpr,
    CrossSectionalOp,
    EvaluateContext,
    RollingOp,
    term_carry_annualized,
    term_contango,
    term_curvature,
    term_log_ratio,
    term_rank_value,
    term_ratio,
    term_slope,
    term_slope_segment,
    term_spread,
)
from tools.products.categories.Category import Category
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


def test_factor_expr_compile_incremental_returns_run_scoped_executor():
    expr = ColumnRef(DataColumn.CLOSE) + 1.0

    executor = expr.compile_incremental(
        factor_alias="close_plus_one",
        products=("P1",),
    )

    executor.on_bar("2024-01-01", {"P1": {"CLOSE": 10.0}})
    assert executor.on_signal("2024-01-01") == {"P1": 11.0}

    executor.on_bar("2024-01-02", {"P1": {"CLOSE": 12.0}})
    assert executor.on_signal("2024-01-02") == {"P1": 13.0}


def test_incremental_factor_supports_category_boolean_mask_leaf():
    sector = Category.from_members(
        alias="IncrementalCategory",
        type=str,
        labels={"eligible": ["P1"]},
    )
    expr = CLOSE.cs_rank(mask=sector["eligible"])

    executor = expr.compile_incremental(
        factor_alias="category_masked_rank",
        products=("P1", "P2"),
    )
    executor.on_bar("2024-01-01", {
        "P1": {"CLOSE_ADJUSTED": 10.0},
        "P2": {"CLOSE_ADJUSTED": 30.0},
    })

    result = executor.on_signal("2024-01-01")
    assert result["P1"] == 0.5
    assert np.isnan(result["P2"])


def test_factor_expr_incremental_executor_ignores_extra_snapshot_products():
    expr = ColumnRef(DataColumn.CLOSE) + 1.0
    executor = expr.compile_incremental(
        factor_alias="close_plus_one",
        products=("P1",),
    )

    executor.on_bar("2024-01-01", {
        "P1": {"CLOSE": 10.0},
        "CONTRACT_EXTRA": {"CLOSE": 99.0},
    })

    assert executor.on_signal("2024-01-01") == {"P1": 11.0}


def test_factor_expr_incremental_executor_rejects_missing_planned_products():
    expr = ColumnRef(DataColumn.CLOSE) + 1.0
    executor = expr.compile_incremental(
        factor_alias="close_plus_one",
        products=("P1",),
    )

    with pytest.raises(ValueError, match="missing streaming products"):
        executor.on_bar("2024-01-01", {"CONTRACT_EXTRA": {"CLOSE": 99.0}})


def test_vectorizable_factor_expr_defaults_to_incremental_capable():
    expr = ColumnRef(DataColumn.CLOSE) + 1.0

    assert expr.supports_vectorized()
    assert expr.supports_incremental()


def _panel() -> tuple[tuple[str, ...], pd.DataFrame]:
    products = ("P1", "P2", "P3")
    index = pd.date_range("2024-01-01 09:00", periods=5, freq="min")
    rows = pd.DataFrame(
        {
            ("P1", DataColumn.CLOSE.name): [10.0, 11.0, 12.0, 13.0, 14.0],
            ("P2", DataColumn.CLOSE.name): [20.0, 18.0, 16.0, 14.0, 12.0],
            ("P3", DataColumn.CLOSE.name): [30.0, 30.0, 31.0, 32.0, 35.0],
            ("P1", DataColumn.OPEN.name): [9.0, 10.0, 10.0, 11.0, 13.0],
            ("P2", DataColumn.OPEN.name): [19.0, 17.0, 17.0, 13.0, 11.0],
            ("P3", DataColumn.OPEN.name): [29.0, 29.0, 30.0, 33.0, 36.0],
        },
        index=index,
    )
    rows.columns = pd.MultiIndex.from_tuples(rows.columns)
    return products, rows


def _batch_eval(expr, products: tuple[str, ...], rows: pd.DataFrame) -> pd.DataFrame:
    preloaded = {
        (product, DataFreq.MIN1.name): rows[product]
        for product in products
    }
    return expr.evaluate(
        ctx=EvaluateContext(
            products=products,
            freq=DataFreq.MIN1,
            cache={},
            preloaded=preloaded,
        )
    )


def _live_eval(expr, products: tuple[str, ...], rows: pd.DataFrame) -> pd.DataFrame:
    executor = expr.compile_incremental(
        factor_alias="factor",
        products=products,
        source_freq=DataFreq.MIN1,
    )
    observed = []
    for timestamp, row in rows.iterrows():
        fields = {
            product: {
                column: row[(product, column)]
                for column in rows[product].columns
            }
            for product in products
        }
        executor.on_bar(timestamp, fields)
        observed.append(pd.Series(executor.on_signal(timestamp), name=timestamp))
    return pd.DataFrame(observed, index=rows.index)[list(products)]


class _MemoryTermStore:
    def __init__(self, rows: pd.DataFrame) -> None:
        self._rows = rows.copy()

    def load(self, product=None, trading_day=None, columns=None):
        rows = self._rows
        if product is not None:
            rows = rows[rows[TERM_PRODUCT_COL] == product]
        if trading_day is not None:
            rows = rows[rows[TERM_TRADING_DAY_COL] == pd.Timestamp(trading_day).normalize()]
        if columns is not None:
            rows = rows[columns]
        return rows.copy()

    def contract_pool(self, product, trading_day, depth=None):
        rows = self.load(product=product, trading_day=trading_day)
        if rows.empty:
            return rows
        rows = rows.sort_values(TERM_RANK_COL)
        return rows.head(int(depth)) if depth is not None else rows


class _TermProduct(AdjustableProductMixin):
    def __init__(self, name: str, index: pd.Index, curves: dict[str, list[float]]) -> None:
        self.name = name
        self._market_data = pd.DataFrame({DataColumn.CLOSE.name: np.arange(len(index), dtype=float)}, index=index)
        rows = []
        for day, prices in curves.items():
            for rank, price in enumerate(prices):
                rows.append({
                    TERM_PRODUCT_COL: name,
                    TERM_TRADING_DAY_COL: pd.Timestamp(day),
                    TERM_CONTRACT_UID_COL: f"{name}{rank}",
                    TERM_CONTRACT_COL: f"{name}{rank}",
                    TERM_DAYS_TO_MATURITY_COL: [10, 40, 70][rank],
                    TERM_RANK_COL: rank,
                    DataColumn.CLOSE.name: price,
                })
        self._store = _MemoryTermStore(pd.DataFrame(rows))

    def __repr__(self) -> str:
        return self.name

    def get_some_data(self, freq: DataFreq, copy: bool = False) -> pd.DataFrame:
        return self._market_data.copy() if copy else self._market_data

    def get_term_structure_store(self, curve_variant: str = "listed_contracts") -> _MemoryTermStore:
        return self._store


def _term_products() -> tuple[tuple[_TermProduct, ...], pd.DatetimeIndex]:
    index = pd.DatetimeIndex([
        pd.Timestamp("2024-01-02 09:00"),
        pd.Timestamp("2024-01-02 10:00"),
        pd.Timestamp("2024-01-03 09:00"),
    ])
    return (
        _TermProduct("TERM_FLAT", index, {
            "2024-01-02": [100.0, 95.0, 90.0],
            "2024-01-03": [110.0, 100.0, 80.0],
        }),
        _TermProduct("TERM_STEEP", index, {
            "2024-01-02": [120.0, 90.0, 70.0],
            "2024-01-03": [130.0, 90.0, 65.0],
        }),
    ), index


def _live_term_eval(expr, products: tuple[_TermProduct, ...], index: pd.Index) -> pd.DataFrame:
    executor = expr.compile_incremental(factor_alias="term", products=products, source_freq=DataFreq.MIN1)
    observed = []
    for timestamp in index:
        fields = {product: {DataColumn.CLOSE.name: 1.0} for product in products}
        curves = {
            product: product.get_term_structure(pd.Timestamp(timestamp).normalize())
            for product in products
        }
        executor.on_bar(timestamp, fields, curves)
        observed.append(pd.Series(executor.on_signal(timestamp), name=timestamp))
    return pd.DataFrame(observed, index=index)[list(products)]


@pytest.mark.parametrize(
    "expr",
    [
        ColumnRef(DataColumn.CLOSE),
        (ColumnRef(DataColumn.CLOSE) - ColumnRef(DataColumn.OPEN)) / ColumnRef(DataColumn.OPEN),
        ColumnRef(DataColumn.CLOSE).shift(2),
        ColumnRef(DataColumn.CLOSE).rolling_mean(3),
        ColumnRef(DataColumn.CLOSE).rolling_ema(3),
        ColumnRef(DataColumn.CLOSE).rolling_corr(ColumnRef(DataColumn.OPEN), 3),
        RollingOp("rolling_cov", ConstExpr(3), ColumnRef(DataColumn.CLOSE), ColumnRef(DataColumn.OPEN)),
        ColumnRef(DataColumn.CLOSE).cs_rank(),
        ColumnRef(DataColumn.CLOSE).cs_rank(
            mask=ColumnRef(DataColumn.OPEN) > ConstExpr(15.0),
        ),
        ColumnRef(DataColumn.CLOSE).cs_zscore(),
        ColumnRef(DataColumn.CLOSE).cs_ordinal_rank(
            mask=ColumnRef(DataColumn.OPEN) > ConstExpr(15.0),
            ascending=False,
        ),
        ColumnRef(DataColumn.CLOSE).tanh(),
        ColumnRef(DataColumn.CLOSE).where(
            ColumnRef(DataColumn.CLOSE) > ConstExpr(15.0),
            other=np.nan,
        ),
    ],
)
def test_incremental_factor_replay_matches_batch_evaluate_for_product_shaped_ops(expr):
    products, rows = _panel()

    batch = _batch_eval(expr, products, rows)
    live = _live_eval(expr, products, rows)

    pd.testing.assert_frame_equal(live, batch.reindex(index=live.index, columns=live.columns))


@pytest.mark.parametrize(
    "expr, message",
    [
        (
            CrossSectionalOp("cs_corr", ColumnRef(DataColumn.CLOSE), ColumnRef(DataColumn.OPEN)),
            "product-level live signal values",
        ),
        (
            CrossSectionalOp("cs_spearman", ColumnRef(DataColumn.CLOSE), ColumnRef(DataColumn.OPEN)),
            "product-level live signal values",
        ),
        (
            ConstExpr([1.0, 2.0, 3.0]),
            "streaming constants must be scalar",
        ),
    ],
)
def test_incremental_factor_compile_rejects_non_product_shaped_or_non_scalar_nodes(expr, message):
    with pytest.raises(UnsupportedStreamingFactor, match=message):
        expr.compile_incremental(factor_alias="factor", products=("P1", "P2", "P3"))


@pytest.mark.parametrize(
    "expr",
    [
        term_spread(0, 2, DataColumn.CLOSE),
        term_ratio(0, 1, CLOSE),
        term_slope(3, CLOSE),
        term_ratio(0, 1, CLOSE).cs_rank(),
        term_log_ratio(0, 1, CLOSE),
        term_contango(0, 1, CLOSE),
        term_carry_annualized(0, 1, CLOSE),
        term_curvature(3, CLOSE),
        term_slope_segment(1, 2, CLOSE),
        term_rank_value(2, CLOSE),
    ],
)
def test_incremental_term_structure_replay_matches_batch_evaluate(expr):
    products, index = _term_products()
    batch = expr.evaluate(ctx=EvaluateContext(products=products, freq=DataFreq.MIN1, cache={}))
    live = _live_term_eval(expr, products, index)

    pd.testing.assert_frame_equal(live, batch.reindex(index=live.index, columns=live.columns))


def test_incremental_term_structure_requires_curve_snapshot():
    products, _ = _term_products()
    executor = term_ratio(0, 1, CLOSE).compile_incremental(
        factor_alias="term_ratio",
        products=products,
        source_freq=DataFreq.MIN1,
    )

    with pytest.raises(KeyError, match="TERM_STRUCTURE snapshot is missing curve"):
        executor.on_bar("2024-01-02 09:00", {product: {DataColumn.CLOSE.name: 1.0} for product in products})
