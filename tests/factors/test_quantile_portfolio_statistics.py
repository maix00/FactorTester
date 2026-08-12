from __future__ import annotations

import numpy as np
import pandas as pd

from tools.factors.tester_calc.single_factor_test.group.research_run.projection import (
    serialize_event_execution,
)
from tools.factors.tester_calc.single_factor_test.quantile_portfolio import (
    compare_quantile_portfolio_statistics,
    compute_quantile_portfolio_statistics,
    formal_group_statistics,
)


def _panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2024-01-01", periods=6, freq="D")
    columns = ["D", "C", "B", "A"]
    factor = pd.DataFrame(np.tile([1.0, 2.0, 3.0, 4.0], (6, 1)), index=index, columns=columns)
    forward = pd.DataFrame(np.tile([-0.02, -0.01, 0.02, 0.04], (6, 1)), index=index, columns=columns)
    return factor, forward


def test_vectorized_groups_share_canonical_metrics_and_unit_capital() -> None:
    factor, forward = _panels()
    result = compute_quantile_portfolio_statistics(
        factor,
        forward,
        group_count=2,
        margin_rates=[0.10, 1.0, 0.20, 0.10],
        open_fee_rates=[0.001] * 4,
        close_fee_rates=[0.001] * 4,
        target_margin_utilization=0.80,
        include_return_series=True,
    )

    assert result["initial_capital"] == 1.0
    assert result["capital_normalization"] == "unit_equity_decimal"
    assert result["turnover_semantics"]["status"].startswith("proxy")
    for mode in result["modes"].values():
        assert len(mode["groups"]) == 2
        assert all("Avg Turnover" in group["metrics"] for group in mode["groups"])
        assert all(len(group["period_returns"]) == 6 for group in mode["groups"])

    no_fee = result["modes"]["no_fee"]["groups"]
    fee = result["modes"]["fee_margin_target"]["groups"]
    # Group 0 is the descending top-ranked bucket, matching native selection.
    assert no_fee[0]["metrics"]["Total Return"] > no_fee[1]["metrics"]["Total Return"]
    assert fee[1]["metrics"]["Total Return"] != no_fee[1]["metrics"]["Total Return"]


def test_vectorized_metrics_compare_to_matching_formal_projection() -> None:
    factor, forward = _panels()
    result = compute_quantile_portfolio_statistics(factor, forward, group_count=2)
    formal = {"groups": [
        {"group_index": item["group_index"], "metrics": item["metrics"]}
        for item in result["modes"]["no_fee"]["groups"]
    ]}
    comparison = compare_quantile_portfolio_statistics(result, formal)
    assert comparison["status"] == "within_tolerance"
    assert comparison["max_absolute_error"] == 0.0


def test_comparison_accepts_formal_projection_metric_map() -> None:
    factor, forward = _panels()
    result = compute_quantile_portfolio_statistics(factor, forward, group_count=2)
    formal = {
        "groups": [
            {"group_index": item["group_index"], "metrics_key": f"G{item['group_index']}"}
            for item in result["modes"]["no_fee"]["groups"]
        ],
        "metrics": {
            f"G{item['group_index']}": item["metrics"]
            for item in result["modes"]["no_fee"]["groups"]
        },
    }
    comparison = compare_quantile_portfolio_statistics(result, formal)
    assert comparison["status"] == "within_tolerance"


def test_comparison_accepts_actual_serialized_event_execution() -> None:
    index = pd.date_range("2024-01-01", periods=6, freq="D")
    columns = ["D", "C", "B", "A"]
    factor = pd.DataFrame(np.tile([1.0, 2.0, 3.0, 4.0], (6, 1)), index=index, columns=columns)
    forward = pd.DataFrame([
        [0.0, 0.0, 0.0, 0.0],
        [-0.02, -0.01, 0.02, 0.04],
        [-0.01, -0.02, 0.01, 0.03],
        [-0.03, -0.01, 0.03, 0.02],
        [-0.02, -0.03, 0.015, 0.05],
        [0.0, 0.01, 0.02, 0.01],
    ], index=index, columns=columns)
    quick = compute_quantile_portfolio_statistics(
        factor, forward, group_count=2, modes=("no_fee",), include_return_series=True,
    )
    portfolios = {}
    owners = []
    for group in quick["modes"]["no_fee"]["groups"]:
        returns = np.asarray(group["period_returns"], dtype=float)
        wealth = np.cumprod(1.0 + returns)
        group_id = f"g{group['group_index']}"
        owners.append({
            "group_id": group_id, "group_name": group_id,
            "group_index": group["group_index"], "is_ls": False,
        })
        portfolios[group_id] = {
            "equity_curve": {
                timestamp.isoformat(): float(value)
                for timestamp, value in zip(index, wealth)
            },
        }
    serialized = serialize_event_execution(
        {
            "group_owner": owners,
            "engine_result": {
                "engine": "native", "portfolios": portfolios,
                "target_trace": {}, "strategy_diagnostics": {},
            },
        },
        settings_by_group={
            owner["group_id"]: {
                "allocation_policy": "equal_notional",
                "rebalance_trigger": "on_factor_signal",
                "position_policy": "rebalance_to_target",
            }
            for owner in owners
        },
        evaluation_split=None,
    )
    assert len(formal_group_statistics({"serialized_execution": serialized})["groups"]) == 2
    comparison = compare_quantile_portfolio_statistics(
        quick, {"serialized_execution": serialized},
        metrics=("Total Return", "Max Drawdown", "Sharpe Ratio"),
        tolerance=1e-10,
    )
    assert comparison["status"] == "within_tolerance"
    assert comparison["max_absolute_error"] <= 1e-10
