from __future__ import annotations

import json
from pathlib import Path

from cli_anything.factortester_research.factortester_research_cli import cli
from click.testing import CliRunner

from tools.cli.release.research_reporting.document import (
    add_component,
    bindings_path_for,
    ensure_report_chapters,
    new_bindings,
    new_document,
    save_bindings,
    save_document,
)


def _packet() -> dict:
    return {
        "node": {"node_id": "factor_semantics"},
        "report_packet": {
            "required_tasks": [{
                "task_ref": "report.node.factor_semantics.action",
                "node_id": "factor_semantics",
                "chapter_ref": "node:factor_semantics",
                "chapter_title_zh": "因子语义",
            }],
        },
    }


def test_ensure_report_chapters_is_idempotent_and_sidecar_bound() -> None:
    document = new_document("research", "研究报告")
    bindings = new_bindings(document)

    document, bindings, first = ensure_report_chapters(
        document, bindings, _packet(),
    )
    document, bindings, second = ensure_report_chapters(
        document, bindings, _packet(),
    )

    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert second["existing_count"] == 1
    assert len(document["components"]) == 1
    assert "chapter_ref" not in document["components"][0]
    assert bindings["bindings"][0]["data"] == {
        "role": "report_chapter",
        "chapter_ref": "node:factor_semantics",
    }


def test_chapter_anchors_are_isolated_by_branch_in_one_content_document() -> None:
    document = new_document("research", "研究报告")
    bindings = new_bindings(document)

    first_packet = {**_packet(), "research_scope": {
        "branch_ref": "graph-branch:i:one",
    }}
    second_packet = {**_packet(), "research_scope": {
        "branch_ref": "graph-branch:i:two",
    }}
    document, bindings, _ = ensure_report_chapters(
        document, bindings, first_packet,
    )
    document, bindings, _ = ensure_report_chapters(
        document, bindings, second_packet,
    )

    assert len(document["components"]) == 2
    assert {
        item["data"]["branch_ref"] for item in bindings["bindings"]
    } == {"graph-branch:i:one", "graph-branch:i:two"}


def test_cycle_next_can_sync_chapter_without_agent_report_add(
    monkeypatch, tmp_path: Path,
) -> None:
    report_file = tmp_path / "report.json"
    bindings_file = report_file.with_suffix(".json.bindings.json")
    document = new_document("research", "研究报告")
    report_file.write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )
    bindings_file.write_text(
        json.dumps(new_bindings(document), ensure_ascii=False), encoding="utf-8"
    )

    class Result:
        returncode = 0
        stderr = ""
        argv = ["research-graph", "next", "instance-1", "branch-1"]
        stdout = json.dumps({
            "graph": "factor-research@v2",
            "node": {"node_id": "factor_semantics"},
            "candidate_edges": [],
            "current_obligations": [],
            "next_bytes": 100,
        })

    from cli_anything.factortester_research.commands import cycle as cycle_commands
    monkeypatch.setattr(cycle_commands, "run_factortester", lambda *args, **kwargs: Result())

    result = CliRunner().invoke(
        cli,
        [
            "cycle", "next", "instance-1", "branch-1",
            "--report-file", str(report_file), "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["report_packet"]["chapter_sync"]["created_count"] == 1
    saved = json.loads(report_file.read_text(encoding="utf-8"))
    assert [item["kind"] for item in saved["components"]] == ["chapter"]


def test_report_fork_clones_content_and_sidecar_with_new_opaque_document_id(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.json"
    target = tmp_path / "branch-b.json"
    document = add_component(
        new_document("research", "研究报告"),
        component_id="chapter-a", kind="chapter", title="假设登记",
    )
    save_document(source, document)
    save_bindings(
        bindings_path_for(source), new_bindings(document), document,
    )

    result = CliRunner().invoke(
        cli,
        [
            "report", "fork", "--source-file", str(source),
            "--output-file", str(target), "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    cloned = json.loads(target.read_text(encoding="utf-8"))
    assert cloned["document_id"] != document["document_id"]
    assert payload["component_count"] == 1
    assert target.with_suffix(".json.bindings.json").exists()


def test_report_cli_writes_and_renders_local_code_component(tmp_path: Path) -> None:
    report_file = tmp_path / "report.json"
    source_file = tmp_path / "factor.py"
    source_file.write_text(
        "class DemoFactor:\n    return '/Users/private/data'\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    created = runner.invoke(cli, [
        "report", "create", "--file", str(report_file),
        "--document-id", "research", "--title", "研究报告", "--json",
    ])
    assert created.exit_code == 0, created.output
    added = runner.invoke(cli, [
        "report", "add", "--file", str(report_file),
        "--component-id", "source", "--kind", "code", "--title", "因子源码",
        "--language", "python", "--code-file", str(source_file), "--json",
    ])
    assert added.exit_code == 0, added.output
    output = tmp_path / "report.md"
    rendered = runner.invoke(cli, [
        "report", "render-document", "--file", str(report_file),
        "--output", str(output), "--json",
    ])
    assert rendered.exit_code == 0, rendered.output
    text = output.read_text(encoding="utf-8")
    assert "```python" in text
    assert "class DemoFactor:" in text
    assert "/Users/private/data" in text
    manifest = runner.invoke(cli, [
        "report", "manifest", "--file", str(report_file), "--json",
    ])
    assert manifest.exit_code == 0, manifest.output
    assert "/Users/private/data" not in manifest.output
    assert "class DemoFactor:" not in manifest.output
