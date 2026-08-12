from __future__ import annotations

from tools.cli.commands.research_report_history_cleanup import (
    cleanup_legacy_chapters,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
    load_snapshot,
)


def _add(
    root, component_id, kind, title, parent_id=None, bindings=None,
):
    add_component(
        package_root=root,
        branch_id="branch",
        component_id=component_id,
        kind=kind,
        title=title,
        parent_id=parent_id,
        body="正文" if kind != "chapter" else "",
        content=None,
        display_kind="",
        bindings=bindings or [],
    )


def _checkpoint(binding_id):
    return [{
        "binding_id": binding_id,
        "kind": "checkpoint",
        "target_ref": "trace:one",
        "label": "检查点",
        "data": {"role": "historical"},
    }]


def test_cleanup_merges_safe_duplicates_and_removes_legacy_chapters(
    tmp_path,
) -> None:
    initialize_tree(
        package_root=tmp_path,
        branch_id="branch",
        report_id="report",
        title="报告",
    )
    _add(tmp_path, "canonical", "chapter", "因子语义")
    _add(tmp_path, "legacy-one", "chapter", "因子语义")
    _add(tmp_path, "legacy-two", "chapter", "能力缺口")
    _add(tmp_path, "duplicate-a", "section", "语义", "canonical")
    _add(
        tmp_path,
        "duplicate-b",
        "section",
        "语义",
        "legacy-one",
        _checkpoint("checkpoint-binding"),
    )
    _add(tmp_path, "unique", "section", "机制", "legacy-one")

    result = cleanup_legacy_chapters(
        package_root=tmp_path,
        branch_id="branch",
        canonical_component_ids={"canonical"},
    )
    snapshot = load_snapshot(
        package_root=tmp_path, branch_id="branch",
    )
    components = {
        item["component_id"]: item for item in snapshot["components"]
    }

    assert result["removed_duplicates"] == ["duplicate-a"]
    assert set(result["removed_legacy_chapters"]) == {
        "legacy-one", "legacy-two",
    }
    assert result["unresolved_legacy_chapters"] == []
    assert set(components) == {"canonical", "duplicate-b", "unique"}
    assert components["duplicate-b"]["parent_id"] == "canonical"
    assert components["unique"]["parent_id"] == "canonical"
    assert snapshot["bindings"][0]["binding_id"] == "checkpoint-binding"


def test_cleanup_keeps_duplicates_with_distinct_binding_semantics(
    tmp_path,
) -> None:
    initialize_tree(
        package_root=tmp_path,
        branch_id="branch",
        report_id="report",
        title="报告",
    )
    _add(tmp_path, "canonical", "chapter", "验证设计")
    _add(tmp_path, "legacy", "chapter", "验证设计")
    _add(
        tmp_path, "one", "section", "设计", "canonical",
        _checkpoint("binding-one"),
    )
    distinct = _checkpoint("binding-two")
    distinct[0]["target_ref"] = "trace:two"
    _add(tmp_path, "two", "section", "设计", "legacy", distinct)

    result = cleanup_legacy_chapters(
        package_root=tmp_path,
        branch_id="branch",
        canonical_component_ids={"canonical"},
    )
    snapshot = load_snapshot(
        package_root=tmp_path, branch_id="branch",
    )

    assert result["removed_duplicates"] == []
    assert {
        item["component_id"] for item in snapshot["components"]
    } == {"canonical", "one", "two"}
