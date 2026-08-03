"""Regression coverage for the compact report authoring layout."""

from __future__ import annotations

from pathlib import Path

from tools.cli.release.research_reporting.authoring.tree_changes import new_node
from tools.cli.release.research_reporting.authoring.tree_paths import (
    report_tree_paths,
)
from tools.cli.release.research_reporting.authoring.tree_store import store_node


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
