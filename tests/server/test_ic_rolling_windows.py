from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from server.jobs.report_outputs.builders import build_report_artifacts
from server.jobs.scheduling.result_projection import persisted_result_summary
from server.modules.single_factor_test.ic_rolling import (
    build_factor_rolling_ic,
    normalize_rolling_window_specs,
)
from tools.data.types import DataFreq
from tools.factors.temporal_support import TemporalSupport


def _support(interval_seconds: float = 60.0) -> TemporalSupport:
    return TemporalSupport.from_components(
        factor_input_support_seconds=0,
        signal_interval_seconds=interval_seconds,
        label_horizon_seconds=120,
        holding_support_seconds=0,
        decay_support_seconds=0,
        factor_input_source="test",
        signal_interval_source="test",
        label_horizon_source="test",
        holding_support_source="test",
        decay_support_source="test",
    )


def _series() -> pd.Series:
    return pd.Series(
        [0.10, 0.15, 0.05, 0.20, 0.25, 0.12, 0.18, 0.22],
        index=pd.date_range("2024-01-01 09:00", periods=8, freq="min"),
    )


def test_window_contract_supports_multiple_signal_counts_only() -> None:
    specs = normalize_rolling_window_specs({
        "rolling_windows": {
            "signal_counts": [3, 5],
        },
    })

    assert [item.mode for item in specs] == ["signals", "signals"]
    assert [item.label for item in specs] == ["K=3", "K=5"]


def test_clock_duration_is_rejected_instead_of_being_converted() -> None:
    import pytest

    with pytest.raises(ValueError, match="duration"):
        normalize_rolling_window_specs({
            "rolling_windows": {"durations": ["1h"]},
        })
    with pytest.raises(ValueError, match="clock_duration"):
        normalize_rolling_window_specs({"rolling_windows": ["1h"]})


def test_signal_count_resolves_without_one_global_n() -> None:
    factor = SimpleNamespace(alias="F|$F:MIN1", freq=DataFreq.MIN1)
    support = _support()
    series = _series()
    result = build_factor_rolling_ic(
        factor=factor,
        series_by_horizon_lag={
            "MIN1": {0: series, 1: series},
            "MIN5": {0: series, 1: series},
        },
        support_by_horizon_lag={
            "MIN1": {0: support.to_dict(), 1: support.to_dict()},
            "MIN5": {0: support.to_dict(), 1: support.to_dict()},
        },
        primary_horizon="MIN1",
        primary_lag=0,
        window_specs=normalize_rolling_window_specs({
            "rolling_windows": [3, 5],
        }),
        metric_selection=None,
    )

    assert result is not None
    assert set(result["by_forward_horizon"]) == {"MIN1", "MIN5"}
    assert set(result["by_forward_horizon"]["MIN1"]["0"]) == {
        "signals:K=3", "signals:K=5",
    }
    assert len(result["stability_summary"]) == 8  # 2 horizons × 2 delays × 2 windows
    signal_row = next(
        row for row in result["stability_summary"]
        if row["window_key"] == "signals:K=5"
    )
    assert signal_row["resolved_k_signals"] == 5
    assert signal_row["rolling_window_unit"] == "signal_count"
    assert signal_row["requested_signal_count"] == 5


def test_stability_table_is_independent_and_projection_keeps_summary_rows() -> None:
    summary = {
        "success": True,
        "rolling_ic_schema": "ic-rolling-v3",
        "rolling_window_specs": [{"mode": "signals", "value": 3, "label": "K=3"}],
        "factors": [{
            "factor_alias": "F|$F:MIN1",
            "factor_ref": "factor:v1:F",
            "ic_method": "rank",
            "rolling_ic_stability": [{
                "forward_return_horizon": "MIN1",
                "entry_delay_bars": 0,
                "window_key": "signals:K=3",
                "rolling_windows_count": 6,
                "rolling_mean_ic_p50": 0.1,
            }],
        }],
    }
    projected = persisted_result_summary(summary)
    assert projected["rolling_ic_schema"] == "ic-rolling-v3"
    assert projected["factors"][0]["rolling_ic_stability"][0]["rolling_mean_ic_p50"] == 0.1

    artifacts = build_report_artifacts(summary, requested=["ic_statistics"])
    names = {item.name for item in artifacts}
    assert {"ic_rolling_stability_csv", "ic_rolling_stability_data"} <= names
