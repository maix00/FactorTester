from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataColumn
from tools.data.types import DataFreq
from tools.factors.expr import ColumnRef, ConstExpr, CrossSectionalOp, EvaluateContext, RollingOp, WhereOp
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
        ColumnRef(DataColumn.CLOSE).cs_zscore(),
        WhereOp(
            "where",
            ColumnRef(DataColumn.CLOSE) > ConstExpr(15.0),
            ColumnRef(DataColumn.CLOSE),
            ConstExpr(np.nan),
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
