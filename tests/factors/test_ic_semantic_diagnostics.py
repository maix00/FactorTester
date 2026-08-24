from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from server.modules.single_factor_test.ic import _ICComputeResult
from server.modules.single_factor_test.ic_diagnostics import (
    _period_groups,
    _period_key,
    _period_keys,
    period_diagnostics,
)
from server.modules.single_factor_test.ic_response import (
    IC_SERIES_DETAIL_MAX_POINTS,
    IC_SERIES_DETAIL_MAX_TOTAL_POINTS,
    _forward_ic_half_life_exponential,
    _series_detail_budget,
    build_ic_response,
)
from tools.data.types import DataFreq
from tools.factors.temporal_support import TemporalSupport
from tools.factors.tester_calc.single_factor_test.ic_diagnostics import (
    _acf_half_life_diagnostic,
    filter_ic_metric_mapping,
    metric_semantics_catalog,
    normalize_ic_metric_selection,
    summarize_ic_series,
)
from tools.factors.tester_calc.single_factor_test.ic_half_life import (
    evaluate_forward_ic_decay_curve,
    fit_forward_ic_half_life,
    fit_ic_series_ar1_half_life,
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
    assert stats["hac_kernel"] == "bartlett"
    assert stats["hac_lag_formula"].startswith("ceil((factor_input")
    assert stats["std_ic_ddof"] == 1
    assert stats["se_iid"] == stats["std_ic"] / (stats["n_signal_observations"] ** 0.5)
    assert stats["ci95_hac_lower"] <= stats["mean_ic"] <= stats["ci95_hac_upper"]
    # The test support has factor_input=0, label=120s, signal=60s, hence
    # ceil(120/60)-1 = 1.  Recompute the Bartlett long-run variance directly.
    values = [0.2, -0.1, 0.3, 0.0]
    centered = [value - sum(values) / len(values) for value in values]
    gamma0 = sum(value * value for value in centered) / len(values)
    gamma1 = sum(centered[index] * centered[index - 1] for index in range(1, len(values))) / len(values)
    expected_lrv = gamma0 + gamma1
    assert stats["hac_lag"] == 1
    assert abs(stats["hac_lrv_to_iid_variance_ratio"] - expected_lrv / gamma0) < 1e-12
    assert stats["ic_series_acf_half_life_signals"] == stats["half_life"]

    no_contract = summarize_ic_series(series)
    assert no_contract["hac_status"] == "not_estimable"
    assert no_contract["t_stat_hac"] is None
    assert no_contract["effective_n_capped"] is None


def test_half_life_estimators_keep_predictive_decay_and_ic_persistence_distinct() -> None:
    predictive = fit_forward_ic_half_life([
        (60.0, "MIN1", 0.08),
        (180.0, "MIN3", 0.04),
        (300.0, "MIN5", 0.02),
    ], entry_delay_bars=0)
    assert predictive["status"] == "estimated"
    assert predictive["half_life_seconds"] == 120.0
    assert predictive["method"] == "log_linear_ols"
    assert predictive["baseline_horizon"] == "MIN1"
    assert predictive["baseline_seconds"] == 60.0
    assert predictive["expected_direction"] == 1
    assert predictive["n_invalid_oriented_points"] == 0
    assert predictive["last_horizon"] == "MIN5"
    assert predictive["log_fit_rmse"] < 1e-12
    curve = evaluate_forward_ic_decay_curve(
        predictive, minimum_seconds=60.0, maximum_seconds=300.0,
    )
    assert len(curve) == 201
    assert abs(curve[0]["oriented_mean_ic"] - 0.08) < 1e-12
    assert abs(curve[-1]["oriented_mean_ic"] - 0.02) < 1e-12

    persistence = fit_ic_series_ar1_half_life(
        [1.0, 0.8, 0.64, 0.512, 0.4096, 0.32768],
        signal_interval_seconds=60.0,
    )
    assert persistence["status"] == "estimated"
    assert abs(persistence["rho"] - 0.8) < 1e-12
    assert abs(persistence["half_life_signals"] - 3.1062837195053903) < 1e-9
    assert persistence["half_life_seconds"] is not None


def test_half_life_requires_positive_decay_curve() -> None:
    result = fit_forward_ic_half_life([
        (60.0, "MIN1", 0.04),
        (120.0, "MIN2", 0.02),
        (240.0, "MIN4", -0.01),
    ])
    assert result["status"] == "nonpositive_or_sign_reversal"
    assert result["n_invalid_oriented_points"] == 1
    assert result["first_invalid_horizon"] == "MIN4"
    assert result["selected_model"] == "crossing_only"
    assert result["sign_reversal"] is True
    assert result["more_horizons_recommended"] is True
    assert result["recommended_min_horizons"] == 12
    assert "重新运行 IC 测试" in result["recommendation"]
    assert result["smooth_reversal_model"] == "damped_oscillatory_exponential"


def test_acf_half_life_treats_exact_half_as_a_crossing() -> None:
    value, status = _acf_half_life_diagnostic([1.0, 0.5])
    assert value == 1.0
    assert status == "estimated"


def test_server_forward_half_life_exposes_continuous_estimate() -> None:
    stats = {
        "MIN1": {0: pd.Series({"mean_ic": 0.08})},
        "MIN3": {0: pd.Series({"mean_ic": 0.04})},
        "MIN5": {0: pd.Series({"mean_ic": 0.02})},
    }
    result = _forward_ic_half_life_exponential(stats, entry_delay_bars=0)
    assert result["status"] == "estimated"
    assert result["half_life_seconds"] == 120.0
    assert result["duration"] == "MIN2"


def test_metric_catalog_distinguishes_signal_rolling_and_period_units() -> None:
    catalog = {item["name"]: item for item in metric_semantics_catalog()}
    assert catalog["rolling_k_signals"]["scope"] == "rolling"
    assert catalog["period_estimability"]["scope"] == "period"
    assert catalog["t_stat_hac"]["scope"] == "signal-level"
    assert catalog["hac_lag_formula"]["scope"] == "signal-level"
    assert catalog["forward_ic_half_life_exponential"]["scope"] == "horizon-level"
    assert catalog["forward_ic_half_life_baseline_seconds"]["unit"] == "seconds"
    assert catalog["forward_ic_half_life_crossing_n_nonpositive_oriented_points"]["unit"] == "count"
    assert "(K-1)" in catalog["rolling_expected_endpoint_span_seconds"]["meaning"]


def test_ic_metric_selection_defaults_to_all_and_projects_groups() -> None:
    assert normalize_ic_metric_selection()["mode"] == "all"
    selection = normalize_ic_metric_selection({
        "include": ["core", "holding_half_life"],
        "exclude": ["median_ic"],
    })
    assert selection["mode"] == "selected"
    assert "mean_ic" in selection["resolved"]
    assert "median_ic" not in selection["resolved"]
    assert "forward_ic_half_life_exponential_seconds" in selection["resolved"]
    projected = filter_ic_metric_mapping(
        {
            "factor_alias": "F",
            "mean_ic": 0.1,
            "median_ic": 0.2,
            "forward_ic_half_life_exponential_seconds": 60.0,
            "t_stat_hac": 2.0,
        },
        selection,
        preserve={"factor_alias"},
    )
    assert projected == {
        "factor_alias": "F",
        "mean_ic": 0.1,
        "forward_ic_half_life_exponential_seconds": 60.0,
    }


def test_period_summary_can_skip_unused_full_persistence_fit() -> None:
    series = pd.Series([0.2, -0.1, 0.3, 0.0], dtype=float)
    stats = summarize_ic_series(
        series,
        expected_sign=1,
        temporal_support=_support(),
        include_persistence=False,
    )
    assert stats["ic_series_acf1"] is not None
    assert stats["ic_series_acf_half_life_status"] == "not_requested"
    assert stats["ic_series_ar1_method"] is None
    assert stats["acf_estimator"].startswith("direct_lag1")


def test_long_ic_response_budget_keeps_only_primary_series_detail() -> None:
    series = pd.Series(
        np.arange(IC_SERIES_DETAIL_MAX_POINTS + 1, dtype=float),
        index=pd.date_range("2024-01-01", periods=IC_SERIES_DETAIL_MAX_POINTS + 1, freq="min"),
    )
    horizon = {
        "MIN1": {0: series, 1: series},
        "MIN2": {0: series, 1: series},
    }
    budget = _series_detail_budget(horizon, {0: series, 1: series})
    assert budget["status"] == "primary_only"
    assert budget["candidate_max_points"] == IC_SERIES_DETAIL_MAX_POINTS + 1
    assert budget["candidate_total_points"] > IC_SERIES_DETAIL_MAX_TOTAL_POINTS


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


def test_vectorized_period_keys_match_scalar_period_contract() -> None:
    timestamps = pd.date_range(
        "2024-01-31 23:30", periods=8, freq="45min", tz="Asia/Shanghai",
    )
    for rule in ("hour", "day", "week", "month", "quarter"):
        vectorized = list(_period_keys(timestamps, rule))
        scalar = [_period_key(timestamp, rule) for timestamp in timestamps]
        assert vectorized == scalar


def test_period_groups_use_ordered_boundaries_and_keep_unsorted_fallback() -> None:
    timestamps = pd.date_range("2024-01-01 09:00", periods=5, freq="30min")
    keys = _period_keys(timestamps, "hour")
    ordered = _period_groups([0.1, 0.2, 0.3, 0.4, 0.5], keys)
    assert [start for start, _ in ordered] == [
        pd.Timestamp("2024-01-01 09:00"),
        pd.Timestamp("2024-01-01 10:00"),
        pd.Timestamp("2024-01-01 11:00"),
    ]
    assert [series.tolist() for _, series in ordered] == [
        [0.1, 0.2], [0.3, 0.4], [0.5],
    ]

    unsorted_keys = keys[[2, 0, 4, 1, 3]]
    fallback = _period_groups([0.1, 0.2, 0.3, 0.4, 0.5], unsorted_keys)
    assert [start for start, _ in fallback] == [
        pd.Timestamp("2024-01-01 09:00"),
        pd.Timestamp("2024-01-01 10:00"),
        pd.Timestamp("2024-01-01 11:00"),
    ]
    assert [series.tolist() for _, series in fallback] == [
        [0.2, 0.4], [0.1, 0.5], [0.3],
    ]


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


def test_server_response_projects_selected_ic_metrics_and_can_omit_half_life() -> None:
    factor = SimpleNamespace(name="F1", alias="F1", freq=DataFreq.MIN1)
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
        [factor.alias], [], compute, "paths", [0], 0, None, None,
        metric_selection={"include": ["core"]},
    )
    assert response["ic_metric_selection"]["mode"] == "selected"
    indices = {row["index"] for row in response["ic_stats"]["rows"]}
    assert "mean_ic" in indices
    assert "t_stat_hac" not in indices
    assert "forward_ic_half_life" not in response["factors"][0]


