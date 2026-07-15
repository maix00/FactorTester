from __future__ import annotations

import json

from tools.cli.modules.custom_factors.controller import (
    _research_payloads_from_artifact,
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
    )[0]

    assert payload["test_type"] == "bucket_label"
    assert payload["metrics"]["ic_mean"] == 0.2
    assert payload["metrics"]["a1_label_return"] == 0.01
    assert payload["metrics"]["a5_label_return"] == -0.02
    assert payload["metrics"]["a1_a5_label_return_spread"] == 0.03


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
