from __future__ import annotations

import pandas as pd
import pytest

from tools.analytics import (
    ResultMetric,
    compute_result_metrics,
    register_result_metric,
    registered_result_metrics,
    unregister_result_metric,
)


def test_default_result_metrics_are_registered() -> None:
    metrics = registered_result_metrics()

    assert "annual_return" in metrics
    assert metrics["annual_return"].label == "年化收益率"
    assert "max_drawdown" in metrics


def test_annual_return_uses_calendar_time_span() -> None:
    index = pd.to_datetime(["2024-01-01", "2025-01-01"])
    equity = pd.Series([100.0, 110.0], index=index)

    result = compute_result_metrics(equity, equity.pct_change().dropna())

    assert result["annual_return"] == pytest.approx(0.1, rel=0.01)


def test_result_metric_registry_accepts_custom_metric() -> None:
    key = "unit_test_metric"
    register_result_metric(
        ResultMetric(key, "测试指标", lambda ctx: float(len(ctx.equity)))
    )
    equity = pd.Series([1.0, 2.0], index=pd.date_range("2024-01-01", periods=2))

    try:
        result = compute_result_metrics(equity, equity.pct_change().dropna())
    finally:
        unregister_result_metric(key)

    assert result[key] == 2.0
