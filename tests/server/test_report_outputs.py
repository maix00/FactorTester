import json

import pytest

from server.jobs.report_outputs import (
    build_report_artifacts,
    normalize_output_requests,
    default_output_requests,
    output_declarations,
    output_capabilities,
    source_artifacts_for,
    output_requests_for_analysis,
    validate_output_requests,
)
from server.jobs.report_outputs.series import metrics_rows


def _sample():
    result = {
        "groups": [{
            "name": "A1",
            "timestamps": [1, 2, 3],
            "total_equity": [100.0, 103.0, 101.0],
            "metrics": {"Sharpe Ratio": 1.2},
        }],
        "metrics": {"A1": {"Sharpe Ratio": 1.2}},
    }
    source = {
        "order_audit": {
            "strategies": {
                "A1": {
                    "fills": [{"timestamp": 1, "product": "CU.SHF", "fee": 3.5}],
                    "settlements": [{"timestamp": 2, "product": "CU.SHF", "fee": 1.5}],
                }
            }
        },
        "engine_result": {
            "portfolios": {
                "A1": {
                    "equity_curve": {"1": 100.0, "2": 103.0, "3": 101.0},
                    "notional_curve": {"1": {"CU.SHF": 1000.0}, "2": {"CU.SHF": 1100.0}},
                    "margin_curve": {"1": {"CU.SHF": 120.0}, "2": {"CU.SHF": 130.0}},
                }
            }
        },
    }
    return result, source


def test_output_capabilities_and_aliases_are_declared() -> None:
    names = {item["name"] for item in output_capabilities()}
    assert {"equity_curve", "fee_detail", "margin_detail", "ratio_detail"} <= names
    assert normalize_output_requests(["equity", "fees_detail", {"name": "margin"}]) == [
        "equity_curve", "fee_detail", "margin_detail",
    ]
    assert source_artifacts_for(["fee_detail", "margin_detail"]) == {
        "result", "order_audit", "group_execution",
    }
    declarations = output_declarations(["equity", "fees"])
    assert [(item["presentation"], item["viewer"]) for item in declarations] == [
        ("chart", "equity_curve"), ("table", "data_table"),
    ]
    assert declarations[0]["artifacts"][0] == "equity_curve_report"
    assert "fee_detail_data" in declarations[1]["artifacts"]


def test_requested_reports_include_images_tables_and_receipts() -> None:
    result, source = _sample()
    artifacts = build_report_artifacts(
        result,
        source=source,
        requested=[
            "equity_curve", "returns_over_time", "metrics_over_time",
            "fee_detail", "margin_detail", "ratio_detail",
        ],
    )
    names = {item.name for item in artifacts}
    assert {"equity_curve_report", "returns_over_time_report", "metrics_over_time_report"} <= names
    assert {"fee_detail_csv", "margin_detail_csv", "ratio_detail_csv"} <= names
    assert all(item.raw for item in artifacts)


def test_equity_svg_formats_epoch_timestamps_and_account_currency() -> None:
    result = {
        "groups": [{
            "name": "A1",
            "base_currency": "CNY",
            "timestamps": [1704178800000, 1704265200000],
            "total_equity": [1_000_000.0, 1_010_000.0],
        }],
    }

    artifacts = build_report_artifacts(
        result, requested=["equity_curve"],
    )

    svg = next(
        item.raw for item in artifacts if item.name == "equity_curve_report"
    ).decode("utf-8")
    assert "CNY" in svg
    assert "2024" in svg
    assert "1704178800000" not in svg
    assert svg.lstrip().startswith("<svg")
    assert "<!DOCTYPE" not in svg


def test_metrics_svg_formats_epoch_timestamps() -> None:
    result = {
        "groups": [{
            "name": "A1",
            "timestamps": [1704178800000, 1704265200000],
            "total_equity": [1_000_000.0, 1_010_000.0],
        }],
    }

    artifacts = build_report_artifacts(
        result, requested=["metrics_over_time"],
    )

    svg = next(
        item.raw for item in artifacts if item.name == "metrics_over_time_report"
    ).decode("utf-8")
    assert "2024" in svg
    assert "1704178800000" not in svg


