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
from tools.cli.release.research_reporting.workspace import initialize_work_package


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
                "work_package_ref": "work-package:package-1",
                "instance_id": "instance-1", "branch_id": "branch-1",
                "execution_node": self.execution_node,
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
                "binding_origin": "agent_direct",
                "work_package_ref": "work-package:package-1",
                "branch_id": "branch-1",
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


def _scope(tmp_path: Path):
    client_root = tmp_path / "client-root"
    workspace_root = tmp_path / "workspace-root"
    store = LocalProfileStore(client_root)
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace_root,
    )
    profile["research_records"] = [{
        "record_id": "package-1", "title": "CLI 报告", "status": "pending",
        "scope": {"factor_families": ["SgCCS"]},
        "factor_family_versions": ["MaxA:SgCCS@1"],
        "agent_id": "research-maxa", "created_at": 1.0, "updated_at": 1.0,
        "workspace_ref": "workspace:workspace-1", "run_ref": "",
        "graph_instance_ref": "work-package:package-1",
        "graph_branch_ref": "graph-branch:instance-1:branch-1",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
        "artifacts": [], "provenance": {"kind": "owned_research"},
    }]
    store.save(profile)
    initialize_work_package(
        workspace_root=workspace_root, work_package_id="package-1",
        branch_id="branch-1", workspace_id="workspace-1", title="CLI 报告",
        branch_ref="graph-branch:instance-1:branch-1",
    )
    scope = resolve_branch_report_scope(
        client_root=client_root, profile_id="maxa", work_package_id="package-1",
        branch_id="branch-1",
    )
    ensure_authoring(scope, node_id="trial_execution")
    return scope


