"""One-time migration seams for report trees written before root-only chapters."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring.tree_changes import new_node
from tools.cli.release.research_reporting.authoring.tree_model import (
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_store import (
    load_head,
    load_node,
    store_node,
    write_head,
)
from tools.cli.release.research_reporting.maintenance.root_hierarchy import (
    inspect_root_hierarchy,
    migrate_single_chapter_root,
)


def test_migration_moves_root_content_under_the_only_chapter(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    paths = created["paths"]
    head = load_head(paths)
    root = load_node(paths, head["root_ref"])
    chapter_ref, _ = store_node(paths, new_node(
        "chapter", "chapter", "假设登记", "", None, "", [],
    ))
    entry_ref, _ = store_node(paths, new_node(
        "finding", "entry", "研究发现", "正文", None, "", [],
    ))
    invalid_root = deepcopy(root)
    invalid_root["children"] = [
        {"node_id": "chapter", "ref": chapter_ref},
        {"node_id": "finding", "ref": entry_ref},
    ]
    invalid_root_ref, _ = store_node(paths, invalid_root)
    write_head(paths, {
        **head, "generation": 1, "root_ref": invalid_root_ref,
        "changed_node_ids": ["root", "chapter", "finding"],
        "locator_generation": 1,
    })

    plan = inspect_root_hierarchy(package_root=package, branch_id="main")
    assert plan["status"] == "migratable"
    migrated = migrate_single_chapter_root(package_root=package, branch_id="main")

    assert migrated["moved_component_ids"] == ["finding"]
    snapshot = load_snapshot(package_root=package, branch_id="main")
    chapter = next(item for item in snapshot["components"] if item["component_id"] == "chapter")
    finding = next(item for item in snapshot["components"] if item["component_id"] == "finding")
    assert finding["parent_id"] == chapter["component_id"]
    assert migrated["head"]["generation"] == 2


def test_migration_rejects_an_ambiguous_root(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    paths = created["paths"]
    head = load_head(paths)
    root = load_node(paths, head["root_ref"])
    refs = []
    for node_id, kind in (("first", "chapter"), ("second", "chapter"), ("entry", "entry")):
        ref, _ = store_node(paths, new_node(node_id, kind, node_id, "", None, "", []))
        refs.append({"node_id": node_id, "ref": ref})
    invalid_root = deepcopy(root)
    invalid_root["children"] = refs
    root_ref, _ = store_node(paths, invalid_root)
    write_head(paths, {
        **head, "generation": 1, "root_ref": root_ref,
        "changed_node_ids": ["root"], "locator_generation": 1,
    })

    assert inspect_root_hierarchy(
        package_root=package, branch_id="main",
    )["status"] == "ambiguous"
    with pytest.raises(ValueError, match="ambiguous"):
        migrate_single_chapter_root(package_root=package, branch_id="main")