def test_requested_ic_outputs_include_series_and_statistics() -> None:
    factor_ref = "factor-expr:MmRateOfChg|P:CA|N:20d|$F:1d@sha256:" + "a" * 64
    result = {
        "success": True,
        "factors": [{
            "factor_alias": "MmRateOfChg|P:CA|N:20d|$F:1d",
            "factor_ref": factor_ref,
            "ic_method": "rank",
            "primary_forward_return_horizon": "DAY1",
            "ic_series_by_forward_horizon": [{
                "horizon": "DAY1",
                "entry_delay_bars": 0,
                "dates": ["2024-01-02", "2024-01-03"],
                "values": [0.2, 0.4],
            }],
            "ic_stats_by_forward_horizon": {
                "DAY1": {"0": {"mean": 0.3, "std": 0.1, "IR": 3.0, "t_stat": 4.0}},
            },
        }],
    }

    artifacts = build_report_artifacts(
        result,
        requested=["ic_series", "ic_statistics"],
    )

    names = {item.name for item in artifacts}
    assert names == {
        "ic_series_report", "ic_series_data",
        "ic_statistics_csv", "ic_statistics_data",
    }
    ic_svg = next(
        item.raw for item in artifacts if item.name == "ic_series_report"
    ).decode("utf-8")
    assert "初始金额" not in ic_svg
    capabilities = {item["name"]: item for item in output_capabilities()}
    assert capabilities["ic_series"]["analyses"] == ["ic"]
    assert capabilities["ic_statistics"]["presentation"] == "table"
    payloads = {
        item.name: json.loads(item.raw)
        for item in artifacts if item.extension == "json"
    }
    assert payloads["ic_series_data"]["series"][0]["factor_ref"] == factor_ref
    assert payloads["ic_statistics_data"]["rows"][0]["factor_ref"] == factor_ref
    assert payloads["ic_statistics_data"]["column_presentations"] == {
        "factor_alias": {
            "presentation": "reference",
            "kind": "factor",
            "target_ref_field": "factor_ref",
        }
    }


def test_ic_statistics_rows_expose_explicit_uncertainty_and_half_life_fields() -> None:
    from server.jobs.report_outputs.ic import ic_statistics_rows

    rows = ic_statistics_rows({
        "factors": [{
            "factor_alias": "F1",
            "factor_ref": "factor-ref:F1",
            "ic_method": "rank",
            "forward_ic_half_life_exponential": {
                "status": "estimated",
                "duration": "MIN5",
                "half_life_seconds": 300.0,
                "r_squared": 0.9,
                "n_horizons": 4,
            },
            "ic_stats_by_forward_horizon": {
                "MIN1": {"0": {
                    "diagnostics_schema": "ic-diagnostics-v1",
                    "n_signal_observations": 10,
                    "mean_ic": 0.02,
                    "std_ic": 0.04,
                    "se_iid": 0.012,
                    "ci95_hac_lower": -0.01,
                    "ci95_hac_upper": 0.05,
                    "hac_lag": 3,
                    "hac_lag_source": "temporal_support_overlap",
                    "hac_lag_formula": "formula",
                    "hac_kernel": "bartlett",
                    "ic_series_ar1_half_life_seconds": 120.0,
                }},
            },
        }],
    })

    assert rows[0]["se_iid"] == 0.012
    assert rows[0]["hac_lag_source"] == "temporal_support_overlap"
    assert rows[0]["hac_kernel"] == "bartlett"
    assert rows[0]["ic_series_ar1_half_life_seconds"] == 120.0
    assert rows[0]["forward_ic_half_life_exponential_seconds"] == 300.0


def test_output_requests_are_validated_against_selected_analyses() -> None:
    assert validate_output_requests(["ic_series"], ["ic"]) == ["ic_series"]
    assert validate_output_requests(["equity_curve", "ic_statistics"], [
        "backtest", "ic",
    ]) == ["equity_curve", "ic_statistics"]
    with pytest.raises(ValueError, match="requires one of analyses: ic"):
        validate_output_requests(["ic_series"], ["backtest"])
    assert default_output_requests(["ic"]) == [
        "ic_series", "ic_statistics",
    ]
    assert default_output_requests(["backtest"]) == []
    assert output_requests_for_analysis([
        "equity_curve", "ic_statistics",
    ], "ic") == ["ic_statistics"]


def test_metrics_rows_keep_historical_max_drawdown_and_cumulative_metrics() -> None:
    rows = metrics_rows([{
        "label": "A1",
        "timestamps": ["2025-01-01T00:00:00Z", "2025-06-01T00:00:00Z", "2026-01-01T00:00:00Z"],
        "values": [100.0, 120.0, 90.0],
    }])

    assert rows[-1]["drawdown"] == rows[-1]["max_drawdown"]
    assert rows[-1]["max_drawdown"] < 0
    assert "annual_return" in rows[-1]
    assert "sharpe_ratio" in rows[-1]
    assert rows[-1]["annual_return"] < 0
