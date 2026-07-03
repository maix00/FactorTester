from __future__ import annotations

import pandas as pd
import pytest

from tools.testers.backtest.modules.risk_metrics import compute_metrics


def test_max_drawdown_known_series():
    equity = pd.Series([100.0, 120.0, 90.0, 110.0])
    returns = equity.pct_change().dropna()
    metrics = compute_metrics(equity, returns)
    # peak 120 -> trough 90 -> drawdown = 90/120 - 1 = -0.25
    assert metrics["max_drawdown"] == pytest.approx(-0.25)


def test_win_rate_known_series():
    equity = pd.Series([100.0, 110.0, 105.0, 115.0, 110.0])
    returns = equity.pct_change().dropna()  # +0.1, -0.0455, +0.0952, -0.0435 -> 2 wins of 4
    metrics = compute_metrics(equity, returns)
    assert metrics["win_rate"] == pytest.approx(0.5)


def test_sharpe_ratio_zero_std_degrades_to_zero_not_div_by_zero_error():
    equity = pd.Series([100.0, 110.0, 120.0])  # equity value itself is unused for this branch
    returns = pd.Series([0.1, 0.1, 0.1])  # identical returns -> std == 0 exactly
    metrics = compute_metrics(equity, returns)
    assert metrics["sharpe_ratio"] == 0.0


def test_sharpe_ratio_nonzero_volatility():
    equity = pd.Series([100.0, 110.0, 95.0, 115.0])
    returns = equity.pct_change().dropna()
    metrics = compute_metrics(equity, returns)
    assert metrics["sharpe_ratio"] == pytest.approx(returns.mean() / returns.std())


def test_empty_returns_degrades_to_zeros_not_error():
    equity = pd.Series([100.0])
    returns = pd.Series(dtype=float)
    metrics = compute_metrics(equity, returns)
    assert metrics["annual_return"] == 0.0
    assert metrics["sharpe_ratio"] == 0.0
    assert metrics["max_drawdown"] == 0.0
    assert metrics["win_rate"] == 0.0


def test_sortino_only_penalizes_downside_volatility():
    equity = pd.Series([100.0, 110.0, 100.0, 130.0, 115.0])
    returns = equity.pct_change().dropna()  # two negative returns -> real (non-NaN) downside std
    metrics = compute_metrics(equity, returns)
    downside = returns[returns < 0]
    assert len(downside) >= 2
    expected = returns.mean() / downside.std()
    assert metrics["sortino_ratio"] == pytest.approx(expected)


def test_sortino_single_downside_observation_degrades_to_zero_not_nan():
    equity = pd.Series([100.0, 110.0, 105.0])  # exactly one negative return -> sample std undefined (NaN)
    returns = equity.pct_change().dropna()
    assert (returns < 0).sum() == 1
    metrics = compute_metrics(equity, returns)
    assert metrics["sortino_ratio"] == 0.0
