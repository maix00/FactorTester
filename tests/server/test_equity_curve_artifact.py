from __future__ import annotations

import json
import queue

from server.jobs.equity_curve_artifact import build_equity_curve_artifact
from server.jobs.scheduling.worker_pool import _WorkerSink


def test_equity_curve_artifact_is_small_deterministic_and_self_describing() -> None:
    result = {
        "groups": [{
            "name": "SgCCS 参数 1",
            "timestamps": [f"2025-01-{index + 1:02d}" for index in range(20)],
            "total_equity": [100 + index * 2 - (8 if index == 11 else 0) for index in range(20)],
        }]
    }

    first = build_equity_curve_artifact(result)
    second = build_equity_curve_artifact(result)

    assert first == second
    assert first is not None
    image, receipt = first
    assert image.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"')
    assert b"<polyline" in image
    assert b"SgCCS" in image
    assert len(image) < 100_000
    assert receipt["panels"] == ["equity", "drawdown"]
    assert receipt["drawdown_definition"] == "historical_maximum_drawdown_through_each_point"
    assert receipt["initial_equity"] == [100]
    assert receipt["series"][0]["original_points"] == 20
    assert receipt["downsampling"] == "bucket_minmax_preserve_endpoints"


def test_equity_curve_artifact_downsamples_and_rejects_invalid_series() -> None:
    curve = build_equity_curve_artifact({
        "groups": [{
            "key": "long-history",
            "timestamps": list(range(10_000)),
            "total_equity": [100 + index / 100 for index in range(10_000)],
        }]
    })
    assert curve is not None
    _, receipt = curve
    assert receipt["series"][0]["rendered_points"] <= 800
    assert receipt["series"][0]["original_points"] == 10_000
    assert build_equity_curve_artifact({"groups": [{
        "total_equity": [1.0, float("nan")],
    }]}) is None


def test_summary_retention_keeps_complete_interactive_curve_not_full_result(
    tmp_path,
) -> None:
    output = queue.Queue()
    sink = _WorkerSink(
        "job-summary",
        output,
        artifact_root=str(tmp_path),
        retention_mode="summary",
    )

    sink.emit_result({
        "success": True,
        "groups": [{
            "name": "main",
            "timestamps": [1, 2, 3],
            "total_equity": [100.0, 103.0, 101.0],
        }],
    })

    messages = []
    while not output.empty():
        messages.append(output.get_nowait())
    names = {
        item["data"]["name"]
        for item in messages
        if item.get("event") == "artifact"
    }
    assert names == {
        "equity_curve_report", "equity_curve_receipt",
        "equity_curve_data", "equity_curve_data_receipt",
    }
    assert not (tmp_path / "job-summary" / "result.json").exists()
    assert (tmp_path / "job-summary" / "equity_curve_report.svg").is_file()
    data = json.loads(
        (tmp_path / "job-summary" / "equity_curve_data.json").read_text()
    )
    assert data["series"][0]["values"] == [100.0, 103.0, 101.0]
    assert len(data["series"][0]["values"]) == len(
        data["series"][0]["drawdown"]
    )


def test_summary_retention_does_not_downsample_interactive_curve(tmp_path) -> None:
    output = queue.Queue()
    sink = _WorkerSink(
        "job-complete-series",
        output,
        artifact_root=str(tmp_path),
        retention_mode="summary",
    )
    points = 3_000
    sink.emit_result({
        "success": True,
        "groups": [{
            "name": "main",
            "timestamps": list(range(points)),
            "total_equity": [100.0 + index / 10 for index in range(points)],
        }],
    })

    data = json.loads(
        (tmp_path / "job-complete-series" / "equity_curve_data.json").read_text()
    )
    assert len(data["series"][0]["values"]) == points
    assert len(data["series"][0]["timestamps"]) == points
    assert len(data["series"][0]["drawdown"]) == points


def test_declared_outputs_retain_only_required_sources_and_generate_reports(tmp_path) -> None:
    output = queue.Queue()
    sink = _WorkerSink(
        "job-declared",
        output,
        artifact_root=str(tmp_path),
        retention_mode="summary",
        output_requests=["fee_detail", "margin_detail"],
    )
    group_execution = {
        "engine_result": {
            "portfolios": {
                "A1": {
                    "equity_curve": {"1": 100.0, "2": 101.0},
                    "margin_curve": {"1": {"CU.SHF": 10.0}},
                    "notional_curve": {"1": {"CU.SHF": 100.0}},
                }
            }
        }
    }
    sink.emit_artifact("group_execution", group_execution)
    sink.emit_artifact("order_audit", {
        "strategies": {"A1": {"fills": [{"timestamp": 1, "fee": 2.0}]}}
    })
    sink.emit_result({
        "groups": [{"name": "A1", "timestamps": [1, 2], "total_equity": [100.0, 101.0]}]
    }, source=group_execution)

    names = {
        item["data"]["name"]
        for item in list(output.queue)
        if item.get("event") == "artifact"
    }
    assert {"group_execution", "order_audit", "fee_detail_csv", "margin_detail_csv"} <= names
    assert (tmp_path / "job-declared" / "result.json").exists()


def test_group_research_detail_retains_drilldown_sources_without_extra_report(
    tmp_path,
) -> None:
    output = queue.Queue()
    sink = _WorkerSink(
        "job-group-detail",
        output,
        artifact_root=str(tmp_path),
        retention_mode="full",
        output_requests=["group_research_detail"],
    )
    group_execution = {
        "engine_result": {
            "portfolios": {"A1": {"equity_curve": {"1": 100.0}}},
        },
        "group_owner": [{"group_id": "A1", "group_index": 0}],
    }
    sink.emit_artifact("group_execution", group_execution)
    sink.emit_artifact("order_audit", {"strategies": {"A1": {"fills": []}}})
    sink.emit_result({
        "success": True,
        "groups": [{"name": "A1", "timestamps": [1], "total_equity": [100.0]}],
    }, source=group_execution)

    names = {
        item["data"]["name"]
        for item in list(output.queue)
        if item.get("event") == "artifact"
    }
    assert {"result", "group_execution", "order_audit"} <= names
    assert not any(name.endswith("_report") for name in names)


def test_summary_retention_generates_default_ic_artifacts(tmp_path) -> None:
    output = queue.Queue()
    sink = _WorkerSink(
        "job-ic",
        output,
        artifact_root=str(tmp_path),
        retention_mode="summary",
    )

    sink.emit_result({
        "success": True,
        "factors": [{
            "factor_alias": "MmRateOfChg|P:CA|N:20d|$F:1d",
            "ic_method": "rank",
            "primary_forward_return_horizon": "DAY1",
            "ic_series_by_forward_horizon": [{
                "horizon": "DAY1",
                "entry_delay_bars": 0,
                "dates": ["2024-01-02", "2024-01-03"],
                "values": [0.2, 0.4],
            }],
            "ic_stats_by_forward_horizon": {
                "DAY1": {"0": {"mean": 0.3, "std": 0.1, "IR": 3.0}},
                "DAY2": {"0": {"mean": 0.2, "std": 0.1, "IR": 2.0}},
                "DAY3": {"0": {"mean": 0.1, "std": 0.1, "IR": 1.0}},
            },
        }],
    })

    names = {
        item["data"]["name"]
        for item in list(output.queue)
        if item.get("event") == "artifact"
    }
    assert {
        "ic_series_report", "ic_series_data",
        "ic_statistics_csv", "ic_statistics_data",
        "ic_holding_half_life_report", "ic_holding_half_life_data",
    } <= names
