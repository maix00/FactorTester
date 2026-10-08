from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.cli.commands.research_report_job_binding import freeze_report_binding
from tools.cli.commands.research_report_scope import (
    ensure_authoring,
    resolve_branch_report_scope,
    resolve_history_migration_scope,
)
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring import add_branch_component
from tools.cli.release.research_reporting.authoring.tree_model import load_snapshot
from tools.cli.release.research_reporting.job_artifact_mounts import (
    mount_kind,
    mount_operations,
    provenance_bindings,
)
from tools.cli.release.research_reporting.job_artifact_tables import table_content
from tools.cli.release.research_reporting.job_artifacts import collect_job_report


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content


class _Client:
    def __init__(
        self, artifacts: list[dict], content: dict[str, bytes], *,
        execution_node: str = "trial_execution",
        server_id: str = "public-main", port: int = 8141,
    ) -> None:
        self.artifacts = artifacts
        self.content = content
        self.execution_node = execution_node
        self.server_id = server_id
        self.port = port
        self.downloads: list[str] = []

    def get_job(self, job_id: str) -> dict:
        return {
            "job_id": job_id,
            "status": "succeeded",
            "server_id": self.server_id,
            "execution_server_id": self.server_id,
            "execution_port": self.port,
            "port": self.port,
            "run_spec_hash": "c" * 64,
            "research_binding": {"trial_plan_hash": "b" * 64},
            "report_binding": {
                "report_workspace_id": "report-one",
                "branch_id": "main",
                "report_parent_id": "job-results",
            },
            "evidence": {"job_attempt": {"envelope_hash": "a" * 64}},
        }

    def list_job_artifacts(self, job_id: str) -> list[dict]:
        return self.artifacts

    def job_artifact(self, job_id: str, name: str) -> _Response:
        self.downloads.append(name)
        return _Response(self.content[name])


class _DirectClient(_Client):
    def get_job(self, job_id: str) -> dict:
        return {
            "job_id": job_id,
            "status": "succeeded",
            "run_spec_hash": "c" * 64,
            "research_binding": {"trial_plan_hash": "b" * 64},
            "report_binding": {
                "profile_ref": "profile:maxa",
                "report_workspace_id": "package-1",
                "branch_id": "branch-1",
                "report_id": "report-package-1",
                "report_generation": 1,
                "report_head_hash": "b" * 64,
                "report_parent_id": "direct-trials",
            },
            "evidence": {"job_attempt": {"envelope_hash": "a" * 64}},
        }


def test_only_curated_ic_summary_json_is_a_mountable_report_table() -> None:
    assert mount_kind(
        "ic_statistics_summary_data",
        {"content_type": "application/json"},
    ) == "table"
    assert mount_kind(
        "ic_statistics_data",
        {"content_type": "application/json"},
    ) is None
    assert mount_kind(
        "ic_holding_half_life_data",
        {"content_type": "application/json"},
    ) is None
    assert mount_kind(
        "ic_period_diagnostics_data",
        {"content_type": "application/json"},
    ) == "table"
    for name in (
        "equity_curve_data", "returns_over_time_data",
        "metrics_over_time_data",
    ):
        assert mount_kind(name, {"content_type": "application/json"}) is None


def test_evidence_binding_keeps_the_job_route_metadata() -> None:
    bindings = provenance_bindings(
        "job-evidence",
        {
            "server_id": "remote-main",
            "execution_port": 8000,
            "evidence": {
                "canonical": {
                    "evidence_ref": "evidence:sha256:abc",
                    "title_zh": "终态证据",
                },
            },
        },
        "a" * 64,
    )

    assert [item["kind"] for item in bindings] == ["evidence"]
    assert bindings[0]["data"]["server_id"] == "remote-main"
    assert bindings[0]["data"]["port"] == "8000"


