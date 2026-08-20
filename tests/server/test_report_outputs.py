import json

import pytest

from server.jobs.report_outputs import (
    build_report_artifacts,
    normalize_output_requests,
    default_output_requests,
    output_declarations,
    output_capabilities,
    output_requests_for_artifacts,
    result_retention_mode_for,
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
    assert {
        "equity_curve", "fee_detail", "margin_detail", "ratio_detail",
        "group_research_detail", "ic_holding_half_life",
    } <= names
    assert normalize_output_requests(["equity", "fees_detail", {"name": "margin"}]) == [
        "equity_curve", "fee_detail", "margin_detail",
    ]
    assert normalize_output_requests(["holding_half_life"]) == ["ic_holding_half_life"]
    capabilities = {item["name"]: item for item in output_capabilities()}
    assert capabilities["ic_holding_half_life"]["formats"] == ["svg", "json"]
    assert "ic_holding_half_life_data" in capabilities["ic_holding_half_life"]["artifacts"]
    assert "ic_statistics_summary_data" in capabilities["ic_statistics"]["artifacts"]
    assert "ic_quantile_portfolio_statistics_data" in capabilities["ic_statistics"]["artifacts"]
    assert capabilities["fee_detail"]["required_sources"] == [{
        "name": "order_audit",
        "label": "订单、成交和结算手续费审计明细",
    }]
    assert source_artifacts_for(["fee_detail", "margin_detail"]) == {
        "result", "order_audit", "group_execution",
    }
    assert source_artifacts_for(["cash_detail"]) == {"order_audit"}
    group_detail = capabilities["group_research_detail"]
    assert group_detail["presentation"] == "detail"
    assert group_detail["viewer"] == "group_research_detail"
    assert group_detail["before_run"] is True
    assert group_detail["after_run"] is False
    assert group_detail["result_retention_mode"] == "full"
    assert source_artifacts_for(["group_research_detail"]) == {
        "result", "group_execution", "order_audit",
    }
    assert result_retention_mode_for(["group_research_detail"]) == "full"
    assert result_retention_mode_for(["fee_detail"]) == "summary"
    assert result_retention_mode_for(["fee_detail"], requested="full") == "full"
    declarations = output_declarations(["equity", "fees"])
    assert [(item["presentation"], item["viewer"]) for item in declarations] == [
        ("chart", "equity_curve"), ("table", "data_table"),
    ]
    assert declarations[0]["artifacts"][0] == "equity_curve_report"
    assert declarations[0]["canonical_artifact"] == "equity_curve_data"
    assert declarations[0]["rendition_artifacts"] == ["equity_curve_report"]
    assert declarations[0]["receipt_artifact"] == "equity_curve_receipt"
    assert "equity_curve_data_receipt" not in declarations[0]["artifacts"]
    assert "fee_detail_data" in declarations[1]["artifacts"]
    detail_declaration = output_declarations(["group_research_detail"])[0]
    assert detail_declaration == {
        "name": "group_research_detail",
        "label": "分组研究详情",
        "presentation": "detail",
        "viewer": "group_research_detail",
        "formats": ["json"],
        "artifacts": [],
        "before_run": True,
        "after_run": False,
        "required_sources": [
            {"name": "result", "label": "回测结果摘要（运行完成后由服务器保留）"},
            {"name": "group_execution", "label": "分组执行明细与组合曲线的原始数据"},
            {"name": "order_audit", "label": "订单、成交和结算手续费审计明细"},
        ],
        "result_retention_mode": "full",
    }
    ic_declarations = output_declarations(["ic_statistics"])
    assert [item["name"] for item in ic_declarations] == [
        "ic_statistics", "ic_statistics_summary", "ic_rolling_stability",
        "ic_period_diagnostics", "ic_quantile_portfolio_statistics",
    ]
    assert ic_declarations[1]["artifacts"][0] == "ic_statistics_summary_csv"
    assert output_requests_for_artifacts([
        "ic_statistics_summary_data", "ic_rolling_stability_csv",
        "ic_period_diagnostics_data", "ic_quantile_portfolio_statistics_data",
        "equity_curve_report",
    ]) == [
        "ic_statistics", "ic_rolling_stability", "ic_period_diagnostics",
        "ic_quantile_portfolio_statistics", "equity_curve",
    ]


def test_ic_statistics_columns_follow_semantic_order() -> None:
    from server.jobs.report_outputs.builders import ordered_ic_statistics_columns

    columns = ordered_ic_statistics_columns([{
        "t_stat_hac": 2.0,
        "factor_alias": "F",
        "forward_return_horizon": "DAY1",
        "mean_ic": 0.1,
        "entry_delay_bars": 0,
        "factor_ref": "ref",
        "n_signal_observations": 10,
    }])
    assert columns[:7] == [
        "factor_alias", "factor_ref", "forward_return_horizon",
        "entry_delay_bars", "n_signal_observations", "mean_ic", "t_stat_hac",
    ]


def test_ic_quantile_portfolio_rows_keep_portfolio_units_separate() -> None:
    from server.jobs.report_outputs.ic import quantile_portfolio_statistics_rows

    result = {
        "factors": [{
            "factor_alias": "ROC", "factor_ref": "factor:v1:roc",
            "ic_method": "rank", "primary_forward_return_horizon": "DAY1",
            "primary_entry_delay_bars": 0,
            "ic_statistics": {
                "quantile_portfolio_statistics": {
                    "status": "computed", "group_count": 2, "product_count": 4,
                    "initial_capital": 1.0, "capital_normalization": "unit_equity_decimal",
                    "target_margin_utilization": 0.3,
                    "modes": {"no_fee": {
                        "groups": [{"group_index": 0, "metrics": {
                            "Total Return": 1.0, "Avg Turnover": 0.2,
                        }}],
                        "long_short": {"metrics": {"Total Return": 2.0}},
                        "monotonicity": {"top_bottom": {"mean_spread": 0.01}},
                        "turnover_proxy": 0.4,
                        "long_short_turnover_proxy": 0.5,
                    }},
                    "turnover_semantics": "target-weight proxy",
                    "metric_semantics": [{"name": "Total Return"}],
                },
            },
        }],
    }
    rows = quantile_portfolio_statistics_rows(result)
    assert [row["portfolio_kind"] for row in rows] == ["group", "long_short"]
    assert rows[0]["avg_turnover"] == 0.2
    assert "metric_semantics" not in rows[0]


def test_ic_quantile_portfolio_rows_include_non_primary_horizon_variants() -> None:
    from server.jobs.report_outputs.ic import quantile_portfolio_statistics_rows

    primary = {
        "status": "computed",
        "group_count": 2,
        "product_count": 4,
        "initial_capital": 1.0,
        "capital_normalization": "unit_equity_decimal",
        "modes": {"no_fee": {"groups": [{"group_index": 0, "metrics": {"Total Return": 1.0}}]}},
    }
    secondary = {
        "status": "computed",
        "source_scope": "forward_return_panel",
        "modes": {"no_fee": {"groups": [{"group_index": 0, "metrics": {"Total Return": 2.0}}]}},
    }
    rows = quantile_portfolio_statistics_rows({
        "factors": [{
            "factor_alias": "ROC",
            "factor_ref": "factor:v1:roc",
            "ic_method": "rank",
            "primary_forward_return_horizon": "DAY1",
            "primary_entry_delay_bars": 0,
            "ic_statistics": {
                "quantile_portfolio_statistics": {
                    **primary,
                    "by_forward_horizon": {"MIN3": {"1": secondary}},
                },
            },
        }],
    })
    assert {(row["forward_return_horizon"], row["entry_delay_bars"]) for row in rows} == {
        ("DAY1", 0), ("MIN3", 1),
    }
    assert next(row for row in rows if row["forward_return_horizon"] == "MIN3")["source_scope"] == "forward_return_panel"


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


def test_optional_execution_and_portfolio_outputs_share_retained_sources() -> None:
    result, source = _sample()
    source["engine_result"]["portfolios"]["A1"].update({
        "cash_curve": {"1": 880.0, "2": 870.0},
        "position_curve": {"1": {"CU.SHF": 2.0}, "2": {"CU.SHF": 3.0}},
        "fill_turnover": {
            "average": 0.25, "total": 0.5, "observations": 2,
            "source": "fill_audit",
        },
    })
    source["order_audit"]["strategies"]["A1"]["orders"] = [{
        "order_id": "order-1", "product": "CU.SHF", "side": "BUY",
        "requested_quantity": 2.0, "filled_quantity": 2.0,
    }]
    source["order_audit"]["strategies"]["A1"]["fills"][0].update({
        "fill_id": "fill-1", "order_id": "order-1", "price": 500.0,
        "quantity": 2.0,
    })
    source["order_audit"]["strategies"]["A1"]["settlements"] = [{
        "fill_id": "fill-1", "cash_before": 900.0, "cash_after": 880.0,
        "margin_before": 100.0, "margin_after": 120.0,
        "realized_pnl": 1.0, "fee": 3.5,
    }]

    artifacts = build_report_artifacts(
        result, source=source, requested=[
            "order_detail", "fill_detail", "cash_detail", "position_detail",
            "exposure_detail", "turnover_detail", "drawdown_detail",
            "period_returns",
        ],
    )
    payloads = {
        item.name: json.loads(item.raw)
        for item in artifacts if item.extension == "json"
    }
    assert payloads["order_detail_data"]["rows"][0]["order_id"] == "order-1"
    fill = payloads["fill_detail_data"]["rows"][0]
    assert fill["cash_change"] == -20.0
    assert fill["margin_change"] == 20.0
    assert payloads["cash_detail_data"]["rows"][0]["cash"] == 880.0
    assert payloads["position_detail_data"]["rows"][0]["quantity"] == 2.0
    assert payloads["exposure_detail_data"]["rows"][0]["gross_exposure"] == 1000.0
    assert payloads["turnover_detail_data"]["rows"][0]["average"] == 0.25
    assert payloads["drawdown_detail_data"]["rows"]
    assert payloads["period_returns_data"]["rows"]

    post_run = build_report_artifacts(
        result,
        source={
            "group_execution": {"engine_result": source["engine_result"]},
            "order_audit": source["order_audit"],
        },
        requested=["cash_detail", "margin_detail", "fill_detail"],
    )
    post_run_payloads = {
        item.name: json.loads(item.raw)
        for item in post_run if item.extension == "json"
    }
    assert post_run_payloads["cash_detail_data"]["rows"][0]["cash"] == 880.0
    assert post_run_payloads["margin_detail_data"]["rows"][0]["margin"] == 120.0
    assert post_run_payloads["fill_detail_data"]["rows"][0]["fill_id"] == "fill-1"


def test_audit_only_output_skips_equity_projection(monkeypatch) -> None:
    from server.jobs.report_outputs import dataset as dataset_module

    result, source = _sample()
    monkeypatch.setattr(
        dataset_module, "extract_series",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("equity projection must remain lazy"),
        ),
    )

    reports = build_report_artifacts(
        result, source=source, requested=["fee_detail"],
    )

    assert {item.name for item in reports} == {"fee_detail_csv", "fee_detail_data"}


