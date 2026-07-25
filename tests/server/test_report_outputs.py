from server.jobs.report_outputs import (
    build_report_artifacts,
    normalize_output_requests,
    output_declarations,
    output_capabilities,
    source_artifacts_for,
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
