from __future__ import annotations

import json
from pathlib import Path

from tools.cli.release.research_reporting.document import (
    bindings_path_for,
    load_bindings,
    load_document,
    new_bindings,
    new_document,
    save_bindings,
    save_document,
)
from tools.cli.release.research_reporting.job_artifacts import collect_job_report


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content


class _Client:
    def __init__(self, artifacts: list[dict], content: dict[str, bytes]) -> None:
        self.artifacts = artifacts
        self.content = content

    def get_job(self, job_id: str) -> dict:
        return {
            "job_id": job_id,
            "status": "succeeded",
            "workspace_id": "workspace-1",
            "research_binding": {
                "instance_id": "instance-1", "branch_id": "branch-1",
            },
            "evidence": {
                "job_attempt": {"envelope_hash": "a" * 64},
            },
        }

    def list_job_artifacts(self, job_id: str) -> list[dict]:
        return self.artifacts

    def job_artifact(self, job_id: str, name: str) -> _Response:
        return _Response(self.content[name])


def _report(path: Path) -> None:
    document = new_document("report-1", "因子研究")
    document = __import__(
        "tools.cli.release.research_reporting.document",
        fromlist=["add_component"],
    ).add_component(
        document, component_id="chapter-1", kind="chapter", title="研究结果",
    )
    save_document(path, document)
    save_bindings(bindings_path_for(path), new_bindings(document), document)


def test_collect_job_report_downloads_all_and_mounts_only_tables_images(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _report(report)
    csv_raw = b"metric,value\nsharpe,1.2\n"
    image_raw = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    client = _Client(
        [
            {"name": "fee_detail_csv", "file_name": "fee_detail_csv.csv", "content_type": "text/csv", "description": "手续费明细表"},
            {"name": "equity_curve_report", "file_name": "equity_curve_report.svg", "content_type": "image/svg+xml", "description": "净值曲线图"},
            {"name": "debug_log", "file_name": "debug_log.log", "content_type": "text/plain", "description": "调试日志"},
        ],
        {"fee_detail_csv": csv_raw, "equity_curve_report": image_raw, "debug_log": b"debug"},
    )

    value = collect_job_report(
        client, job_id="job-1", report_file=report,
        output_dir=tmp_path / "jobs" / "job-1",
    )

    assert len(value["downloaded"]) == 3
    assert {item["kind"] for item in value["mounted"]} == {"table", "image"}
    assert (tmp_path / "jobs" / "job-1" / "debug_log.log").read_bytes() == b"debug"
    document = load_document(report)
    special = [item for item in document["components"] if item["kind"] == "special"]
    assert len(special) == 2
    assert {item["display_kind"] for item in special} == {"job-artifact-table", "job-artifact-image"}
    bindings = load_bindings(bindings_path_for(report), document)
    assert {item["kind"] for item in bindings["bindings"]} == {"evidence", "job"}
    assert (tmp_path / "assets").is_dir()


def test_collect_job_report_is_idempotent(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _report(report)
    raw = json.dumps({"sharpe": 1.2}).encode()
    client = _Client(
        [{"name": "metrics_over_time_data", "file_name": "metrics.json", "content_type": "application/json", "description": "指标"}],
        {"metrics_over_time_data": raw},
    )
    first = collect_job_report(client, job_id="job-2", report_file=report)
    second = collect_job_report(client, job_id="job-2", report_file=report)
    assert len(first["mounted"]) == 1
    assert len(second["mounted"]) == 1
    assert len(load_document(report)["components"]) == 2