def test_server_response_keeps_quantile_portfolio_category_structured() -> None:
    factor = SimpleNamespace(name="F1", alias="F1", freq=DataFreq.MIN1)
    support = _support()
    index = pd.date_range("2024-01-01 09:00", periods=4, freq="min")
    series = pd.Series([0.1, 0.2, -0.1, 0.0], index=index)
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
        [factor.alias], [], compute, "paths", [0], 0, None, None,
        quantile_portfolio_config={"enabled": False},
    )
    category = response["factors"][0]["ic_statistics"]["quantile_portfolio_statistics"]
    assert category["schema_version"] == "quantile-portfolio-statistics-v1"
    assert category["status"] == "disabled"


def test_signal_screening_panel_projects_source_bars_to_daily_signal_without_repeating() -> None:
    from server.modules.single_factor_test.ic_response import _signal_screening_panel

    source_index = pd.MultiIndex.from_arrays(
        [
            pd.to_datetime([
                "2025-01-02", "2025-01-02", "2025-01-03", "2025-01-03",
            ]),
            pd.to_datetime([
                "2025-01-02 09:00", "2025-01-02 15:00",
                "2025-01-03 09:00", "2025-01-03 15:00",
            ]),
        ],
        names=["DAY1", "MIN1"],
    )
    source = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0]}, index=source_index)
    signal_index = pd.DatetimeIndex(pd.to_datetime(["2025-01-02", "2025-01-03"]))

    projected = _signal_screening_panel(source, signal_index)

    assert projected.index.equals(signal_index)
    assert projected["A"].tolist() == [2.0, 4.0]


