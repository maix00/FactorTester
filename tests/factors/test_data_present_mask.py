from __future__ import annotations

from pathlib import Path

import pandas as pd

from tools.data.types import DataColumn
from tools.data.types import DataFreq
from tools.factors.FactorExpr import ColumnRef, EvaluateContext
from tools.factors.FactorRunResult import FactorRunResult
from tools.products.Product import Product
from tests._repo import repo_root


def _product(alias: str) -> Product:
    return Product(name=alias, _local_only=True)


def _raw_index(times: list[str]) -> pd.MultiIndex:
    timestamps = pd.to_datetime(times)
    return pd.MultiIndex.from_arrays(
        [timestamps.normalize(), timestamps],
        names=["交易日", "数据源时间"],
    )


def test_column_ref_records_raw_product_presence_once():
    first = _product("MASK_FIRST")
    second = _product("MASK_SECOND")
    freq = DataFreq.MIN1
    first_index = _raw_index(["2026-05-25 09:00", "2026-05-25 09:01"])
    second_index = _raw_index(["2026-05-25 09:01"])
    run_result = FactorRunResult()

    ColumnRef(DataColumn.CLOSE)._evaluate(EvaluateContext(
        products=[first, second],
        freq=freq,
        preloaded={
            (first, freq.name): pd.DataFrame({"CLOSE": [1.0, 2.0]}, index=first_index),
            (second, freq.name): pd.DataFrame({"CLOSE": [3.0]}, index=second_index),
        },
        run_result=run_result,
    ))

    expected = pd.DataFrame(
        {first: [True, True], second: [False, True]},
        index=first_index,
        dtype=bool,
    )
    pd.testing.assert_frame_equal(run_result.data_present_mask, expected)
    assert run_result.data_present_all is False
    assert isinstance(run_result.data_present_mask.index, pd.MultiIndex)
    assert run_result.data_present_mask.index.names == ["交易日", "数据源时间"]

    ColumnRef(DataColumn.VOLUME)._evaluate(EvaluateContext(
        products=[first, second],
        freq=freq,
        preloaded={
            (first, freq.name): pd.DataFrame({"VOLUME": [1.0]}, index=second_index),
            (second, freq.name): pd.DataFrame({"VOLUME": [2.0]}, index=second_index),
        },
        run_result=run_result,
    ))

    pd.testing.assert_frame_equal(run_result.data_present_mask, expected)


def test_ic_merge_publishes_intermediate_source_mask_for_group_use(monkeypatch):
    monkeypatch.chdir(repo_root(Path(__file__)))
    from server.modules.single_factor_test.ic import _ICComputeResult, _merge_ic_result

    product = _product("MASK_IC_FE")
    index = pd.to_datetime(["2026-05-25 09:00", "2026-05-25 09:01"])
    expected = pd.DataFrame({product: [True, False]}, index=index, dtype=bool)
    factor = object()
    stored = FactorRunResult()

    class _Tester:
        def _get_result(self, requested_factor):
            assert requested_factor is factor
            return stored

    _merge_ic_result(
        _ICComputeResult(),
        ("key", 0, "rank", "alias"),
        (
            [factor],
            pd.Series([0.1], dtype=float),
            pd.Series({"mean": 0.1}, dtype=float),
            pd.DataFrame({product: [0.01, 0.02]}, index=index),
            pd.DataFrame({product: [1.0, 2.0]}, index=index),
            expected,
        ),
        _Tester(),
        primary_ic_lag=0,
        primary_horizons={"alias": "key"},
    )

    pd.testing.assert_frame_equal(stored.data_present_mask, expected)
    assert stored.data_present_all is False


def test_ic_rank_panels_survive_real_result_merge_and_artifact_serialization():
    from server.modules.single_factor_test.ic import _ICComputeResult, _merge_ic_result
    from server.modules.single_factor_test.evaluation import factor_series_from_tester

    class _Factor:
        alias = "CAPTURED_RANK"
        freq = DataFreq.MIN1

        def evaluate(self, *_args, **_kwargs):
            raise AssertionError("artifact serialization must reuse computed panels")

    factor = _Factor()
    product = _product("CAPTURED_RANK_PRODUCT")
    index = pd.date_range("2026-05-25 09:00", periods=2, freq="min")
    stored = FactorRunResult()
    factor_rank = pd.DataFrame({product: [1.0, 1.0]}, index=index)
    return_rank = pd.DataFrame({product: [1.0, 1.0]}, index=index)
    stats = pd.Series({"mean": 0.1}, dtype=float)
    stats.attrs.update(factor_cs_rank=factor_rank, return_cs_rank=return_rank)

    class _Tester:
        start_date = end_date = None
        products = [product]
        results = {factor: stored}

        def _get_result(self, requested):
            assert requested is factor
            return stored

    tester = _Tester()
    _merge_ic_result(
        _ICComputeResult(), ("horizon", 0, "rank", factor.alias),
        ([factor], pd.Series([0.1, 0.2], index=index), stats,
         pd.DataFrame({product: [0.01, 0.02]}, index=index),
         pd.DataFrame({product: [10.0, 20.0]}, index=index), pd.DataFrame()),
        tester, primary_ic_lag=0, primary_horizons={factor.alias: "horizon"},
    )
    assert stored.factor_cs_rank is factor_rank
    assert stored.return_cs_rank is return_rank
    series = factor_series_from_tester(tester, [factor])["series"][0]
    assert series["values"] == [10.0, 20.0]
    assert series["returns"]["values"] == [0.01, 0.02]
    assert series["cs_rank"]["values"] == [1.0, 1.0]
    assert series["returns_cs_rank"]["values"] == [1.0, 1.0]
    stored.clear_caches()
    assert stored.factor_cs_rank.empty and stored.return_cs_rank.empty
