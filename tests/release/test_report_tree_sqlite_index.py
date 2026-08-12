from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
    remove_component,
)
from tools.cli.release.research_reporting.authoring.tree_presence import (
    ReportTreePresence,
)
from tools.cli.release.research_reporting.authoring.tree_sqlite_index import (
    ensure_sqlite_index,
    verify_sqlite_index,
)
from tools.cli.release.research_reporting.authoring.tree_store import (
    load_head,
    load_node,
)


def test_new_tree_builds_and_updates_sqlite_index(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package,
        branch_id="main",
        report_id="report-wp",
        title="研究报告",
    )
    add_component(
        package_root=package,
        branch_id="main",
        component_id="chapter",
        kind="chapter",
        title="假设登记",
        parent_id=None,
        body="",
        content=None,
        display_kind="",
        bindings=[{
            "binding_id": "evidence-one",
            "kind": "evidence",
            "target_ref": "evidence:one",
            "label": "证据",
            "data": {},
        }],
        include_snapshot=False,
    )

    presence = ReportTreePresence.load(
        package_root=package,
        branch_id="main",
    )
    checked = verify_sqlite_index(
        created["paths"], presence.root, presence.head["generation"],
    )

    assert checked == {
        "components": 1,
        "current_bindings": 1,
        "registered_bindings": 1,
    }
    assert presence.component_exists("chapter")
    assert presence.binding_exists("evidence-one")
    with sqlite3.connect(created["paths"]["index_db"]) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_missing_sqlite_index_rebuilds_from_tree_and_registry(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package,
        branch_id="main",
        report_id="report-wp",
        title="研究报告",
    )
    add_component(
        package_root=package,
        branch_id="main",
        component_id="chapter",
        kind="chapter",
        title="假设登记",
        parent_id=None,
        body="",
        content=None,
        display_kind="",
        include_snapshot=False,
    )
    created["paths"]["binding_registry"].write_text(
        '{"binding_id":"historical-binding"}\n',
        encoding="utf-8",
    )
    created["paths"]["index_db"].unlink()
    head = load_head(created["paths"])
    root = load_node(created["paths"], head["root_ref"])

    ensure_sqlite_index(created["paths"], root, head["generation"])

    with sqlite3.connect(created["paths"]["index_db"]) as db:
        assert db.execute(
            "SELECT parent_id FROM component_locator WHERE node_id='chapter'"
        ).fetchone() == ("root",)
        assert db.execute(
            "SELECT binding_id FROM binding_registry"
        ).fetchall() == [("historical-binding",)]


def test_node_files_are_readable_without_changing_content_hash(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package,
        branch_id="main",
        report_id="report-wp",
        title="研究报告",
    )
    head = load_head(created["paths"])
    path = created["paths"]["root"] / head["root_ref"]

    payload = path.read_text(encoding="utf-8")

    assert "\n  \"bindings\"" in payload
    assert json.loads(payload)["node_id"] == "root"


def test_removed_component_is_removed_from_sqlite_projection(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package,
        branch_id="main",
        report_id="report-wp",
        title="研究报告",
    )
    add_component(
        package_root=package, branch_id="main", component_id="chapter",
        kind="chapter", title="章节", parent_id=None, body="",
        content=None, display_kind="", include_snapshot=False,
    )
    add_component(
        package_root=package, branch_id="main", component_id="section",
        kind="section", title="小节", parent_id="chapter", body="",
        content=None, display_kind="", include_snapshot=False,
    )
    remove_component(
        package_root=package, branch_id="main", component_id="section",
        include_children=False, include_snapshot=False,
    )
    head = load_head(created["paths"])
    root = load_node(created["paths"], head["root_ref"])

    assert verify_sqlite_index(
        created["paths"], root, head["generation"],
    )["components"] == 1
    with sqlite3.connect(created["paths"]["index_db"]) as db:
        assert db.execute(
            "SELECT node_id FROM component_locator"
        ).fetchall() == [("chapter",)]
