from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import (
    CANDIDATE,
    CLOSE,
    CURRENT,
    ColumnRef,
    ConstExpr,
    CrossSectionalOp,
    EvaluateContext,
    RollingOp,
    SignalAlign,
    bar_since,
    scope_bars,
    scope_session,
    scope_trading_day,
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
from tools.factors.expr.timeline import build_panel_timeline
from tools.parameters import WindowParam
from tools.products.AdjustableTermStructure import (
    TERM_CONTRACT_COL,
    TERM_CONTRACT_UID_COL,
    TERM_DAYS_TO_MATURITY_COL,
    TERM_PRODUCT_COL,
    TERM_RANK_COL,
    TERM_TRADING_DAY_COL,
    AdjustableProductMixin,
)
from tools.products.categories.Category import Category
from tools.testers.backtest.engines.factors.incremental import (
    UnsupportedStreamingFactor,
)


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


def test_incremental_nested_signal_align_holds_last_formed_value():
    expr = SignalAlign(CLOSE, "2m") + CLOSE
    executor = expr.compile_incremental(
        factor_alias="nested_signal_hold",
        products=("P1",),
        source_freq=DataFreq.MIN1,
    )

    observed = []
    for minute, close in enumerate([1.0, 2.0, 3.0, 4.0], start=1):
        timestamp = pd.Timestamp(f"2024-01-01 09:0{minute}:00")
        executor.on_bar(timestamp, {"P1": {"CLOSE_ADJUSTED": close}})
        observed.append(executor.on_signal(timestamp)["P1"])

    np.testing.assert_allclose(
        observed,
        [np.nan, 4.0, 5.0, 8.0],
        equal_nan=True,
    )


def test_incremental_nested_signal_align_resets_cadence_at_session_gap():
    expr = SignalAlign(
        CLOSE,
        "2m",
        end_session_skip=True,
        end_session_gap=pd.Timedelta("3h"),
    )
    executor = expr.compile_incremental(
        factor_alias="session_signal_hold",
        products=("P1",),
        source_freq=DataFreq.MIN1,
    )

    observed = []
    for timestamp, close in zip(
        pd.to_datetime([
            "2024-01-01 09:01", "2024-01-01 09:02", "2024-01-01 09:03",
            "2024-01-01 21:01", "2024-01-01 21:02",
        ]),
        [1.0, 2.0, 3.0, 4.0, 5.0],
        strict=True,
    ):
        executor.on_bar(timestamp, {"P1": {"CLOSE_ADJUSTED": close}})
        observed.append(executor.on_signal(timestamp)["P1"])

    np.testing.assert_allclose(
        observed,
        [np.nan, 2.0, 2.0, 2.0, 5.0],
        equal_nan=True,
    )


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
            panel_timeline=build_panel_timeline(products, DataFreq.MIN1, preloaded),
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


def test_incremental_nested_signal_align_matches_batch_hold_semantics():
    products, rows = _panel()
    close = ColumnRef(DataColumn.CLOSE)
    expr = SignalAlign(close, "2m") + close

    batch = _batch_eval(expr, products, rows)
    live = _live_eval(expr, products, rows)

    pd.testing.assert_frame_equal(
        live,
        batch.reindex(index=live.index, columns=live.columns),
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_incremental_multilevel_signal_align_matches_batch_semantics():
    products = ("P1",)
    index = pd.date_range("2024-01-01 09:01", periods=12, freq="min")
    rows = pd.DataFrame(
        {("P1", DataColumn.CLOSE.name): np.arange(1.0, 13.0)},
        index=index,
    )
    rows.columns = pd.MultiIndex.from_tuples(rows.columns)
    close = ColumnRef(DataColumn.CLOSE)
    inner = SignalAlign(close.rolling(2).mean(), "2m")
    middle = SignalAlign(inner + close, "3m")
    expr = SignalAlign(middle * 2.0, "4m") + close

    batch = _batch_eval(expr, products, rows)
    live = _live_eval(expr, products, rows)

    pd.testing.assert_frame_equal(
        live,
        batch.reindex(index=live.index, columns=live.columns),
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_incremental_shared_nested_signal_advances_cadence_once_per_bar():
    aligned = SignalAlign(CLOSE, "2m")
    expr = aligned + aligned
    executor = expr.compile_incremental(
        factor_alias="shared_nested_signal",
        products=("P1",),
        source_freq=DataFreq.MIN1,
    )

    observed = []
    for minute, close in enumerate([1.0, 2.0, 3.0, 4.0], start=1):
        timestamp = pd.Timestamp(f"2024-01-01 09:0{minute}:00")
        executor.on_bar(timestamp, {"P1": {"CLOSE_ADJUSTED": close}})
        observed.append(executor.on_signal(timestamp)["P1"])

    np.testing.assert_allclose(
        observed,
        [np.nan, 4.0, 4.0, 8.0],
        equal_nan=True,
    )


def test_incremental_shared_stateful_child_advances_once_across_signal_layers():
    shifted = ColumnRef(DataColumn.CLOSE).shift(1)
    expr = SignalAlign(shifted, "2m") + SignalAlign(shifted, "3m")
    executor = expr.compile_incremental(
        factor_alias="shared_stateful_child",
        products=("P1",),
        source_freq=DataFreq.MIN1,
    )

    observed = []
    for minute, close in enumerate(np.arange(1.0, 9.0), start=1):
        timestamp = pd.Timestamp(f"2024-01-01 09:0{minute}:00")
        executor.on_bar(timestamp, {"P1": {"CLOSE": close}})
        observed.append(executor.on_signal(timestamp)["P1"])

    np.testing.assert_allclose(
        observed,
        [np.nan, np.nan, 3.0, 5.0, 5.0, 10.0, 10.0, 12.0],
        equal_nan=True,
    )


def test_incremental_bar_since_matches_batch_fixed_scope():
    products, rows = _panel()
    close = ColumnRef(DataColumn.CLOSE)
    expr = bar_since(close > 16.0, scope=scope_bars(3), default=3)

    batch = _batch_eval(expr, products, rows)
    live = _live_eval(expr, products, rows)

    pd.testing.assert_frame_equal(live, batch, check_exact=False)


def test_incremental_bar_distance_matches_batch_dynamic_predicate():
    products, rows = _panel()
    close = ColumnRef(DataColumn.CLOSE)
    expr = close.bar_distance(
        (CURRENT - CANDIDATE).abs() >= 2.0,
        scope=scope_bars(3),
        default=3,
    )

    batch = _batch_eval(expr, products, rows)
    live = _live_eval(expr, products, rows)

    pd.testing.assert_frame_equal(live, batch, check_exact=False)


def test_incremental_bar_distance_condition_embedding_signal_align_compiles_and_runs():
    # A nested-factor reference inside a bar-distance condition compiles to a
    # SignalAlign operand.  The streaming match predicate must compile it as a
    # whole SignalHoldNode (formed signal carried forward onto the outer bar
    # timeline) instead of treating SIGNAL_ALIGN as a pointwise op, which
    # raised "unsupported pointwise op" per bar during compilation.
    products, rows = _panel()
    close = ColumnRef(DataColumn.CLOSE)
    expr = close.bar_distance(
        SignalAlign(close.shift(1), "1m") > CURRENT,
        scope=scope_bars(3),
        default=3,
    )

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
        observed.append(executor.on_signal(timestamp))

    assert len(observed) == len(rows)
    assert set(observed[-1]) == set(products)
    # Batch evaluation of the same expression succeeds and stays on the same
    # default when nothing matches (P1 rises monotonically).
    batch = _batch_eval(expr, products, rows)
    assert set(batch.columns) == set(products)
    assert batch["P1"].tolist() == [3.0, 3.0, 3.0, 3.0, 3.0]


def test_incremental_bar_distance_farthest_matches_batch():
    products, rows = _panel()
    close = ColumnRef(DataColumn.CLOSE)
    expr = close.bar_distance(
        CANDIDATE != CURRENT,
        scope=scope_bars(4),
        select="farthest",
        default=4,
    )

    batch = _batch_eval(expr, products, rows)
    live = _live_eval(expr, products, rows)

    pd.testing.assert_frame_equal(live, batch, check_exact=False)


def test_incremental_bar_distance_default_tracks_trading_day_scope_length():
    close = ColumnRef(DataColumn.CLOSE)
    executor = close.bar_distance(
        CANDIDATE < CURRENT,
        scope=scope_trading_day(),
    ).compile_incremental(
        factor_alias="day_distance", products=("P1",), source_freq=DataFreq.MIN1,
    )
    rows = [
        ("2026-01-01 09:01", "2026-01-01"),
        ("2026-01-01 09:02", "2026-01-01"),
        ("2026-01-01 21:01", "2026-01-02"),
        ("2026-01-01 21:02", "2026-01-02"),
    ]

    observed = []
    for timestamp, day in rows:
        executor.on_bar(timestamp, {"P1": {"CLOSE": 1.0}}, trading_day=day)
        observed.append(executor.on_signal(timestamp)["P1"])

    np.testing.assert_allclose(observed, [0, 1, 0, 1])


def test_incremental_bar_distance_resolves_duration_scope_from_source_frequency():
    maximum = WindowParam("K", default_value="3m")
    expr = ColumnRef(DataColumn.CLOSE).bar_distance(
        CANDIDATE < CURRENT,
        scope=scope_bars(maximum),
    ).resolve(param_values={"K": pd.Timedelta("3m")})
    executor = expr.compile_incremental(
        factor_alias="duration_scope", products=("P1",), source_freq=DataFreq.MIN1,
    )

    observed = []
    for minute in range(1, 6):
        timestamp = f"2026-01-01 09:0{minute}"
        executor.on_bar(timestamp, {"P1": {"CLOSE": 1.0}})
        observed.append(executor.on_signal(timestamp)["P1"])

    np.testing.assert_allclose(observed, [0, 1, 2, 3, 3])


def test_incremental_bar_search_scopes_reset_at_session_and_trading_day():
    condition = ColumnRef(DataColumn.CLOSE) > 1.5
    session_executor = bar_since(
        condition, scope=scope_session(), default=9,
    ).compile_incremental(
        factor_alias="session_bar_since", products=("P1",), source_freq=DataFreq.MIN1,
    )
    day_executor = bar_since(
        condition, scope=scope_trading_day(), default=9,
    ).compile_incremental(
        factor_alias="day_bar_since", products=("P1",), source_freq=DataFreq.MIN1,
    )
    rows = [
        ("2026-01-01 09:01", "2026-01-01", 2.0),
        ("2026-01-01 09:02", "2026-01-01", 1.0),
        ("2026-01-01 21:01", "2026-01-02", 1.0),
    ]
    session_values = []
    day_values = []
    for timestamp, trading_day_value, close in rows:
        fields = {"P1": {"CLOSE": close}}
        session_executor.on_bar(timestamp, fields, trading_day=trading_day_value)
        day_executor.on_bar(timestamp, fields, trading_day=trading_day_value)
        session_values.append(session_executor.on_signal(timestamp)["P1"])
        day_values.append(day_executor.on_signal(timestamp)["P1"])

    np.testing.assert_allclose(session_values, [0, 1, 9])
    np.testing.assert_allclose(day_values, [0, 1, 9])


def test_incremental_bar_distance_reports_fixed_scope_lookback_contract():
    close = ColumnRef(DataColumn.CLOSE)
    executor = close.bar_distance(
        CANDIDATE < CURRENT,
        scope=scope_bars(4),
        default=4,
    ).compile_incremental(
        factor_alias="bar_distance_lookback",
        products=("P1",),
        source_freq=DataFreq.MIN1,
    )

    contract = executor._plan.lookback_contract
    assert contract.warmup == 4
    assert contract.max_window == 4


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
    "expr",
    [
        ColumnRef(DataColumn.CLOSE).rolling_std(3),
        ColumnRef(DataColumn.CLOSE).rolling_var(3),
        ColumnRef(DataColumn.CLOSE).rolling_min(3),
        ColumnRef(DataColumn.CLOSE).rolling_max(3),
        ColumnRef(DataColumn.CLOSE).rolling_sum(3),
        ColumnRef(DataColumn.CLOSE).rolling_skew(3),
        ColumnRef(DataColumn.CLOSE).rolling_argmax(3),
        RollingOp("rolling_argmin_raw", ConstExpr(3), ColumnRef(DataColumn.CLOSE)),
    ],
)
def test_incremental_numpy_rolling_kernels_match_batch(expr):
    products, rows = _panel()

    batch = _batch_eval(expr, products, rows)
    live = _live_eval(expr, products, rows)

    pd.testing.assert_frame_equal(
        live,
        batch.reindex(index=live.index, columns=live.columns),
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_incremental_nested_composite_lookbacks_match_batch_at_every_timestamp():
    products, rows = _panel()
    expr = (
        (
            ColumnRef(DataColumn.CLOSE).rolling_mean(3)
            - ColumnRef(DataColumn.OPEN).rolling_ema(2)
        ).rolling_mean(2)
        + ColumnRef(DataColumn.CLOSE).shift(1)
    )

    batch = _batch_eval(expr, products, rows)
    live = _live_eval(expr, products, rows)

    pd.testing.assert_frame_equal(
        live,
        batch.reindex(index=live.index, columns=live.columns),
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )
    plan = expr.compile_incremental(
        factor_alias="nested",
        products=products,
        source_freq=DataFreq.MIN1,
    )
    assert plan._plan.lookback_contract.warmup == 5
    assert plan._plan.lookback_contract.max_window == 3
    assert plan._plan.lookback_contract.serial_depth == 2


def test_incremental_ewm_constant_state_matches_batch_with_missing_values():
    products = ("P1", "P2")
    index = pd.date_range("2024-01-01 09:00", periods=12, freq="min")
    rows = pd.DataFrame(
        {
            ("P1", DataColumn.CLOSE.name): [1.0, 2.0, np.nan, 4.0, 5.0, np.nan, 7.0, 8.0, 9.0, np.nan, 11.0, 12.0],
            ("P2", DataColumn.CLOSE.name): [np.nan, 2.0, 3.0, np.nan, 5.0, 6.0, np.nan, 8.0, 9.0, 10.0, np.nan, 12.0],
        },
        index=index,
    )
    rows.columns = pd.MultiIndex.from_tuples(rows.columns)
    expr = ColumnRef(DataColumn.CLOSE).rolling_ema(4)

    batch = _batch_eval(expr, products, rows)
    live = _live_eval(expr, products, rows)

    pd.testing.assert_frame_equal(
        live,
        batch.reindex(index=live.index, columns=live.columns),
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_incremental_ewm_keeps_last_value_after_a_long_missing_run():
    products = ("P1",)
    values = [1.0, 2.0, *([np.nan] * 2100), *np.arange(4.0, 104.0)]
    index = pd.date_range("2024-01-01 09:00", periods=len(values), freq="min")
    rows = pd.DataFrame({("P1", DataColumn.CLOSE.name): values}, index=index)
    rows.columns = pd.MultiIndex.from_tuples(rows.columns)
    expr = ColumnRef(DataColumn.CLOSE).rolling_ema(4)

    batch = _batch_eval(expr, products, rows)
    live = _live_eval(expr, products, rows)

    pd.testing.assert_frame_equal(
        live,
        batch.reindex(index=live.index, columns=live.columns),
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


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