def test_signal_screening_panel_deduplicates_repeated_signal_timestamps() -> None:
    from server.modules.single_factor_test.ic_response import _signal_screening_panel

    source_index = pd.MultiIndex.from_arrays(
        [
            pd.to_datetime([
                "2025-01-02", "2025-01-02", "2025-01-03", "2025-01-03",
            ]),
            pd.to_datetime([
                "2025-01-02 09:00", "2025-01-02 15:00",
                "2025-01-03 09:00", "2025-01-03 15:00",
            ]),
        ],
        names=["DAY1", "MIN1"],
    )
    source = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0]}, index=source_index)
    repeated_signal_index = pd.DatetimeIndex(pd.to_datetime([
        "2025-01-02", "2025-01-02", "2025-01-03", "2025-01-03",
    ]))

    projected = _signal_screening_panel(source, repeated_signal_index)

    assert projected.index.equals(pd.DatetimeIndex(pd.to_datetime([
        "2025-01-02", "2025-01-03",
    ])))
    assert projected["A"].tolist() == [2.0, 4.0]


def test_screening_signal_index_uses_one_trading_day_for_daily_factor() -> None:
    from server.modules.single_factor_test.ic import screening_signal_index

    source_index = pd.MultiIndex.from_arrays(
        [
            pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-03", "2025-01-03"]),
            pd.to_datetime([
                "2025-01-02 09:00", "2025-01-02 15:00",
                "2025-01-03 09:00", "2025-01-03 15:00",
            ]),
        ],
        names=["DAY1", "MIN1"],
    )
    factor = SimpleNamespace(freq=DataFreq.DAY1)
    series = pd.Series([1.0, 2.0, 3.0, 4.0], index=source_index)

    target = screening_signal_index(factor, series)

    assert target.equals(pd.DatetimeIndex(pd.to_datetime(["2025-01-02", "2025-01-03"])))


