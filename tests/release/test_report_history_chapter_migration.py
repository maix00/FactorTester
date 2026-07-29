import json
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
from tools.cli.release.research_reporting.maintenance.history_chapters import (
    migrate_history_chapters,
)
from tools.cli.release.research_reporting.maintenance.legacy_binding_kinds import (
    normalized_legacy_binding_kind,
)
from tools.cli.release.research_reporting.node_titles import node_title_zh


def test_node_titles_are_shared_by_authoring_and_history() -> None:
    assert node_title_zh("hypothesis_preregistration") == "假设预注册"
    assert node_title_zh("capability_gap") == "能力缺口"
    assert node_title_zh("trial_execution") == "试验执行"


def test_history_migration_renames_checkpoint_chapter_from_authority(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialized = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )
    paths = initialized["paths"]
    head = load_head(paths)
    root = load_node(paths, head["root_ref"])
    checkpoint = "trace:abc"
    chapter = new_node(
        "legacy-chapter", "chapter", "旧节点",
        "", None, "", [{
            "binding_id": "checkpoint-binding", "kind": "checkpoint",
            "target_ref": checkpoint, "label": "历史检查点", "data": {},
        }],
    )
    chapter_ref, _ = store_node(paths, chapter)
    chapter["title"] = f"历史检查点 {checkpoint}"
    (paths["root"] / chapter_ref).write_text(
        json.dumps(chapter, ensure_ascii=False), encoding="utf-8",
    )
    root["children"] = [{"node_id": "legacy-chapter", "ref": chapter_ref}]
    root_ref, _ = store_node(paths, root)
    write_head(paths, {
        **head, "generation": 1, "root_ref": root_ref,
        "changed_node_ids": ["root", "legacy-chapter"],
        "locator_generation": 0,
    })

    result = migrate_history_chapters(
        package_root=package, branch_id="main",
        checkpoint_nodes={checkpoint: "factor_semantics"},
    )

    assert result["renamed_count"] == 1
    snapshot = load_snapshot(package_root=package, branch_id="main")
    chapter = next(
        item for item in snapshot["components"]
        if item["component_id"] == "legacy-chapter"
    )
    assert chapter["title"] == "因子语义"


def test_legacy_evidence_kind_is_reclassified_by_reference_not_label() -> None:
    assert normalized_legacy_binding_kind(
        "evidence", "evidence:abc",
    ) == "evidence"
    assert normalized_legacy_binding_kind(
        "evidence", "runspec:abc",
    ) == "run_spec"
    assert normalized_legacy_binding_kind(
        "evidence", "decision:abc",
    ) == "graph_reference"


def test_new_checkpoint_placeholder_chapters_are_rejected() -> None:
    with pytest.raises(ValueError, match="research node title"):
        new_node(
            "bad-chapter", "chapter", "历史检查点 trace:abc",
            "", None, "", [],
        )
