from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from server.modules.single_factor_test.ic_diagnostics import period_diagnostics
from server.modules.single_factor_test.ic_response import build_ic_response
from server.modules.single_factor_test.ic import _ICComputeResult
from tools.data.types import DataFreq
from tools.factors.temporal_support import TemporalSupport
from tools.factors.tester_calc.single_factor_test.ic_diagnostics import (
    metric_semantics_catalog,
    summarize_ic_series,
)


def _support() -> TemporalSupport:
    return TemporalSupport.from_components(
        factor_input_support_seconds=0,
        signal_interval_seconds=60,
        label_horizon_seconds=120,
        holding_support_seconds=0,
        decay_support_seconds=0,
        factor_input_source="test",
        signal_interval_source="test",
        label_horizon_source="test",
        holding_support_source="test",
        decay_support_source="test",
    )


def test_ic_summary_has_explicit_semantics_and_strict_hac_status() -> None:
    series = pd.Series([0.2, -0.1, 0.3, 0.0], dtype=float)
    stats = summarize_ic_series(
        series,
        expected_sign=-1,
        expected_sign_source="factor_alias:$Rev",
        temporal_support=_support(),
    )

    assert stats["diagnostics_schema"] == "ic-diagnostics-v1"
    assert stats["n_signal_observations"] == 4
    assert stats["mean_ic"] == stats["mean"]
    assert stats["icir_signal"] == stats["IR"]
    assert stats["t_stat_iid"] == stats["t_stat"]
    assert stats["expected_sign"] == -1
    assert stats["direction_rate"] == 0.25
    assert stats["hac_status"] == "estimable"
    assert stats["hac_lag_source"] == "temporal_support_overlap"
    assert stats["ic_series_acf_half_life_signals"] == stats["half_life"]

    no_contract = summarize_ic_series(series)
    assert no_contract["hac_status"] == "not_estimable"
    assert no_contract["t_stat_hac"] is None
    assert no_contract["effective_n_capped"] is None


def test_metric_catalog_distinguishes_signal_rolling_and_period_units() -> None:
    catalog = {item["name"]: item for item in metric_semantics_catalog()}
    assert catalog["rolling_k_signals"]["scope"] == "rolling"
    assert catalog["period_estimability"]["scope"] == "period"
    assert catalog["t_stat_hac"]["scope"] == "signal-level"
    assert "(K-1)" in catalog["rolling_expected_endpoint_span_seconds"]["meaning"]


def test_period_diagnostics_uses_configured_period_and_separate_estimability() -> None:
    index = pd.date_range("2024-01-01 09:00", periods=4, freq="30min")
    result = period_diagnostics(
        pd.Series([0.1, 0.2, -0.1, 0.0], index=index),
        factor=SimpleNamespace(freq=DataFreq.MIN30),
        support=_support(),
        expected_sign=1,
        expected_sign_source="factor_alias:raw",
        requested_periods=[{
            "label": "hour",
            "rule": "hour",
            "min_signal_observations": 2,
            "min_periods": 1,
        }],
    )
    hour = result["periods"]["hour"]
    assert hour["period_estimability_status"] == "estimable"
    assert hour["n_periods_estimable"] == 2
    assert all(item["period_estimable"] for item in hour["periods"])


def test_server_response_exposes_rolling_signal_count_and_two_span_conventions() -> None:
    factor = SimpleNamespace(
        name="F1",
        alias="F1",
        freq=DataFreq.MIN1,
    )
    support = _support()
    series = pd.Series(
        [0.1, 0.2, -0.1, 0.0],
        index=pd.date_range("2024-01-01 09:00", periods=4, freq="min"),
    )
    stats = pd.Series(summarize_ic_series(series, temporal_support=support))
    stats["temporal_support"] = support.to_dict()
    stats["temporal_support_status"] = support.support_status

    compute = _ICComputeResult()
    compute.factor_by_column[factor.alias] = factor
    compute.series_by_column_lag[factor.alias] = {0: series}
    compute.stats_by_column_lag[factor.alias] = {0: stats}
    compute.series_by_column_horizon_lag[factor.alias] = {"MIN1": {0: series}}
    compute.stats_by_column_horizon_lag[factor.alias] = {"MIN1": {0: stats}}
    compute.temporal_support_by_column_lag[factor.alias] = {0: support.to_dict()}

    response = build_ic_response(
        SimpleNamespace(factors=[], discard_result=lambda _factor: None),
        [factor.alias], [], compute, "paths", [0], 0, None, 3,
    )
    output = response["factors"][0]
    rolling = output["rolling_ic"]
    assert response["ic_diagnostics_schema"] == "ic-diagnostics-v1"
    assert rolling["rolling_k_signals"] == [3, 3]
    assert rolling["expected_endpoint_span_seconds"] == [120, 120]
    assert rolling["expected_coverage_span_seconds"] == [180, 180]
    assert len(rolling["t_stat_hac"]) == 2
    assert output["period_diagnostics"]["schema"] == "ic-period-diagnostics-v1"
