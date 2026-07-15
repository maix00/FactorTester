from __future__ import annotations

from tools.data.factor_research_registry import (
    RESEARCH_METRIC_REGISTRY,
    parse_metric_thresholds,
    research_stability_rows,
    resolve_research_rank_preset,
)


def test_research_registry_presets_and_thresholds():
    resolved = resolve_research_rank_preset(
        preset="monotonic-long-short",
        test_type="",
        metric="",
        min_metrics=("ic_mean=0.01",),
        max_metrics=(),
    )

    assert resolved["test_type"] == "backtest"
    assert resolved["metric"] == "a1_a5_return_spread"
    assert parse_metric_thresholds(resolved["min_metrics"]) == {
        "a1_a5_return_spread": 0.0,
        "ic_mean": 0.01,
    }
    assert RESEARCH_METRIC_REGISTRY["a1_a5_return_spread"]["direction"] == "higher"


def test_research_stability_rows_returns_structured_dicts():
    rows = research_stability_rows(
        [
            {"factor_alias": "F|N:1", "test_type": "ic", "product_group": "core", "start_date": "2026-01-01", "metrics": {"ic_mean": 0.02}},
            {"factor_alias": "F|N:1", "test_type": "ic", "product_group": "core", "start_date": "2026-04-01", "metrics": {"ic_mean": -0.01}},
        ],
        metric="ic_mean",
        min_metrics={"ic_mean": 0.0},
        max_metrics={},
        bucket="quarter",
    )

    assert rows == [
        {
            "factor_alias": "F|N:1",
            "test_type": "ic",
            "product_group": "core",
            "periods": 2,
            "pass_count": 1,
            "run_count": 2,
            "avg": 0.005,
            "worst": -0.01,
            "best": 0.02,
            "failures": 1,
        }
    ]
