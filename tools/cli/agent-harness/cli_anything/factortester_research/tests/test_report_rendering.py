"""Deterministic, cold-path research report acceptance tests."""

from __future__ import annotations

from copy import deepcopy
import json

from click.testing import CliRunner
import pytest

from cli_anything.factortester_research.factortester_research_cli import cli
from cli_anything.factortester_research.core.reporting import (
    MarkdownReportTarget,
    canonical_report_snapshot,
    render_branch_report,
)
from cli_anything.factortester_research.core.reporting import writer


def _snapshot() -> dict:
    return {
        "schema_version": 1,
        "workspace_id": "workspace-maxa",
        "work_package_id": "sgccs-review",
        "branch_id": "branch-sgccs",
        "title": "SgCCS bounded research report",
        "status": "blocked",
        "graph_ref": "factor-research@5:sha256:graph",
        "methodology_hash": "1" * 64,
        "decision_contract_hash": "2" * 64,
        "trial_plan_hash": "3" * 64,
        "factor_family_versions": ["MaxA:SgCCS@7"],
        "sections": [{
            "section_id": "current-state",
            "title": "Current evidence state",
            "body": "The latest bounded decision remains blocked.",
            "evidence_refs": ["evidence:job-attempt-1"],
            "asset_refs": ["asset:equity-curve", "asset:unavailable"],
        }],
        "evidence_refs": ["evidence:job-attempt-1"],
        "assets": [{
            "asset_ref": "asset:equity-curve",
            "content_hash": "4" * 64,
            "media_type": "image/png",
            "filename": f"{'4' * 64}.png",
            "caption": "Reviewed equity curve",
            "alt_text": "Equity curve over the declared sample",
            "provenance_refs": ["evidence:job-attempt-1"],
            "availability": "available",
        }, {
            "asset_ref": "asset:unavailable",
            "content_hash": "5" * 64,
            "media_type": "application/json",
            "filename": f"{'5' * 64}.json",
            "caption": "Restricted detail",
            "alt_text": "",
            "provenance_refs": ["evidence:restricted"],
            "availability": "unauthorized",
        }],
        "gaps": [{
            "gap_ref": "capability:performance.bootstrap-sharpe",
            "reason": "No approved implementation is available.",
        }],
    }


def test_markdown_is_byte_stable_and_contains_only_bounded_refs() -> None:
    snapshot = canonical_report_snapshot(_snapshot())
    target = MarkdownReportTarget()

    first = target.render(snapshot)
    second = target.render(deepcopy(snapshot))

    assert first == second
    text = first.decode()
    assert snapshot["source_hash"] in text
    assert "evidence:job-attempt-1" in text
    assert "MaxA:SgCCS@7" in text
    assert (
        "![Equity curve over the declared sample]"
        f"(../../assets/{'4' * 64}.png)"
    ) in text
    assert "`asset:unavailable` — unauthorized" in text
    assert "performance.bootstrap-sharpe" in text


def test_incremental_render_does_not_rewrite_unchanged_report(
    tmp_path,
) -> None:
    snapshot = _snapshot()

    first = render_branch_report(snapshot, workspace_root=tmp_path)
    stat_before = first["path"].stat()
    second = render_branch_report(snapshot, workspace_root=tmp_path)
    stat_after = second["path"].stat()

    assert first["changed"] is True
    assert second["changed"] is False
    assert first["content_hash"] == second["content_hash"]
    assert stat_before.st_mtime_ns == stat_after.st_mtime_ns
    assert stat_before.st_ino == stat_after.st_ino


def test_failed_atomic_replace_preserves_previous_complete_report(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot = _snapshot()
    first = render_branch_report(snapshot, workspace_root=tmp_path)
    previous = first["path"].read_bytes()
    snapshot["sections"][0]["body"] = "Changed bounded state."
    monkeypatch.setattr(
        writer.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("injected failure")),
    )

    with pytest.raises(OSError, match="injected failure"):
        render_branch_report(snapshot, workspace_root=tmp_path)

    assert first["path"].read_bytes() == previous


@pytest.mark.parametrize(
    "prohibited",
    [
        {"factor_source": "secret implementation"},
        {"nested": {"raw_stdout": "unbounded"}},
        {"expression_tree": {"operator": "private"}},
        {"credentials": {"token": "secret"}},
    ],
)
def test_snapshot_rejects_prohibited_source_and_heavy_payloads(
    prohibited,
) -> None:
    snapshot = _snapshot()
    snapshot["sections"][0].update(prohibited)

    with pytest.raises(ValueError, match="prohibited report field"):
        canonical_report_snapshot(snapshot)


def test_renderer_interface_does_not_require_pdf_or_chart_dependency() -> None:
    target = MarkdownReportTarget()

    assert target.media_type == "text/markdown"
    assert target.extension == ".md"
    assert not hasattr(target, "database")
    assert not hasattr(target, "client")


def test_report_cli_renders_snapshot_without_server_access(tmp_path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()))
    workspace_root = tmp_path / "workspace"

    result = CliRunner().invoke(cli, [
        "report",
        "render",
        "--snapshot-file",
        str(snapshot_path),
        "--workspace-root",
        str(workspace_root),
        "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["changed"] is True
    assert payload["path"].endswith(
        "research/branches/branch-sgccs/REPORT.md"
    )
