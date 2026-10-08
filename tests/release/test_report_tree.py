"""Acceptance seams for the revisioned local report tree."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring import (
    tree_changes,
    tree_model,
    tree_navigation,
)
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
from tools.cli.release.research_reporting.authoring.tree_projection import (
    load_chapter_snapshot,
    load_report_index,
)
from tools.cli.release.research_reporting.authoring.tree_schema import (
    validate_node,
)


def _schema_node(kind: str, *, title: str) -> dict[str, object]:
    content: object = None
    if kind == "list":
        content = {
            "style": "unordered",
            "items": [{"text": "样本封存", "depth": 0}],
        }
    elif kind == "table":
        content = {"columns": ["指标"], "rows": [["样本数"]]}
    elif kind == "image":
        content = {"asset_ref": "asset-1"}
    elif kind == "code":
        content = {"language": "python", "code": "value = 1"}
    elif kind == "math":
        content = {"latex": "r_t", "fallback": ""}
    elif kind == "result":
        content = {"status": "accepted"}
    return {
        "schema_version": 1,
        "node_id": f"node-{kind}",
        "kind": kind,
        "title": title,
        "body": "",
        "content": content,
        "display_kind": "grill_resolution" if kind == "special" else "",
        "created_at": 1.0,
        "children": [],
        "bindings": [],
    }


@pytest.mark.parametrize(
    "kind", ["entry", "list", "table", "image", "code", "math", "result"],
)
def test_content_components_allow_an_empty_title(kind: str) -> None:
    assert validate_node(_schema_node(kind, title=""))["title"] == ""


@pytest.mark.parametrize(
    "kind", ["chapter", "section", "subsection", "special"],
)
def test_structure_nodes_require_a_title(kind: str) -> None:
    with pytest.raises(ValueError, match="node.title"):
        validate_node(_schema_node(kind, title=""))


@pytest.mark.parametrize(
    "title", ["正文", "表格", "列表", "Body", " TABLE ", "list"],
)
@pytest.mark.parametrize(
    "kind", ["chapter", "section", "subsection", "special"],
)
def test_structure_nodes_reject_content_kind_labels(
    kind: str, title: str,
) -> None:
    with pytest.raises(ValueError, match="content-kind label"):
        validate_node(_schema_node(kind, title=title))


def test_titleless_content_component_renders_without_an_empty_heading(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    add_component(
        package_root=package, branch_id="main", component_id="chapter",
        kind="chapter", title="验证结果", parent_id=None, body="",
        content=None, display_kind="",
    )
    add_component(
        package_root=package, branch_id="main", component_id="finding",
        kind="entry", title="", parent_id="chapter", body="收益为正",
        content=None, display_kind="",
    )

    rendered = render_tree_markdown(
        load_snapshot(package_root=package, branch_id="main"),
    ).decode()

    assert "# 验证结果" in rendered
    assert "#### \n" not in rendered
    assert "收益为正" in rendered


def test_report_index_and_chapter_loader_do_not_require_full_snapshot(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    add_component(
        package_root=package, branch_id="main", component_id="chapter-a",
        kind="chapter", title="第一章", parent_id=None, body="",
        content=None, display_kind="",
    )
    add_component(
        package_root=package, branch_id="main", component_id="entry-a",
        kind="entry", title="条目", parent_id="chapter-a", body="内容",
        content=None, display_kind="",
    )
    add_component(
        package_root=package, branch_id="main", component_id="chapter-b",
        kind="chapter", title="第二章", parent_id=None, body="",
        content=None, display_kind="",
    )

    index = load_report_index(package_root=package, branch_id="main")
    chapter = load_chapter_snapshot(
        package_root=package, branch_id="main", chapter_id="chapter-a",
    )

    assert [item["component_id"] for item in index["chapter_descriptors"]] == [
        "chapter-a", "chapter-b",
    ]
    assert [item["component_id"] for item in chapter["components"]] == [
        "chapter-a", "entry-a",
    ]


def test_add_component_can_insert_before_an_existing_sibling(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    add_component(
        package_root=package, branch_id="main", component_id="chapter",
        kind="chapter", title="验证结果", parent_id=None, body="",
        content=None, display_kind="",
    )
    for component_id in ("finding-a", "finding-c"):
        add_component(
            package_root=package, branch_id="main",
            component_id=component_id, kind="entry", title="",
            parent_id="chapter", body=component_id, content=None,
            display_kind="",
        )

    saved = add_component(
        package_root=package, branch_id="main", component_id="finding-b",
        kind="entry", title="", parent_id="chapter", body="finding-b",
        content=None, display_kind="", before_component_id="finding-c",
    )

    assert [
        item["component_id"] for item in saved["components"]
        if item["parent_id"] == "chapter"
    ] == ["finding-a", "finding-b", "finding-c"]


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
    assert first_head["generation"] == 0
    assert second_head["generation"] == 1
    assert second_head["root_ref"] != first_head["root_ref"]
    assert "revisions" not in created["paths"]
    assert first_bytes != created["paths"]["head"].read_bytes()
    assert [item["component_id"] for item in added["components"]] == ["chapter-a"]


def test_binding_is_coherent_with_the_component_revision(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    add_component(
        package_root=package, branch_id="main", component_id="finding",
        kind="chapter", title="发现", parent_id=None, body="", content=None,
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
    assert updated["head"]["generation"] == snapshot["head"]["generation"] == 2
    assert snapshot["bindings"] == [{
        "binding_id": "evidence-1", "kind": "evidence",
        "target_ref": "evidence:job-1", "label": "回测证据", "data": {},
        "component_id": "finding",
    }]


def test_batch_rejects_duplicate_identifiers_before_writing_nodes(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    before = created["paths"]["head"].read_bytes()
    operation = {
        "op": "add", "component_id": "same", "kind": "chapter",
        "title": "重复章节", "parent_id": None, "body": "内容",
        "content": None, "display_kind": "", "bindings": [],
    }

    with pytest.raises(ValueError, match="duplicates component_id"):
        apply_batch(
            package_root=package, branch_id="main",
            operations=[operation, dict(operation)],
        )

    assert created["paths"]["head"].read_bytes() == before
    assert not (created["paths"]["nodes"] / "same").exists()


def test_root_rejects_non_chapter_content_before_writing(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    before = created["paths"]["head"].read_bytes()

    with pytest.raises(ValueError, match="root-level report components"):
        add_component(
            package_root=package, branch_id="main", component_id="entry",
            kind="entry", title="正文", parent_id=None, body="", content=None,
            display_kind="",
        )
    with pytest.raises(ValueError, match="root-level report components"):
        apply_batch(
            package_root=package, branch_id="main", operations=[{
                "op": "add", "component_id": "table", "kind": "table",
                "title": "表格", "parent_id": None, "body": "",
                "content": {"columns": ["指标"], "rows": []},
                "display_kind": "", "bindings": [],
            }],
        )

    assert created["paths"]["head"].read_bytes() == before
    assert load_snapshot(package_root=package, branch_id="main")["components"] == []


def test_failed_add_never_leaves_an_unpublished_leaf(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )

    with pytest.raises(ValueError, match="report component does not exist"):
        add_component(
            package_root=package, branch_id="main", component_id="orphan",
            kind="entry", title="孤儿", parent_id="missing", body="", content=None,
            display_kind="",
        )

    assert not (created["paths"]["nodes"] / "orphan").exists()


def test_post_write_failure_discards_new_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )

    def fail_rewrite(*_args, **_kwargs):
        raise OSError("simulated rewrite failure")

    monkeypatch.setattr(tree_changes, "rewrite", fail_rewrite)
    with pytest.raises(OSError, match="simulated rewrite failure"):
        add_component(
            package_root=package, branch_id="main", component_id="orphan",
            kind="chapter", title="孤儿", parent_id=None, body="", content=None,
            display_kind="",
        )

    assert not (created["paths"]["nodes"] / "orphan").exists()


def test_binding_identifier_is_global_and_indexed_incrementally(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    binding = {
        "binding_id": "shared-evidence", "kind": "evidence",
        "target_ref": "evidence:one", "label": "证据", "data": {},
    }
    first = add_component(
        package_root=package, branch_id="main", component_id="first",
        kind="chapter", title="第一项", parent_id=None, body="正文", content=None,
        display_kind="", bindings=[binding],
    )

    with pytest.raises(ValueError, match="binding_id already exists"):
        add_component(
            package_root=package, branch_id="main", component_id="second",
            kind="chapter", title="第二项", parent_id=None, body="正文", content=None,
            display_kind="", bindings=[binding],
        )

    assert first["head"]["generation"] == 1
    assert [item["component_id"] for item in load_snapshot(
        package_root=package, branch_id="main",
    )["components"]] == ["first"]


def test_current_head_keeps_no_superseded_copy_on_write_nodes(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    for index in range(4):
        add_component(
            package_root=package, branch_id="main", component_id=f"entry-{index}",
            kind="chapter", title=str(index), parent_id=None, body="", content=None,
            display_kind="",
        )
    snapshot = load_snapshot(package_root=package, branch_id="main")
    paths = snapshot["paths"]
    reachable = {snapshot["head"]["root_ref"]}
    root = json.loads((paths["root"] / snapshot["head"]["root_ref"]).read_text())
    reachable.update(child["ref"] for child in root["children"])
    stored = {
        str(path.relative_to(paths["root"]))
        for path in paths["nodes"].glob("*/*.json")
    }
    assert stored == reachable


def test_fast_append_never_materializes_the_complete_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )

    def fail_snapshot(**_kwargs):
        raise AssertionError("fast append unexpectedly scanned the report")

    monkeypatch.setattr(tree_model, "load_snapshot", fail_snapshot)
    value = add_component(
        package_root=package, branch_id="main", component_id="entry",
        kind="chapter", title="结果", parent_id=None, body="", content=None,
        display_kind="", include_snapshot=False,
    )

    assert value["head"]["generation"] == 1
    assert value["components"] == []


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

    assert value["head"]["generation"] == 1
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
                    "kind": "chapter", "title": "可重试", "body": "",
                    "content": None, "display_kind": "", "bindings": [],
                },
                {"op": "unsupported"},
            ],
        )

    assert created["paths"]["head"].read_bytes() == before
    assert not (created["paths"]["nodes"] / "recoverable").exists()
    retried = apply_batch(
        package_root=package,
        branch_id="main",
        operations=[{
            "op": "add", "component_id": "recoverable", "kind": "chapter",
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
            {"op": "add", "component_id": "chapter", "kind": "chapter",
             "title": "结果", "body": "", "content": None,
             "display_kind": "", "bindings": []},
            {"op": "add", "component_id": "table", "kind": "special",
             "title": "统计表", "parent_id": "chapter", "body": "", "display_kind": "job-artifact-table",
             "content": {"columns": ["指标", "值"], "rows": [["Sharpe", "1.2"]]}, "bindings": []},
            {"op": "add", "component_id": "image", "kind": "special",
             "title": "净值图", "parent_id": "chapter", "body": "", "display_kind": "job-artifact-image",
             "content": {"asset_ref": "job-artifact:job-1:equity"}, "bindings": []},
        ],
    )
    rendered = render_tree_markdown(load_snapshot(package_root=package, branch_id="main")).decode()
    assert "| 指标 | 值 |" in rendered
    assert "![净值图](factortester-artifact://jobs/job-1/equity)" in rendered


def test_markdown_export_escapes_table_cell_delimiters(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    apply_batch(
        package_root=package, branch_id="main", operations=[
            {"op": "add", "component_id": "chapter", "kind": "chapter",
             "title": "结果", "body": "", "content": None,
             "display_kind": "", "bindings": []},
            {"op": "add", "component_id": "table", "kind": "table",
             "title": "公式", "parent_id": "chapter", "body": "",
             "content": {"columns": ["表达式"],
                         "rows": [[r"\(a|b\)" + "\n第二行"]]},
             "display_kind": "", "bindings": []},
        ],
    )

    rendered = render_tree_markdown(
        load_snapshot(package_root=package, branch_id="main")
    ).decode()
    assert r"\\(a\|b\\)<br>第二行" in rendered


def test_report_tree_rejects_large_inline_table_before_writing(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    operation = {
        "op": "add", "component_id": "chapter", "kind": "chapter",
        "title": "结果", "parent_id": None, "body": "", "display_kind": "",
        "content": {"columns": ["时间"], "rows": [[str(index)] for index in range(201)]},
        "bindings": [],
    }

    with pytest.raises(ValueError, match="inline preview limit"):
        apply_batch(package_root=package, branch_id="main", operations=[operation])

    assert not (created["paths"]["nodes"] / "chapter").exists()
