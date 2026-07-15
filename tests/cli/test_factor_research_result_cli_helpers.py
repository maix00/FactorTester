from __future__ import annotations

import json

from tools.cli.modules.custom_factors.controller import (
    _RESEARCH_METRIC_REGISTRY,
    _research_payloads_from_artifact,
    _research_stability_rows,
    _resolve_research_rank_preset,
)


def test_research_payloads_from_backtest_artifact(tmp_path):
    artifact = tmp_path / "backtest.json"
    artifact.write_text(
        json.dumps(
            {
                "family": "MmTrend",
                "factor_source": "public",
                "alias": "MmTrend|N:10d|$F:1d",
                "start_date": "2024-01-02",
                "end_date": "2025-12-31",
                "product_group": "core8",
                "local_setting_overrides": {"fee_mode": "exact"},
                "groups": [
                    {"name": "A1", "return": 0.3, "max_drawdown": -0.1},
                    {"name": "A5", "return": -0.2, "max_drawdown": -0.3},
                    {"name": "LS A1/A5", "return": 0.4, "max_drawdown": -0.2},
                ],
            }
        ),
        encoding="utf-8",
    )

    payloads = _research_payloads_from_artifact(
        artifact,
        factor_family="",
        factor_alias="",
        product_group="",
        test_type="auto",
        report_path="/tmp/report.md",
        note="note",
        metadata={},
    )

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["ff_alias"] == "MmTrend"
    assert payload["test_type"] == "backtest"
    assert payload["metrics"]["a1_return"] == 0.3
    assert payload["metrics"]["a5_return"] == -0.2
    assert payload["metrics"]["ls_return"] == 0.4
    assert payload["metrics"]["a1_a5_return_spread"] == 0.5


def test_research_payloads_from_ic_artifact_with_multiple_aliases(tmp_path):
    artifact = tmp_path / "ic.json"
    artifact.write_text(
        json.dumps(
            {
                "family": "MmRet",
                "factor_source": "public",
                "start_date": "2024-01-02",
                "end_date": "2024-12-31",
                "product_group": "core8",
                "summary": {
                    "MmRet|N:10d": {"mean": 0.1, "t_stat": 2.0, "n": 100, "positive_rate": 0.6},
                    "MmRet|N:20d": {"mean": -0.1, "t_stat": -2.0, "n": 100, "positive_rate": 0.4},
                },
            }
        ),
        encoding="utf-8",
    )

    payloads = _research_payloads_from_artifact(
        artifact,
        factor_family="",
        factor_alias="",
        product_group="",
        test_type="auto",
        report_path="",
        note="",
        metadata={},
    )

    assert [payload["factor_alias"] for payload in payloads] == ["MmRet|N:10d", "MmRet|N:20d"]
    assert payloads[0]["metrics"]["ic_mean"] == 0.1
    assert payloads[1]["metrics"]["ic_t_stat"] == -2.0


def test_research_payloads_from_bucket_label_artifact(tmp_path):
    artifact = tmp_path / "bucket.json"
    artifact.write_text(
        json.dumps(
            {
                "family": "MmVolWgtRet",
                "canonical_alias": "MmVolWgtRet|N:10d",
                "start_date": "2024-01-02",
                "end_date": "2025-12-31",
                "product_group": "core8",
                "ic": {"mean": 0.2, "positive_rate": 0.7},
                "bucket_forward_returns": [
                    {"mean": {"A1": 0.01, "A5": -0.02}},
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = _research_payloads_from_artifact(
        artifact,
        factor_family="",
        factor_alias="",
        product_group="",
        test_type="auto",
        report_path="",
        note="",
        metadata={"sample_role": "oos", "regime_label": "low-vol"},
    )[0]

    assert payload["test_type"] == "bucket_label"
    assert payload["metrics"]["ic_mean"] == 0.2
    assert payload["metrics"]["a1_label_return"] == 0.01
    assert payload["metrics"]["a5_label_return"] == -0.02
    assert payload["metrics"]["a1_a5_label_return_spread"] == 0.03
    assert payload["config"]["research_meta"]["sample_role"] == "oos"
    assert payload["config"]["research_meta"]["regime_label"] == "low-vol"


def test_research_rank_preset_expands_default_filters():
    resolved = _resolve_research_rank_preset(
        preset="ic-stable",
        test_type="",
        metric="",
        min_metrics=("sample_count=100",),
        max_metrics=(),
    )

    assert resolved["test_type"] == "ic"
    assert resolved["metric"] == "ic_mean"
    assert resolved["min_metrics"] == ["ic_mean=0", "ic_t_stat=2", "sample_count=100"]


def test_research_rank_preset_respects_explicit_metric_and_test_type():
    resolved = _resolve_research_rank_preset(
        preset="costed-backtest",
        test_type="bucket_label",
        metric="a1_a5_label_return_spread",
        min_metrics=(),
        max_metrics=("max_drawdown=0",),
    )

    assert resolved["test_type"] == "bucket_label"
    assert resolved["metric"] == "a1_a5_label_return_spread"
    assert resolved["min_metrics"] == ["ls_return=0"]
    assert resolved["max_metrics"] == ["max_drawdown=0"]


def test_research_rank_preset_supports_aliases():
    resolved = _resolve_research_rank_preset(
        preset="costed-good",
        test_type="",
        metric="",
        min_metrics=(),
        max_metrics=(),
    )

    assert resolved["test_type"] == "backtest"
    assert resolved["metric"] == "ls_return"
    assert resolved["min_metrics"] == ["ls_return=0"]


def test_research_stability_rows_aggregates_periods_and_failures():
    rows = _research_stability_rows(
        [
            {
                "factor_alias": "F|N:1",
                "test_type": "ic",
                "product_group": "core",
                "start_date": "2026-01-01",
                "metrics": {"ic_mean": 0.03, "ic_t_stat": 2.4},
            },
            {
                "factor_alias": "F|N:1",
                "test_type": "ic",
                "product_group": "core",
                "start_date": "2026-04-01",
                "metrics": {"ic_mean": -0.01, "ic_t_stat": -0.5},
            },
        ],
        metric="ic_mean",
        min_metrics={"ic_mean": 0.0, "ic_t_stat": 2.0},
        max_metrics={},
        bucket="quarter",
    )

    assert rows == [("F|N:1", "ic", "core", 2, "1/2", "0.01", "-0.01", "0.03", 1)]


def test_research_metric_registry_has_core_metrics():
    assert _RESEARCH_METRIC_REGISTRY["ic_mean"]["default_test_type"] == "ic"
    assert _RESEARCH_METRIC_REGISTRY["ls_return"]["direction"] == "higher"