def test_cash_detail_uses_retained_settlement_without_dense_engine_curve() -> None:
    reports = build_report_artifacts(
        {},
        source={"order_audit": {"strategies": {"A1": {
            "fills": [{"fill_id": "fill-1", "timestamp": "2024-01-02T09:00:00"}],
            "settlements": [{
                "fill_id": "fill-1", "cash_before": 1000.0,
                "cash_after": 970.0,
            }],
        }}}},
        requested=["cash_detail"],
    )
    payload = json.loads(next(
        item.raw for item in reports if item.name == "cash_detail_data"
    ))
    assert payload["rows"] == [{
        "strategy": "A1", "timestamp": "2024-01-02T09:00:00",
        "fill_id": "fill-1", "cash_before": 1000.0,
        "cash_after": 970.0, "cash_change": -30.0,
    }]


def test_report_builder_emits_monotonic_output_progress() -> None:
    result, source = _sample()
    observed = []

    build_report_artifacts(
        result,
        source=source,
        requested=["fee_detail", "order_detail", "period_returns"],
        progress=lambda completed, total, name: observed.append(
            (completed, total, name),
        ),
    )

    assert observed == [
        (1, 3, "fee_detail"),
        (2, 3, "order_detail"),
        (3, 3, "period_returns"),
    ]


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
    factor_ref = "factor:v1:profile-maxa:path:identity:" + "a" * 40 + ":" + "b" * 40
    result = {
        "success": True,
        "forward_horizon_sampling": {
            "mode": "scale_aware", "source": "request",
            "resolved_horizons": ["MIN1", "MIN5", "DAY1"],
        },
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
                "DAY2": {"0": {"mean": 0.2, "std": 0.12, "IR": 1.7, "t_stat": 2.2}},
            },
            "period_diagnostics": {
                "schema": "ic-period-diagnostics-v1",
                "periods": {
                    "month": {
                        "rule": "month",
                        "min_signal_observations": 2,
                        "min_periods": 3,
                        "n_periods_total": 1,
                        "n_periods_estimable": 1,
                        "n_periods_hac_estimable": 1,
                        "period_estimability_status": "not_estimable",
                        "periods": [{
                            "period_start": "2024-01-01T00:00:00",
                            "period_estimable": True,
                            "hac_estimable": True,
                            "n_signal_observations": 2,
                            "mean_ic": 0.3,
                            "std_ic": 0.1,
                            "icir_signal": 3.0,
                            "t_stat_hac": 2.0,
                            "ci95_hac_lower": 0.01,
                            "ci95_hac_upper": 0.59,
                            "hac_status": "estimable",
                            "direction_rate": 1.0,
                            "positive_ic_rate": 1.0,
                            "effective_n_capped": 2,
                            "ic_series_acf1": 0.1,
                        }],
                    },
                },
            },
        }],
    }

    artifacts = build_report_artifacts(
        result,
        requested=["ic_series", "ic_statistics"], job_id="job-123",
    )

    names = {item.name for item in artifacts}
    assert names == {
        "ic_series_report", "ic_series_data",
        "ic_statistics_csv", "ic_statistics_data",
        "ic_statistics_summary_csv", "ic_statistics_summary_data",
        "ic_period_diagnostics_csv", "ic_period_diagnostics_data",
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
    summary = payloads["ic_statistics_summary_data"]
    assert summary["artifact_kind"] == "ic_statistics_summary"
    assert summary["artifact_role"] == "report_table"
    assert summary["columns"] == [
        "factor", "experiment", "entry_delay_bars",
        "primary_forward_return_horizon", "n_horizons",
        "n_signal_observations_primary", "mean_ic_primary", "std_ic_primary",
        "icir_signal_primary", "t_stat_hac_primary", "ci95_hac_lower_primary",
        "ci95_hac_upper_primary", "hac_status_primary", "direction_rate_primary",
        "positive_ic_rate_primary", "effective_n_capped_primary",
        "ic_series_acf1_primary", "forward_ic_half_life_status",
        "forward_ic_half_life_registered_direction",
        "forward_ic_half_life_observed_direction",
        "forward_ic_half_life_direction_match",
        "forward_ic_half_life_direction_status",
        "forward_ic_half_life_exponential_seconds", "source",
    ]
    assert len(summary["rows"]) == 1
    assert summary["rows"][0]["primary_forward_return_horizon"] == "DAY1"
    assert summary["rows"][0]["n_horizons"] == 2
    assert summary["aggregation"]["half_life"] == (
        "fit over all available horizon-level mean IC values"
    )
    summary_artifact = next(
        item for item in artifacts if item.name == "ic_statistics_summary_data"
    )
    assert summary_artifact.receipt["aggregation"]["row_key"] == [
        "factor_ref", "factor_alias", "ic_method", "entry_delay_bars",
    ]
    assert "factortester://factor/" in summary["rows"][0]["factor"]
    assert "factortester://job/job%3Ajob-123" in summary["rows"][0]["experiment"]
    assert "factortester://artifact/" in summary["rows"][0]["source"]
    period = payloads["ic_period_diagnostics_data"]
    assert period["artifact_kind"] == "ic_period_diagnostics"
    assert period["period_diagnostics_schema"] == "ic-period-diagnostics-v1"
    assert period["rows"][0]["period_label"] == "month"
    assert "factortester://factor/" in period["rows"][0]["factor"]
    assert payloads["ic_statistics_data"]["column_presentations"] == {
        "factor_alias": {
            "presentation": "reference",
            "kind": "factor",
            "target_ref_field": "factor_ref",
        }
    }
    assert payloads["ic_statistics_data"]["ic_diagnostics_schema"] == "ic-diagnostics-v1"
    assert payloads["ic_statistics_data"]["forward_horizon_sampling"]["mode"] == "scale_aware"
    assert any(
        item["name"] == "forward_ic_half_life_exponential"
        for item in payloads["ic_statistics_data"]["ic_metric_semantics"]
    )


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
                "baseline_horizon": "MIN1",
                "baseline_seconds": 60.0,
                "baseline_mean_ic": 0.08,
                "expected_direction": 1,
                "log_fit_rmse": 0.02,
            },
            "ic_stats_by_forward_horizon": {
                "MIN1": {"0": {
                    "diagnostics_schema": "ic-diagnostics-v1",
                    "n_signal_observations": 10,
                    "mean_ic": 0.02,
                    "std_ic": 0.04,
                    "expected_sign": 1,
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
    assert rows[0]["forward_ic_half_life_exponential_baseline_seconds"] == 60.0
    assert rows[0]["forward_ic_half_life_exponential_log_fit_rmse"] == 0.02
    assert rows[0]["forward_ic_half_life_registered_direction"] == 1
    assert rows[0]["forward_ic_half_life_observed_direction"] == 1
    assert rows[0]["forward_ic_half_life_direction_match"] is True
    assert rows[0]["forward_ic_half_life_direction_status"] == "match"


def test_half_life_direction_comparison_reports_mismatch_without_changing_fit() -> None:
    from server.jobs.report_outputs.ic import ic_statistics_rows

    rows = ic_statistics_rows({
        "factors": [{
            "factor_alias": "F1",
            "forward_ic_half_life": {
                "status": "estimated",
                "expected_direction": -1,
            },
            "forward_ic_half_life_exponential": {
                "status": "estimated",
                "expected_direction": -1,
                "half_life_seconds": 90.0,
            },
            "ic_stats_by_forward_horizon": {
                "MIN1": {"0": {"mean_ic": -0.1, "expected_sign": 1}},
            },
        }],
    })

    assert rows[0]["forward_ic_half_life_expected_direction"] == -1
    assert rows[0]["forward_ic_half_life_registered_direction"] == 1
    assert rows[0]["forward_ic_half_life_observed_direction"] == -1
    assert rows[0]["forward_ic_half_life_direction_match"] is False
    assert rows[0]["forward_ic_half_life_direction_status"] == "mismatch"


def test_ic_statistics_rows_respect_metric_selection_projection() -> None:
    from server.jobs.report_outputs.ic import ic_statistics_rows

    rows = ic_statistics_rows({
        "ic_metric_selection": {"include": ["core"]},
        "factors": [{
            "factor_alias": "F1",
            "ic_stats_by_forward_horizon": {
                "MIN1": {"0": {
                    "mean_ic": 0.02,
                    "std_ic": 0.04,
                    "t_stat_hac": 3.0,
                }},
            },
        }],
    })

    assert rows[0]["mean_ic"] == 0.02
    assert rows[0]["std_ic"] == 0.04
    assert "t_stat_hac" not in rows[0]


def test_holding_period_half_life_is_parallel_on_demand_plot() -> None:
    result = {
        "forward_horizon_sampling": {
            "mode": "scale_aware", "source": "request",
            "resolved_horizons": ["MIN1", "MIN3", "MIN5"],
        },
        "factors": [{
            "factor_alias": "F1|N:1m|$F:1m",
            "factor_ref": "factor-ref:F1",
            "ic_method": "rank",
            "ic_stats_by_forward_horizon": {
                "MIN1": {"0": {"mean_ic": 0.08}},
                "MIN3": {"0": {"mean_ic": 0.04}},
                "MIN5": {"0": {"mean_ic": 0.02}},
            },
        }],
    }
    artifacts = build_report_artifacts(result, requested=["ic_holding_half_life"])
    assert {item.name for item in artifacts} == {
        "ic_holding_half_life_report", "ic_holding_half_life_data",
    }
    svg = next(item.raw for item in artifacts if item.name == "ic_holding_half_life_report").decode("utf-8")
    assert "真实持有期 IC 半衰期" in svg
    assert "指数拟合" in svg
    assert "基准 IC ($F=1m, 方向对齐)" in svg
    assert "entry_delay=0" in svg
    assert "F1 · entry_delay=0 ·" not in svg
    data = json.loads(next(item.raw for item in artifacts if item.name == "ic_holding_half_life_data"))
    assert data["artifact_kind"] == "ic_holding_half_life"
    assert data["rows"][0]["exponential_half_life_seconds"] == 120.0
    assert data["rows"][0]["baseline_horizon"] == "MIN1"
    assert data["inference"].startswith("descriptive_only")
    assert "may overlap" in data["horizon_overlap_note"]
    assert data["forward_horizon_sampling"]["resolved_horizons"] == ["MIN1", "MIN3", "MIN5"]


def test_holding_period_numbers_are_inside_ic_statistics_table() -> None:
    from server.jobs.report_outputs.ic import ic_statistics_rows

    rows = ic_statistics_rows({
        "factors": [{
            "factor_alias": "F1",
            "forward_ic_half_life_by_entry_delay": {
                "0": {"status": "estimated", "seconds": 60.0, "duration": "MIN1"},
                "1": {"status": "estimated", "seconds": 120.0, "duration": "MIN2"},
            },
            "forward_ic_half_life_exponential_by_entry_delay": {
                "0": {"status": "estimated", "half_life_seconds": 90.0, "r_squared": 0.8, "n_horizons": 3},
                "1": {"status": "estimated", "half_life_seconds": 180.0, "r_squared": 0.7, "n_horizons": 3},
            },
            "ic_stats_by_forward_horizon": {
                "MIN1": {"0": {"mean_ic": 0.1}, "1": {"mean_ic": 0.1}},
                "MIN3": {"0": {"mean_ic": 0.05}, "1": {"mean_ic": 0.05}},
            },
        }],
    })
    assert rows[0]["forward_ic_half_life_exponential_seconds"] == 90.0
    assert rows[1]["forward_ic_half_life_exponential_seconds"] == 180.0
    assert rows[0]["forward_ic_half_life_crossing_seconds"] == 60.0


def test_output_requests_are_validated_against_selected_analyses() -> None:
    assert validate_output_requests(["ic_series"], ["ic"]) == ["ic_series"]
    assert validate_output_requests(["equity_curve", "ic_statistics"], [
        "backtest", "ic",
    ]) == ["equity_curve", "ic_statistics"]
    with pytest.raises(ValueError, match="requires one of analyses: ic"):
        validate_output_requests(["ic_series"], ["backtest"])
    assert default_output_requests(["ic"]) == [
        "ic_series", "ic_statistics", "ic_holding_half_life",
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