def test_automatic_artifact_mount_is_an_evidence_fragment_section() -> None:
    raw = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    digest = hashlib.sha256(raw).hexdigest()
    mounted, operations = mount_operations(
        component_exists=lambda _: False,
        parent_id="job-result",
        job_id="job-1",
        detail={
            "server_id": "remote-main",
            "execution_port": 8000,
            "evidence": {
                "canonical": {
                    "evidence_ref": "evidence:sha256:abc",
                    "title_zh": "终态证据",
                },
            },
        },
        metadata={
            "name": "equity_curve_report",
            "file_name": "equity.svg",
            "content_type": "image/svg+xml",
            "description": "净值曲线",
        },
        raw=raw,
        kind="image",
    )

    wrapper = next(
        operation for operation in operations
        if operation["op"] == "add"
        and operation["display_kind"] == "evidence_fragment"
    )
    child = next(
        operation for operation in operations
        if operation["op"] == "add" and operation["kind"] == "image"
    )
    assert wrapper["parent_id"] == "job-result"
    assert child["parent_id"] == wrapper["component_id"]
    assert [item["kind"] for item in wrapper["bindings"]] == ["evidence"]
    assert wrapper["bindings"][0]["target_ref"] == "evidence:sha256:abc"
    assert wrapper["bindings"][0]["data"] == {
        "content_hash": digest,
        "server_id": "remote-main",
        "port": "8000",
    }
    assert child["bindings"] == []
    assert mounted["component_id"] == child["component_id"]
    assert mounted["evidence_fragment_id"] == wrapper["component_id"]


def test_collect_job_report_uses_frozen_report_parent(tmp_path: Path, monkeypatch):
    from tools.cli.release.research_reporting.workspace import initialize_report_workspace

    monkeypatch.setenv("FACTORTESTER_JOB_CACHE_ROOT", str(tmp_path / "jobs"))
    client_root = tmp_path / "client"
    workspace_root = tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace_root,
    )
    LocalProfileStore(client_root).save(profile)
    initialize_report_workspace(
        workspace_root=workspace_root,
        report_workspace_id="report-one", report_id="report-one",
        branch_id="main", workspace_id="workspace-1", title="Job 报告",
        branch_ref="report-branch:main",
    )
    scope = resolve_branch_report_scope(
        client_root=client_root, profile_id="maxa",
        report_workspace_id="report-one", branch_id="main",
    )
    add_branch_component(
        package_root=scope.package_root,
        report_workspace_id=scope.report_workspace_id,
        branch_id="main", component_id="job-results", kind="chapter",
        title="测试结果", parent_id=None, body="", content=None,
        display_kind="",
    )
    raw = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    client = _Client(
        [{"name": "equity_curve_report", "file_name": "equity.svg",
          "content_type": "image/svg+xml", "description": "净值曲线"}],
        {"equity_curve_report": raw},
    )
    first = collect_job_report(client, job_id="job-1", scope=scope)
    second = collect_job_report(client, job_id="job-1", scope=scope)
    assert first["report_parent_id"] == "job-results"
    assert len(first["mounted"]) == len(second["mounted"]) == 1
    assert second["downloaded"][0]["cache_hit"] is True
    assert client.downloads == ["equity_curve_report"]


def test_job_table_mount_keeps_only_preview_and_global_source() -> None:
    raw = ("time,value\n" + "".join(f"{index},{index / 10}\n" for index in range(201))).encode()

    value = table_content(raw, "text/csv", source={
        "job_id": "job-1", "artifact_ref": "job-artifact:job-1:fee_detail_csv",
        "filename": "fee_detail.csv", "content_type": "text/csv",
        "content_hash": "a" * 64,
    })

    assert len(value["rows"]) == 200
    assert value["preview"]["is_truncated"] is True
    assert value["source"]["filename"] == "fee_detail.csv"


def test_job_table_mount_marks_wide_preview_as_truncated() -> None:
    raw = (",".join(f"c{index}" for index in range(21)) + "\n"
           + ",".join("1" for _ in range(21)) + "\n").encode()

    value = table_content(raw, "text/csv", source={})

    assert len(value["columns"]) == 20
    assert value["preview"]["is_truncated"] is True
