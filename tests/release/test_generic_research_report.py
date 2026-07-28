from __future__ import annotations

import json
import hashlib

import pytest
from click.testing import CliRunner

from tools.cli.release.research_reporting.document import (
    add_binding,
    add_component,
    document_manifest,
    new_bindings,
    new_document,
    render_markdown,
    validate_document,
)
from tools.cli.release.research_reporting.authoring import (
    ensure_branch_report_chapter,
)
from tools.cli.release.research_reporting.graph_adapter import (
    enrich_graph_packet,
    validate_report_tasks,
)
from tools.cli.commands.research_report import report as report_cli
from tools.cli.commands import research_report_authoring
from tools.cli.commands import research_report_component
from tools.cli.commands import research_report_inspection
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.workspace import initialize_work_package


def test_report_components_are_content_only() -> None:
    value = new_document("doc-1", "Research", language="en")
    value = add_component(
        value, component_id="chapter", kind="chapter", title="Findings",
    )
    value = add_component(
        value, component_id="table", kind="table", parent_id="chapter",
        title="Results", content={"columns": ["A", "B"], "rows": [["1", "2"]]},
    )
    assert set(value) == {
        "schema_version", "document_id", "title", "language", "revision",
        "components", "assets",
    }
    assert "graph" not in json.dumps(value, ensure_ascii=False).lower()
    text = render_markdown(value).decode()
    assert "# Findings" in text
    assert "| A | B |" in text


def test_graph_packet_contains_references_not_evidence_payload() -> None:
    packet = enrich_graph_packet({
        "graph": "factor-research@v1",
        "node": {"node_id": "validation"},
        "candidate_edges": [{
            "edge_id": "validation__trial",
            "to_node": "trial",
            "report_requirement_refs": ["report.edge.validation__trial"],
        }],
    })
    report = packet["report_packet"]
    assert report["required_tasks"][0]["task_ref"] == "report.edge.validation__trial"
    assert "evidence_payload" not in json.dumps(report, ensure_ascii=False).lower()
    assert "data_policy" in report


def test_profile_report_chapters_follow_node_entry_without_checkpoint(
    tmp_path,
) -> None:
    initialize_work_package(
        workspace_root=tmp_path,
        work_package_id="wp-1",
        branch_id="branch-1",
        workspace_id="workspace-1",
        title="动量因子研究",
        branch_ref="graph-branch:physical-1:branch-1",
    )
    first = ensure_branch_report_chapter(
        workspace_root=tmp_path,
        work_package_id="wp-1",
        title="动量因子研究",
        node_id="hypothesis_preregistration",
        branch_id="branch-1",
        branch_ref="graph-branch:physical-1:branch-1",
    )
    second = ensure_branch_report_chapter(
        workspace_root=tmp_path,
        work_package_id="wp-1",
        title="动量因子研究",
        node_id="data_contract",
        branch_id="branch-1",
        branch_ref="graph-branch:physical-1:branch-1",
    )
    repeated = ensure_branch_report_chapter(
        workspace_root=tmp_path,
        work_package_id="wp-1",
        title="动量因子研究",
        node_id="data_contract",
        branch_id="branch-1",
        branch_ref="graph-branch:physical-1:branch-1",
    )

    document = json.loads(
        first["paths"]["document"].read_text(encoding="utf-8")
    )
    assert [item["kind"] for item in document["components"]] == [
        "chapter", "chapter",
    ]
    assert [item["title"] for item in document["components"]] == [
        "假设登记", "数据契约",
    ]
    assert first["chapter_sync"]["created_count"] == 1
    assert second["chapter_sync"]["created_count"] == 1
    assert repeated["chapter_sync"]["created_count"] == 0
    assert repeated["descriptor"]["format"] == "document"


def test_graph_report_completion_uses_external_bindings() -> None:
    packet = enrich_graph_packet({
        "graph": "factor-research@v1",
        "node": {"node_id": "validation"},
        "candidate_edges": [{
            "edge_id": "e",
            "report_requirement_refs": ["report.edge.e"],
        }],
    })
    document = add_component(
        new_document("doc", "R"), component_id="s", kind="section", title="S",
    )
    bindings = new_bindings(document)
    assert validate_report_tasks(packet, bindings)["valid"] is False
    bindings = add_binding(
        bindings, document, component_id="s", binding_id="req",
        kind="report_requirement", target_ref="report.edge.e",
    )
    assert validate_report_tasks(packet, bindings)["valid"] is True


def test_content_document_rejects_old_graph_bound_shape() -> None:
    with pytest.raises(ValueError, match="content-only v2"):
        validate_document({
            "schema_version": 1, "document_id": "old", "title": "Old",
            "language": "en", "revision": 0, "metadata": {},
            "components": [], "chips": [], "assets": [],
        })


def test_new_content_rejects_graph_binding_fields() -> None:
    with pytest.raises(ValueError, match="external binding field"):
        add_component(
            new_document("doc-bound", "R"), component_id="s",
            kind="entry", title="S", content={"graph_ref": "graph:v1"},
        )


def test_report_manifest_is_content_free_and_stable() -> None:
    value = add_component(
        new_document("doc-manifest", "R"),
        component_id="s", kind="section", title="S", body="private body",
    )
    manifest = document_manifest(value)
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert manifest["document_hash"]
    assert "private body" not in serialized
    assert "component_refs" in manifest
    assert document_manifest(value) == manifest