def test_scope_resolves_an_owned_historical_report_branch(
    tmp_path: Path,
) -> None:
    client_root = tmp_path / "client-root"
    workspace_root = tmp_path / "workspace-root"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace_root,
    )
    profile["research_records"] = [{
        "record_id": "package-1", "title": "CLI 报告", "status": "ready",
        "scope": {}, "factor_family_versions": [],
        "agent_id": "research-maxa", "created_at": 1.0, "updated_at": 1.0,
        "workspace_ref": "workspace:workspace-1", "run_ref": "",
        "graph_instance_ref": "work-package:package-1",
        "graph_branch_ref": "graph-branch:instance-new:branch-new",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
        "artifacts": [{
            "artifact_ref": (
                "artifact:research/package-1/branches/branch-old/"
                "authoring/HEAD.json"
            ),
            "format": "report_tree", "status": "ready",
            "content_hash": "a" * 64, "local_ref": "file:///old",
            "index_ref": "", "section_refs": [],
        }],
        "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    (workspace_root / "research" / "package-1").mkdir(parents=True)

    scope = resolve_branch_report_scope(
        client_root=client_root, profile_id="maxa",
        work_package_id="package-1", branch_id="branch-old",
    )

    assert scope.record["record_id"] == "package-1"
    assert scope.branch_ref == "report-branch:branch-old"


def test_history_migration_registers_a_materialized_lineage_branch(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    old_branch = "branch-old"
    old_head = (
        scope.package_root / "branches" / old_branch / "authoring" / "HEAD.json"
    )
    old_head.parent.mkdir(parents=True)
    old_head.write_text("{}", encoding="utf-8")

    historical = resolve_history_migration_scope(
        client_root=scope.client_root, profile_id="maxa",
        work_package_id="package-1", branch_id=old_branch,
    )

    assert historical.record["record_id"] == "package-1"
    assert historical.branch_ref == f"report-branch:{old_branch}"


def test_collect_job_report_mounts_to_immutable_execution_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_JOB_CACHE_ROOT", str(tmp_path / "jobs"))
    scope = _scope(tmp_path)
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

    value = collect_job_report(client, job_id="job-1", scope=scope)

    assert len(value["downloaded"]) == 2
    assert {item["kind"] for item in value["mounted"]} == {"table", "image"}
    assert value["execution_node"] == "trial_execution"
    assert {item["artifact_ref"] for item in value["downloaded"]} == {
        "job-artifact:job-1:fee_detail_csv",
        "job-artifact:job-1:equity_curve_report",
    }
    assert client.downloads == ["fee_detail_csv", "equity_curve_report"]
    snapshot = load_snapshot(
        package_root=scope.package_root, branch_id="branch-1",
    )
    special = [item for item in snapshot["components"] if item["kind"] == "special"]
    result = next(item for item in special if item["display_kind"] == "test_result")
    fragments = [
        item for item in special if item["display_kind"] == "evidence_fragment"
    ]
    assert len(fragments) == 2
    chapter = next(item for item in snapshot["components"] if item["kind"] == "chapter")
    assert result["parent_id"] == chapter["component_id"]
    result_children = [
        item for item in snapshot["components"]
        if item["parent_id"] == result["component_id"]
    ]
    assert {item["kind"] for item in result_children} == {"special"}
    assert {item["display_kind"] for item in result_children} == {
        "evidence_fragment",
    }
    fragment_children = [
        item for item in snapshot["components"]
        if item["parent_id"] in {
            child["component_id"] for child in result_children
        }
    ]
    assert {item["kind"] for item in fragment_children} == {"table", "image"}
    assert all(not item.get("bindings") for item in fragment_children)
    assert {
        item["evidence_fragment_id"] for item in value["mounted"]
    } == {item["component_id"] for item in result_children}
    assert value["result_component_id"] == result["component_id"]
    assert value["report_head"].endswith("/authoring/HEAD.json")
    assert not (scope.package_root / "branches" / "branch-1" / "REPORT.md").exists()
    image = next(item for item in snapshot["head"]["assets"] if item["media_type"] == "image/svg+xml")
    assert image["external_ref"] == "factortester-artifact://jobs/job-1/equity_curve_report"
    assert image["content_hash"] == hashlib.sha256(image_raw).hexdigest()
    assert "factortester://job/" in result["body"]
    job_binding = next(
        item for item in snapshot["bindings"]
        if item["component_id"] == result["component_id"]
        and item["kind"] == "job"
    )
    assert job_binding["data"]["server_id"] == "public-main"
    assert job_binding["data"]["port"] == "8141"
    assert "factortester://evidence/" not in result["body"]
    assert (tmp_path / "jobs" / "job-1" / "fee_detail_csv.csv").is_file()
    assert (tmp_path / "jobs" / "job-1" / "equity_curve_report.svg").is_file()

    add_branch_component(
        package_root=scope.package_root,
        work_package_id=scope.work_package_id,
        branch_id=scope.branch_id,
        component_id="job-1-analysis",
        kind="section",
        title="结果分析",
        parent_id=value["result_component_id"],
        body="解释净值、费用和稳定性",
        content=None,
        display_kind="",
    )
    with_analysis = load_snapshot(
        package_root=scope.package_root, branch_id="branch-1",
    )
    analysis = next(
        item for item in with_analysis["components"]
        if item["component_id"] == "job-1-analysis"
    )
    assert analysis["parent_id"] == value["result_component_id"]


def test_collect_job_report_mounts_one_ic_statistics_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_JOB_CACHE_ROOT", str(tmp_path / "jobs"))
    scope = _scope(tmp_path)
    payload = json.dumps({
        "schema_version": 1,
        "artifact_kind": "ic_statistics_summary",
        "columns": ["factor", "experiment", "mean_ic", "source"],
        "rows": [{
            "factor": "[MmRateOfChg](factortester://factor/factor%3Av1%3Aprofile-maxa%3Apath%3Aidentity%3Aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa%3Abbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)",
            "experiment": "[Job job-ic](factortester://job/job%3Ajob-ic)",
            "mean_ic": 0.12,
            "source": "[原始](factortester://artifact/job-artifact%3Ajob-ic%3Aic_statistics_data)",
        }],
    }).encode()
    client = _Client(
        [
            {
                "name": "ic_statistics_csv",
                "file_name": "ic_statistics_csv.csv",
                "content_type": "text/csv; charset=utf-8",
                "description": "IC 统计表（CSV）",
            },
            {
                "name": "ic_statistics_data",
                "file_name": "ic_statistics_data.json",
                "content_type": "application/json",
                "description": "IC 统计数据（JSON）",
            },
            {
                "name": "ic_statistics_summary_data",
                "file_name": "ic_statistics_summary_data.json",
                "content_type": "application/json",
                "description": "IC 统计摘要表（报告 artifact，JSON）",
            },
        ],
        {
            "ic_statistics_csv": b"factor_alias,factor_ref,mean_ic\nA,ref,0.12\n",
            "ic_statistics_data": payload,
            "ic_statistics_summary_data": payload,
        },
    )

    value = collect_job_report(client, job_id="job-ic", scope=scope)

    assert [(item["name"], item["kind"]) for item in value["mounted"]] == [
        ("ic_statistics_summary_data", "table"),
    ]
    assert client.downloads == ["ic_statistics_summary_data"]
    assert {item["name"] for item in value["skipped"]} == {
        "ic_statistics_csv", "ic_statistics_data",
    }


def test_collect_direct_job_report_mounts_to_explicit_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_JOB_CACHE_ROOT", str(tmp_path / "jobs"))
    scope = _scope(tmp_path)
    initial = load_snapshot(
        package_root=scope.package_root, branch_id="branch-1",
    )
    chapter_id = next(
        item["component_id"] for item in initial["components"]
        if item["kind"] == "chapter"
    )
    add_branch_component(
        package_root=scope.package_root,
        work_package_id=scope.work_package_id,
        branch_id=scope.branch_id,
        component_id="direct-trials",
        kind="section",
        title="图外试验",
        parent_id=chapter_id,
        body="Agent 自主运行但不推动研究图",
        content=None,
        display_kind="",
    )
    client = _DirectClient([], {})

    value = collect_job_report(client, job_id="job-direct", scope=scope)

    snapshot = load_snapshot(
        package_root=scope.package_root, branch_id="branch-1",
    )
    result = next(
        item for item in snapshot["components"]
        if item["component_id"] == value["result_component_id"]
    )
    assert value["report_parent_id"] == "direct-trials"
    assert value["execution_node"] == ""
    assert result["parent_id"] == "direct-trials"
    assert "factortester://trial_plan/" in result["body"]
    assert "factortester://run_spec/" in result["body"]


def test_direct_report_binding_freezes_an_existing_parent(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    initial = load_snapshot(
        package_root=scope.package_root, branch_id="branch-1",
    )
    parent_id = next(
        item["component_id"] for item in initial["components"]
        if item["kind"] == "chapter"
    )

    binding = freeze_report_binding(
        scope,
        trial_binding={"binding_origin": "agent_direct"},
        report_parent_id=parent_id,
    )

    assert binding["binding_origin"] == "agent_direct"
    assert binding["report_parent_id"] == parent_id
    assert "instance_id" not in binding


def test_direct_report_binding_rejects_a_non_container_parent(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    initial = load_snapshot(
        package_root=scope.package_root, branch_id="branch-1",
    )
    chapter_id = next(
        item["component_id"] for item in initial["components"]
        if item["kind"] == "chapter"
    )
    add_branch_component(
        package_root=scope.package_root,
        work_package_id=scope.work_package_id,
        branch_id=scope.branch_id,
        component_id="plain-entry",
        kind="entry",
        title="",
        parent_id=chapter_id,
        body="普通正文",
        content=None,
        display_kind="",
    )

    with pytest.raises(ValueError, match="container"):
        freeze_report_binding(
            scope,
            trial_binding={"binding_origin": "agent_direct"},
            report_parent_id="plain-entry",
        )


def test_collect_job_report_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_JOB_CACHE_ROOT", str(tmp_path / "jobs"))
    scope = _scope(tmp_path)
    raw = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    client = _Client(
        [{"name": "metrics_over_time_report", "file_name": "metrics.svg", "content_type": "image/svg+xml", "description": "指标", "content_hash": hashlib.sha256(raw).hexdigest()}],
        {"metrics_over_time_report": raw},
    )
    first = collect_job_report(client, job_id="job-2", scope=scope)
    second = collect_job_report(client, job_id="job-2", scope=scope)
    assert len(first["mounted"]) == len(second["mounted"]) == 1
    snapshot = load_snapshot(
        package_root=scope.package_root, branch_id="branch-1",
    )
    assert len(snapshot["components"]) == 4
    assert client.downloads == ["metrics_over_time_report"]
    assert second["downloaded"][0]["cache_hit"] is True


def test_collect_job_report_rejects_missing_execution_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_JOB_CACHE_ROOT", str(tmp_path / "jobs"))
    scope = _scope(tmp_path)
    client = _Client([], {}, execution_node="")
    with pytest.raises(ValueError, match="未冻结执行节点"):
        collect_job_report(client, job_id="job-legacy", scope=scope)


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
