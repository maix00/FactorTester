from __future__ import annotations

import json

from tools.cli.commands import research_report_history_reconciliation as history
from tools.cli.commands.research_graph_report_sync import (
    synchronize_report_container,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    load_snapshot,
)
from tools.cli.release.research_reporting.git import commit_work_package

from tests.cli.test_research_graph_detour_report import _scope
from tests.cli.test_research_report_history_reconciliation import _Client


class _ReportRefClient(_Client):
    def __init__(self) -> None:
        super().__init__()
        refs = {
            "trace:t1": ["report:data-a"],
            "trace:t2": ["report:resolution", "report:gap"],
            "trace:t3": ["report:gap"],
            "trace:t4": ["report:data-b"],
            "trace:t5": ["report:factor-a"],
        }
        for item in self.items:
            item["evidence_refs"] = refs[item["step_ref"]]


def _entry(scope, component_id: str, parent_id: str) -> None:
    add_component(
        package_root=scope.package_root, branch_id=scope.branch_id,
        component_id=component_id, kind="entry", title=component_id,
        parent_id=parent_id, body="既有内容", content=None, display_kind="",
        bindings=[],
    )


def test_history_report_refs_move_to_recorded_containers_idempotently(
    tmp_path,
    monkeypatch,
) -> None:
    scope, _ = _scope(tmp_path)
    chapter = synchronize_report_container(
        scope, container={
            "kind": "chapter", "anchor_node": "hypothesis_preregistration",
            "current_node": "hypothesis_preregistration",
            "latest_trace_id": "",
        },
    )
    special_id = "profile-screen-alias-capability-resolution"
    add_component(
        package_root=scope.package_root, branch_id=scope.branch_id,
        component_id=special_id, kind="special", title="能力缺口",
        parent_id=chapter["component_id"], body="人工记录", content={"old": 1},
        display_kind="capability_resolution", bindings=[],
    )
    for component_id in (
        "data-a", "resolution", "gap", "data-b", "factor-a",
    ):
        _entry(scope, component_id, chapter["component_id"])
    commit_work_package(scope.package_root, message="Historical report fixture")
    record = scope.store.load("maxa")["research_records"][0]
    scope.store.upsert_research_record("maxa", {
        **record, "graph_instance_ref": "work-package:wp",
    })
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({
        "schema_version": 2,
        "episode_components": {
            "capability-detour:t2": special_id,
        },
        "component_parents": {
            "factor-a": chapter["component_id"],
        },
        "component_special_kinds": {},
    }), encoding="utf-8")
    monkeypatch.setattr(
        history, "load_profile_root", lambda _path: scope.client_root,
    )
    kwargs = {
        "profile_id": "maxa", "work_package_id": "wp",
        "branch_id": "branch", "release_profile": None,
        "component_map_file": mapping, "apply_changes": True,
        "client": _ReportRefClient(),
    }

    applied = history._reconcile(**kwargs)
    snapshot = load_snapshot(
        package_root=scope.package_root, branch_id=scope.branch_id,
    )
    by_id = {item["component_id"]: item for item in snapshot["components"]}
    data = next(item for item in snapshot["components"] if item["title"] == "数据契约")
    factor = next(item for item in snapshot["components"] if item["title"] == "因子语义")
    for component_id in ("resolution", "gap", "data-b"):
        assert by_id[component_id]["parent_id"] == special_id
    assert [
        item["component_id"] for item in snapshot["components"]
        if item["parent_id"] == special_id
    ] == ["resolution", "gap", "data-b"]
    assert by_id["data-a"]["parent_id"] == data["component_id"]
    assert by_id["factor-a"]["parent_id"] == factor["component_id"]
    assert applied["ignored_system_parent_hints"] == ["factor-a"]
    assert applied["placement"]["unresolved_report_refs"] == []

    repeated = history._reconcile(**kwargs)
    assert repeated["moved_item_count"] == 0
    assert repeated["git"]["committed"] is False
