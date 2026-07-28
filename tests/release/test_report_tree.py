"""Acceptance seams for the revisioned local report tree."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring import tree_navigation
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_binding,
    add_component,
    apply_batch,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_render import (
    render_tree_markdown,
)


def test_head_switches_only_after_complete_tree_write(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    first_bytes = created["paths"]["head"].read_bytes()
    first_head = json.loads(created["paths"]["head"].read_text(encoding="utf-8"))

    added = add_component(
        package_root=package, branch_id="main", component_id="chapter-a",
        kind="chapter", title="假设登记", parent_id=None, body="正文", content=None,
        display_kind="",
    )

    second_head = json.loads(created["paths"]["head"].read_text(encoding="utf-8"))
    assert first_head["revision"] == 0
    assert second_head["revision"] == 1
    assert second_head["parent_revision"] == first_head["revision"]
    assert second_head["root_ref"] != first_head["root_ref"]
    assert (created["paths"]["revisions"] / "0.json").read_bytes() == first_bytes
    assert (created["paths"]["revisions"] / "1.json").read_bytes() == (
        created["paths"]["head"].read_bytes()
    )
    assert [item["component_id"] for item in added["components"]] == ["chapter-a"]


def test_binding_is_coherent_with_the_component_revision(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    add_component(
        package_root=package, branch_id="main", component_id="finding",
        kind="entry", title="发现", parent_id=None, body="", content=None,
        display_kind="",
    )

    updated = add_binding(
        package_root=package, branch_id="main", component_id="finding",
        binding={
            "binding_id": "evidence-1", "kind": "evidence",
            "target_ref": "evidence:job-1", "label": "回测证据", "data": {},
        },
    )

    snapshot = load_snapshot(package_root=package, branch_id="main")
    assert updated["head"]["revision"] == snapshot["head"]["revision"] == 2
    assert snapshot["bindings"] == [{
        "binding_id": "evidence-1", "kind": "evidence",
        "target_ref": "evidence:job-1", "label": "回测证据", "data": {},
        "component_id": "finding",
    }]


def test_batch_adds_related_content_under_one_revision(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )

    value = apply_batch(
        package_root=package, branch_id="main", operations=[
            {
                "op": "add", "component_id": "chapter", "kind": "chapter",
                "title": "试验执行", "body": "", "content": None,
                "display_kind": "", "bindings": [],
            },
            {
                "op": "add", "component_id": "result", "kind": "table",
                "title": "结果", "parent_id": "chapter", "body": "",
                "content": {"columns": ["指标"], "rows": [["Sharpe"]]},
                "display_kind": "", "bindings": [{
                    "binding_id": "job", "kind": "job", "target_ref": "job:1",
                    "label": "回测", "data": {},
                }],
            },
        ],
    )

    assert value["head"]["revision"] == 1
    assert [item["component_id"] for item in value["components"]] == ["chapter", "result"]
    assert value["bindings"][0]["component_id"] == "result"


def test_failed_batch_keeps_head_and_component_identity_unchanged(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    before = created["paths"]["head"].read_bytes()

    with pytest.raises(ValueError, match="unknown report batch operation"):
        apply_batch(
            package_root=package,
            branch_id="main",
            operations=[
                {
                    "op": "add", "component_id": "recoverable",
                    "kind": "entry", "title": "可重试", "body": "",
                    "content": None, "display_kind": "", "bindings": [],
                },
                {"op": "unsupported"},
            ],
        )

    assert created["paths"]["head"].read_bytes() == before
    retried = apply_batch(
        package_root=package,
        branch_id="main",
        operations=[{
            "op": "add", "component_id": "recoverable", "kind": "entry",
            "title": "可重试", "body": "", "content": None,
            "display_kind": "", "bindings": [],
        }],
    )
    assert [item["component_id"] for item in retried["components"]] == [
        "recoverable",
    ]


def test_committed_locator_avoids_full_tree_scan_for_nested_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    for component_id, parent_id in [
        ("chapter", None), ("section", "chapter"), ("entry", "section"),
    ]:
        add_component(
            package_root=package, branch_id="main", component_id=component_id,
            kind="entry" if component_id == "entry" else component_id,
            title=component_id, parent_id=parent_id, body="", content=None,
            display_kind="",
        )

    def fail_scan(*_args, **_kwargs):
        raise AssertionError("committed locator unexpectedly fell back to scan")

    monkeypatch.setattr(tree_navigation, "scan_path", fail_scan)
    add_binding(
        package_root=package, branch_id="main", component_id="entry",
        binding={
            "binding_id": "job", "kind": "job", "target_ref": "job:1",
            "label": "", "data": {},
        },
    )


def test_special_job_outputs_project_as_table_and_remote_image(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    apply_batch(
        package_root=package, branch_id="main", operations=[
            {"op": "asset", "asset": {
                "asset_ref": "job-artifact:job-1:equity", "media_type": "image/svg+xml",
                "filename": "equity.svg", "caption": "净值", "alt_text": "净值图",
                "external_ref": "factortester-artifact://jobs/job-1/equity",
                "content_hash": "a" * 64,
            }},
            {"op": "add", "component_id": "table", "kind": "special",
             "title": "统计表", "body": "", "display_kind": "job-artifact-table",
             "content": {"columns": ["指标", "值"], "rows": [["Sharpe", "1.2"]]}, "bindings": []},
            {"op": "add", "component_id": "image", "kind": "special",
             "title": "净值图", "body": "", "display_kind": "job-artifact-image",
             "content": {"asset_ref": "job-artifact:job-1:equity"}, "bindings": []},
        ],
    )
    rendered = render_tree_markdown(load_snapshot(package_root=package, branch_id="main")).decode()
    assert "| 指标 | 值 |" in rendered
    assert "![净值图](factortester-artifact://jobs/job-1/equity)" in rendered