def test_server_response_keeps_quick_portfolio_statistics_by_horizon_and_delay() -> None:
    factor = SimpleNamespace(name="F1", alias="F1", freq=DataFreq.MIN1)
    support = _support()
    index = pd.date_range("2024-01-01 09:00", periods=4, freq="min")
    series = pd.Series([0.1, 0.2, -0.1, 0.0], index=index)
    stats = pd.Series(summarize_ic_series(series, temporal_support=support))
    stats["temporal_support"] = support.to_dict()
    stats["temporal_support_status"] = support.support_status
    compute = _ICComputeResult()
    compute.factor_by_column[factor.alias] = factor
    compute.series_by_column_lag[factor.alias] = {0: series}
    compute.stats_by_column_lag[factor.alias] = {0: stats}
    compute.series_by_column_horizon_lag[factor.alias] = {
        "MIN1": {0: series}, "MIN3": {0: series},
    }
    compute.stats_by_column_horizon_lag[factor.alias] = {
        "MIN1": {0: stats}, "MIN3": {0: stats},
    }
    compute.temporal_support_by_column_lag[factor.alias] = {0: support.to_dict()}
    compute.quantile_portfolio_statistics_by_column_horizon_lag[factor.alias] = {
        "MIN1": {0: {
            "schema_version": "quantile-portfolio-statistics-v1", "status": "computed",
            "modes": {"no_fee": {"groups": []}},
        }},
        "MIN3": {0: {
            "schema_version": "quantile-portfolio-statistics-v1", "status": "computed",
            "modes": {"no_fee": {"groups": []}},
        }},
    }
    response = build_ic_response(
        SimpleNamespace(factors=[], discard_result=lambda _factor: None),
        [factor.alias], [], compute, "paths", [0], 0, None, None,
        primary_horizons={"F1": "MIN1"},
        quantile_portfolio_config={"enabled": False},
    )
    category = response["factors"][0]["ic_statistics"]["quantile_portfolio_statistics"]
    assert set(category["by_forward_horizon"]) == {"MIN1", "MIN3"}
    assert category["by_forward_horizon"]["MIN3"]["0"]["status"] == "computed"