def _scoped_report(tmp_path):
    client_root = tmp_path / "client-root"
    workspace_root = tmp_path / "workspace-root"
    store = LocalProfileStore(client_root)
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=workspace_root,
    )
    profile["research_records"] = [{
        "record_id": "package-1",
        "title": "CLI 报告",
        "status": "pending",
        "scope": {"factor_families": ["SgCCS"]},
        "factor_family_versions": ["MaxA:SgCCS@1"],
        "agent_id": "research-maxa",
        "created_at": 1.0,
        "updated_at": 1.0,
        "workspace_ref": "workspace:workspace-1",
        "run_ref": "",
        "graph_instance_ref": "work-package:package-1",
        "graph_branch_ref": "graph-branch:instance-1:branch-1",
        "checkpoint_ref": "",
        "evidence_refs": [],
        "timeline_refs": [],
        "artifacts": [],
        "provenance": {"kind": "owned_research"},
    }]
    store.save(profile)
    initialize_work_package(
        workspace_root=workspace_root,
        work_package_id="package-1",
        branch_id="branch-1",
        workspace_id="workspace-1",
        title="CLI 报告",
        branch_ref="graph-branch:instance-1:branch-1",
    )
    return client_root, workspace_root


def _scope_args() -> list[str]:
    return [
        "--profile", "maxa", "--work-package-id", "package-1",
        "--branch-id", "branch-1",
    ]


def test_report_cli_authors_content_and_sidecar_bindings(tmp_path, monkeypatch) -> None:
    client_root, workspace_root = _scoped_report(tmp_path)
    monkeypatch.setattr(
        research_report_authoring, "load_profile_root", lambda path: client_root,
    )
    monkeypatch.setattr(
        research_report_inspection, "load_profile_root", lambda path: client_root,
    )
    monkeypatch.setattr(
        research_report_component, "load_profile_root", lambda path: client_root,
    )
    runner = CliRunner()
    created = runner.invoke(report_cli, [
        "create", *_scope_args(), "--json",
    ])
    assert created.exit_code == 0, created.output
    added = runner.invoke(report_cli, [
        "add", *_scope_args(), "--component-id", "findings", "--kind", "chapter",
        "--title", "Findings", "--json",
    ])
    assert added.exit_code == 0, added.output
    bound = runner.invoke(report_cli, [
        "chip", *_scope_args(), "findings", "--chip-id", "job-1", "--kind", "job",
        "--target-ref", "job:1", "--json",
    ])
    assert bound.exit_code == 0, bound.output
    checked = runner.invoke(report_cli, ["validate", *_scope_args(), "--json"])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output)["bindings"] == 1
    document = (
        workspace_root / "research" / "package-1" / "branches" / "branch-1"
        / "authoring" / "DOCUMENT.json"
    )
    content = json.loads(document.read_text(encoding="utf-8"))
    sidecar = json.loads(
        document.with_name("BINDINGS.json").read_text(encoding="utf-8")
    )
    assert "bindings" not in content
    assert sidecar["bindings"][0]["target_ref"] == "job:1"


def test_report_cli_authors_math_and_result_components(tmp_path, monkeypatch) -> None:
    client_root, workspace_root = _scoped_report(tmp_path)
    monkeypatch.setattr(
        research_report_authoring, "load_profile_root", lambda path: client_root,
    )
    monkeypatch.setattr(
        research_report_inspection, "load_profile_root", lambda path: client_root,
    )
    monkeypatch.setattr(
        research_report_component, "load_profile_root", lambda path: client_root,
    )
    runner = CliRunner()
    result_content = tmp_path / "result.json"
    code_file = tmp_path / "factor.py"
    result_content.write_text(json.dumps({"sharpe": 1.25}), encoding="utf-8")
    code_file.write_text("def signal(price):\n    return price\n", encoding="utf-8")
    assert runner.invoke(report_cli, [
        "create", *_scope_args(), "--json",
    ]).exit_code == 0
    added_math = runner.invoke(report_cli, [
        "add", *_scope_args(), "--component-id", "equation", "--kind", "math",
        "--title", "Signal", "--latex", r"s_t = z_t / \sigma_t",
        "--fallback", "normalized signal", "--json",
    ])
    assert added_math.exit_code == 0, added_math.output
    added_code = runner.invoke(report_cli, [
        "add", *_scope_args(), "--component-id", "source", "--kind", "code",
        "--title", "Implementation", "--language", "python",
        "--code-file", str(code_file), "--json",
    ])
    assert added_code.exit_code == 0, added_code.output
    added_result = runner.invoke(report_cli, [
        "add", *_scope_args(), "--component-id", "summary", "--kind", "result",
        "--title", "Backtest", "--content-file", str(result_content), "--json",
    ])
    assert added_result.exit_code == 0, added_result.output
    rendered = runner.invoke(report_cli, [
        "render", *_scope_args(), "--json",
    ])
    assert rendered.exit_code == 0, rendered.output
    branch_root = (
        workspace_root / "research" / "package-1" / "branches" / "branch-1"
    )
    markdown = (branch_root / "REPORT.md").read_text(encoding="utf-8")
    assert "$$\ns_t = z_t / \\sigma_t\n$$" in markdown
    assert "```python\ndef signal(price):" in markdown
    assert '"sharpe": 1.25' in markdown
    assert "<!-- FACTORTESTER AUTHORING BEGIN -->" in markdown
    assert not (branch_root / "authoring" / "REPORT.md").exists()
    index = json.loads(
        (workspace_root / "research" / "package-1" / "INDEX.json").read_text(
            encoding="utf-8"
        )
    )
    entry = next(item for item in index["branches"] if item["branch_id"] == "branch-1")
    assert entry["content_hash"] == hashlib.sha256(
        (branch_root / "REPORT.md").read_bytes()
    ).hexdigest()
