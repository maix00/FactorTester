"""Regression coverage for the compact report authoring layout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring.tree_changes import new_node
from tools.cli.release.research_reporting.authoring.tree_paths import (
    report_tree_paths,
)
from tools.cli.release.research_reporting.authoring.tree_store import store_node
from tools.cli.release.research_reporting.authoring.tree_store import load_head


def test_report_tree_uses_sqlite_indexes_and_hash_sharded_nodes(
    tmp_path: Path,
) -> None:
    paths = report_tree_paths(tmp_path, "main")
    reference, node_hash = store_node(
        paths,
        new_node("finding", "entry", "研究发现", "正文", None, "", []),
    )

    assert reference == f"nodes/{node_hash[:2]}/{node_hash}.json"
    assert paths["index_db"].name == "index.sqlite"
    assert paths["submission_db"].name == "submission.sqlite"
    assert "locators" not in paths
    assert "binding_locators" not in paths
    assert "submission_receipts" not in paths

    payload = (paths["root"] / reference).read_text(encoding="utf-8")
    assert payload.startswith("{\n")
    assert '\n  "body": "正文"' in payload


def test_new_report_head_uses_storage_schema_three(tmp_path: Path) -> None:
    from tools.cli.release.research_reporting.authoring.tree_model import (
        initialize_tree,
    )

    created = initialize_tree(
        package_root=tmp_path / "research" / "wp",
        branch_id="main",
        report_id="report-wp",
        title="研究报告",
    )

    assert created["head"]["schema_version"] == 3
    assert load_head(created["paths"])["schema_version"] == 3


def test_previous_storage_schema_cannot_be_written_by_current_runtime(
    tmp_path: Path,
) -> None:
    from tools.cli.release.research_reporting.authoring.tree_model import (
        initialize_tree,
    )

    created = initialize_tree(
        package_root=tmp_path / "research" / "wp",
        branch_id="main",
        report_id="report-wp",
        title="研究报告",
    )
    head_path = created["paths"]["head"]
    head = json.loads(head_path.read_text(encoding="utf-8"))
    head["schema_version"] = 2
    head_path.write_text(json.dumps(head), encoding="utf-8")

    with pytest.raises(ValueError, match="HEAD schema is invalid"):
        load_head(created["paths"])
