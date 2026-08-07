from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.modules.single_factor_test.ic_rolling import (
    ROLLING_DETAIL_MAX_OBSERVATIONS,
    _rolling_rows,
    build_rolling_window_payload,
    rolling_stability_summary,
)
from server.modules.single_factor_test.ic_rolling_fast import (
    fast_rolling_metrics,
    fast_rolling_metrics_many,
)
from server.modules.single_factor_test.ic_rolling_params import RollingWindowSpec
from tools.factors.temporal_support import TemporalSupport


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


def _resolution(k: int) -> dict[str, object]:
    return {
        "mode": "signals",
        "value": k,
        "label": f"K={k}",
        "key": f"signals:K={k}",
        "resolved_k_signals": k,
        "signal_interval_seconds": 60,
        "expected_endpoint_span_seconds": (k - 1) * 60,
        "expected_coverage_span_seconds": k * 60,
    }


def test_fast_rolling_metrics_matches_full_endpoint_summary() -> None:
    series = pd.Series(
        np.random.default_rng(42).normal(size=100),
        index=pd.date_range("2024-01-01", periods=100, freq="min"),
    )
    resolution = _resolution(20)
    fast = fast_rolling_metrics(
        series, expected_sign=1, support=_support(), resolution=resolution,
    )
    rows, full_rows = _rolling_rows(
        series,
        expected_sign=1,
        expected_sign_source="test",
        support_payload=_support().to_dict(),
        resolution=resolution,
        metric_selection=None,
    )
    del rows
    full = rolling_stability_summary(
        full_rows, expected_sign=1, resolution=resolution,
    )
    for field in (
        "rolling_mean_ic_p10", "rolling_mean_ic_p50", "rolling_mean_ic_p90",
        "rolling_icir_p50", "rolling_t_stat_hac_p50",
        "rolling_effective_n_ratio_p50",
        "rolling_hac_ci_excludes_zero_expected_direction_rate",
        "rolling_actual_endpoint_span_seconds_median",
        "rolling_actual_over_expected_span_median",
        "rolling_std_ic_p50", "rolling_mad_ic_p50",
        "rolling_iqr_ic_p50", "rolling_q90_q10_ic_p50",
        "rolling_median_abs_ic_p50", "rolling_p90_abs_ic_p50",
        "rolling_mean_abs_delta_ic_p50",
        "rolling_mean_abs_second_delta_ic_p50",
        "rolling_zero_crossing_rate_p50", "rolling_path_max_drawdown_p50",
        "rolling_path_drawdown_duration_p50", "rolling_scale_instability_rcv",
    ):
        assert fast[field] == pytest.approx(full[field], abs=1e-6)
    assert fast["rolling_windows_count"] == full["rolling_windows_count"] == 81


def test_long_rolling_series_keeps_exact_summary_without_endpoint_rows() -> None:
    series = pd.Series(
        np.random.default_rng(7).normal(size=ROLLING_DETAIL_MAX_OBSERVATIONS + 1),
        index=pd.date_range(
            "2024-01-01", periods=ROLLING_DETAIL_MAX_OBSERVATIONS + 1, freq="min",
        ),
    )
    payload = build_rolling_window_payload(
        series,
        expected_sign=1,
        expected_sign_source="test",
        support_payload=_support().to_dict(),
        fallback_signal_interval_seconds=60,
        spec=RollingWindowSpec("signals", 20, "K=20"),
        metric_selection=None,
    )
    assert payload["rolling_detail_status"] == "summary_only"
    assert payload["rolling_detail_row_count"] == 0
    assert payload["rows"] == []
    assert payload["rolling_windows_count"] == ROLLING_DETAIL_MAX_OBSERVATIONS - 18
    assert payload["summary"]["rolling_detail_status"] == "summary_only"


def test_many_window_hac_scan_matches_individual_windows() -> None:
    series = pd.Series(
        np.random.default_rng(19).normal(size=120),
        index=pd.date_range("2024-01-01", periods=120, freq="min"),
    )
    resolutions = [_resolution(k) for k in (20, 60, 100)]
    combined = fast_rolling_metrics_many(
        series,
        expected_sign=-1,
        support=_support(),
        resolutions=resolutions,
    )
    for resolution in resolutions:
        individual = fast_rolling_metrics(
            series,
            expected_sign=-1,
            support=_support(),
            resolution=resolution,
        )
        actual = combined[resolution["key"]]
        for field in (
            "rolling_mean_ic_p50",
            "rolling_icir_p50",
            "rolling_t_stat_hac_p50",
            "rolling_effective_n_ratio_p50",
            "rolling_actual_over_expected_span_median",
            "rolling_q90_q10_ic_p50",
            "rolling_zero_crossing_rate_p50",
            "rolling_path_max_drawdown_p50",
            "rolling_scale_instability_rcv",
        ):
            assert actual[field] == pytest.approx(individual[field], abs=1e-10)


def test_shape_diagnostics_capture_amplitude_roughness_and_path() -> None:
    series = pd.Series(
        [1.0, -1.0, 1.0, -1.0, 1.0, -1.0],
        index=pd.date_range("2024-01-01", periods=6, freq="min"),
    )
    result = fast_rolling_metrics(
        series, expected_sign=1, support=_support(), resolution=_resolution(4),
    )

    assert result["rolling_std_ic_p50"] == pytest.approx(2.0 / np.sqrt(3))
    assert result["rolling_mad_ic_p50"] == pytest.approx(1.0)
    assert result["rolling_iqr_ic_p50"] == pytest.approx(2.0)
    assert result["rolling_q90_q10_ic_p50"] == pytest.approx(2.0)
    assert result["rolling_median_abs_ic_p50"] == pytest.approx(1.0)
    assert result["rolling_p90_abs_ic_p50"] == pytest.approx(1.0)
    assert result["rolling_mean_abs_delta_ic_p50"] == pytest.approx(2.0)
    assert result["rolling_mean_abs_second_delta_ic_p50"] == pytest.approx(4.0)
    assert result["rolling_zero_crossing_rate_p50"] == pytest.approx(1.0)
    assert result["rolling_path_max_drawdown_p50"] == pytest.approx(1.0)
    assert result["rolling_path_drawdown_duration_p50"] == pytest.approx(1.0)
    assert result["rolling_scale_instability_rcv"] == pytest.approx(0.0)


def test_detail_payload_publishes_shape_series_and_summary() -> None:
    series = pd.Series(
        np.random.default_rng(11).normal(size=12),
        index=pd.date_range("2024-01-01", periods=12, freq="min"),
    )
    payload = build_rolling_window_payload(
        series,
        expected_sign=1,
        expected_sign_source="test",
        support_payload=_support().to_dict(),
        fallback_signal_interval_seconds=60,
        spec=RollingWindowSpec("signals", 4, "K=4"),
        metric_selection=None,
    )

    assert len(payload["iqr_ic"]) == payload["rolling_windows_count"]
    assert len(payload["path_max_drawdown"]) == payload["rolling_windows_count"]
    assert payload["summary"]["rolling_iqr_ic_p50"] is not None
    assert payload["summary"]["rolling_scale_instability_rcv"] is not None
